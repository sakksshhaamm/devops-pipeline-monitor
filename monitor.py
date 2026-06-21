#!/usr/bin/env python3
"""
DevOps Pipeline Monitor
=======================
A CLI tool to monitor Jenkins pipelines, track build health,
detect failures, and send alerts via Slack or email.

Author : Saksham Bhambota
GitHub : github.com/saksham-bhambota
"""

import argparse
import json
import logging
import os
import smtplib
import sys
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from typing import Optional
from urllib.parse import urljoin

import requests
from requests.auth import HTTPBasicAuth

# ── Logging setup ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("pipeline_monitor.log"),
    ],
)
log = logging.getLogger(__name__)


# ── Jenkins Client ────────────────────────────────────────────────
class JenkinsClient:
    """Thin wrapper around Jenkins REST API."""

    def __init__(self, url: str, user: str, token: str):
        self.base = url.rstrip("/")
        self.auth = HTTPBasicAuth(user, token)
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, path: str) -> dict:
        url = urljoin(self.base + "/", path.lstrip("/"))
        resp = self.session.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_jobs(self) -> list:
        """Return list of all top-level jobs."""
        data = self._get("/api/json?tree=jobs[name,url,color]")
        return data.get("jobs", [])

    def get_build(self, job_name: str, build_number: str = "lastBuild") -> dict:
        """Return build info for a job."""
        path = f"/job/{job_name}/{build_number}/api/json"
        return self._get(path)

    def get_build_log(self, job_name: str, build_number: str = "lastBuild") -> str:
        """Return console log for a build."""
        url = f"{self.base}/job/{job_name}/{build_number}/consoleText"
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.text


# ── Health Analyser ───────────────────────────────────────────────
class PipelineHealthAnalyser:
    """
    Analyses build results and computes health metrics.
    """

    STATUS_COLORS = {
        "SUCCESS":  "✅",
        "FAILURE":  "❌",
        "UNSTABLE": "⚠️",
        "ABORTED":  "🔴",
        "RUNNING":  "🔄",
        "UNKNOWN":  "❓",
    }

    def __init__(self, client: JenkinsClient):
        self.client = client

    def get_status(self, color: str) -> str:
        mapping = {
            "blue":        "SUCCESS",
            "red":         "FAILURE",
            "yellow":      "UNSTABLE",
            "aborted":     "ABORTED",
            "blue_anime":  "RUNNING",
            "red_anime":   "RUNNING",
        }
        return mapping.get(color, "UNKNOWN")

    def analyse_job(self, job: dict) -> dict:
        """Return rich health info for a single Jenkins job."""
        name = job["name"]
        status = self.get_status(job.get("color", ""))

        try:
            build = self.client.get_build(name)
            duration_s = build.get("duration", 0) / 1000
            timestamp = build.get("timestamp", 0) / 1000
            build_time = datetime.fromtimestamp(timestamp) if timestamp else None

            return {
                "name":        name,
                "status":      status,
                "icon":        self.STATUS_COLORS.get(status, "❓"),
                "build_num":   build.get("number"),
                "duration_s":  round(duration_s, 1),
                "duration_hr": str(timedelta(seconds=int(duration_s))),
                "built_at":    build_time.strftime("%Y-%m-%d %H:%M:%S") if build_time else "N/A",
                "url":         build.get("url", ""),
                "culprits":    [c["fullName"] for c in build.get("culprits", [])],
                "triggered_by": self._get_trigger(build),
            }
        except Exception as exc:
            log.warning("Could not fetch build for %s: %s", name, exc)
            return {
                "name":   name,
                "status": status,
                "icon":   self.STATUS_COLORS.get(status, "❓"),
                "error":  str(exc),
            }

    def _get_trigger(self, build: dict) -> str:
        actions = build.get("actions", [])
        causes = actions[0].get("causes", []) if actions else []
        if not causes:
            return "unknown"
        cause = causes[0]
        if "userName" in cause:
            return f"manual ({cause['userName']})"
        if "shortDescription" in cause:
            return cause["shortDescription"]
        return "unknown"

    def analyse_all(self, jobs: list) -> list:
        results = []
        for job in jobs:
            log.info("Analysing job: %s", job["name"])
            results.append(self.analyse_job(job))
        return results

    @staticmethod
    def compute_summary(results: list) -> dict:
        total   = len(results)
        success = sum(1 for r in results if r.get("status") == "SUCCESS")
        failed  = sum(1 for r in results if r.get("status") == "FAILURE")
        running = sum(1 for r in results if r.get("status") == "RUNNING")
        other   = total - success - failed - running

        health_pct = round((success / total * 100) if total else 0, 1)
        return {
            "total":      total,
            "success":    success,
            "failed":     failed,
            "running":    running,
            "other":      other,
            "health_pct": health_pct,
            "grade":      "A" if health_pct >= 90 else
                          "B" if health_pct >= 75 else
                          "C" if health_pct >= 60 else "F",
        }


# ── Alerting ──────────────────────────────────────────────────────
class SlackAlerter:
    """Send alerts to a Slack webhook."""

    def __init__(self, webhook_url: str):
        self.webhook = webhook_url

    def send(self, message: str, color: str = "#F97316") -> bool:
        payload = {
            "attachments": [{
                "color": color,
                "text":  message,
                "footer": "DevOps Pipeline Monitor",
                "ts":    int(time.time()),
            }]
        }
        try:
            resp = requests.post(self.webhook, json=payload, timeout=10)
            resp.raise_for_status()
            log.info("Slack alert sent")
            return True
        except Exception as exc:
            log.error("Slack alert failed: %s", exc)
            return False

    def alert_failure(self, job: dict):
        culprits = ", ".join(job.get("culprits", [])) or "unknown"
        msg = (
            f"*❌ BUILD FAILED: {job['name']}*\n"
            f"> Build #{job.get('build_num')} failed\n"
            f"> Culprits: {culprits}\n"
            f"> Duration: {job.get('duration_hr', 'N/A')}\n"
            f"> <{job.get('url', '')}|View Build>"
        )
        self.send(msg, color="#EF4444")

    def alert_summary(self, summary: dict, failed_jobs: list):
        grade_emoji = {"A": "🏆", "B": "👍", "C": "⚠️", "F": "🚨"}.get(summary["grade"], "❓")
        msg = (
            f"*{grade_emoji} Pipeline Health Report*\n"
            f"> Health Score: *{summary['health_pct']}%* (Grade {summary['grade']})\n"
            f"> ✅ Success: {summary['success']}  "
            f"❌ Failed: {summary['failed']}  "
            f"🔄 Running: {summary['running']}\n"
        )
        if failed_jobs:
            msg += "\n*Failed Jobs:*\n"
            for j in failed_jobs:
                msg += f"• `{j['name']}` — Build #{j.get('build_num', '?')}\n"

        color = "#22C55E" if summary["grade"] in ("A", "B") else "#EF4444"
        self.send(msg, color=color)


class EmailAlerter:
    """Send alerts via SMTP email."""

    def __init__(self, smtp_host: str, smtp_port: int,
                 sender: str, password: str, recipients: list):
        self.smtp_host  = smtp_host
        self.smtp_port  = smtp_port
        self.sender     = sender
        self.password   = password
        self.recipients = recipients

    def send(self, subject: str, body: str) -> bool:
        msg = MIMEText(body, "plain")
        msg["Subject"] = subject
        msg["From"]    = self.sender
        msg["To"]      = ", ".join(self.recipients)
        try:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.recipients, msg.as_string())
            log.info("Email sent to %s", self.recipients)
            return True
        except Exception as exc:
            log.error("Email failed: %s", exc)
            return False

    def alert_failure(self, job: dict):
        subject = f"[ALERT] Jenkins Build FAILED: {job['name']}"
        body = (
            f"Build Failure Detected\n"
            f"{'='*40}\n"
            f"Job     : {job['name']}\n"
            f"Build # : {job.get('build_num', 'N/A')}\n"
            f"Status  : {job['status']}\n"
            f"Built At: {job.get('built_at', 'N/A')}\n"
            f"Duration: {job.get('duration_hr', 'N/A')}\n"
            f"Culprits: {', '.join(job.get('culprits', [])) or 'unknown'}\n"
            f"URL     : {job.get('url', 'N/A')}\n"
        )
        self.send(subject, body)


# ── Report Generator ──────────────────────────────────────────────
class ReportGenerator:

    @staticmethod
    def console_report(results: list, summary: dict):
        grade_emoji = {"A": "🏆", "B": "👍", "C": "⚠️", "F": "🚨"}.get(summary["grade"], "❓")
        width = 72

        print("\n" + "=" * width)
        print(f"  PIPELINE HEALTH REPORT  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("=" * width)
        print(f"  {grade_emoji} Health Score : {summary['health_pct']}% (Grade {summary['grade']})")
        print(f"  ✅ Success : {summary['success']}   "
              f"❌ Failed : {summary['failed']}   "
              f"🔄 Running : {summary['running']}   "
              f"Total : {summary['total']}")
        print("-" * width)
        print(f"  {'JOB':<30} {'STATUS':<12} {'BUILD':<8} {'DURATION':<12} BUILT AT")
        print("-" * width)
        for r in results:
            icon   = r.get("icon", "❓")
            status = r.get("status", "UNKNOWN")
            num    = str(r.get("build_num", "-"))
            dur    = r.get("duration_hr", "-")
            when   = r.get("built_at", "-")
            print(f"  {r['name']:<30} {icon} {status:<10} #{num:<7} {dur:<12} {when}")
        print("=" * width + "\n")

    @staticmethod
    def json_report(results: list, summary: dict, path: str = "report.json"):
        data = {
            "generated_at": datetime.now().isoformat(),
            "summary":      summary,
            "jobs":         results,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        log.info("JSON report saved to %s", path)


# ── CLI ───────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser(
        description="Monitor Jenkins pipelines and alert on failures",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python monitor.py --url http://jenkins:8080 --user admin --token abc123
  python monitor.py --url http://jenkins:8080 --user admin --token abc123 \\
      --slack-webhook https://hooks.slack.com/... --watch --interval 60
  python monitor.py --url http://jenkins:8080 --user admin --token abc123 \\
      --report-json report.json
        """
    )
    p.add_argument("--url",           required=True,  help="Jenkins base URL")
    p.add_argument("--user",          required=True,  help="Jenkins username")
    p.add_argument("--token",         required=True,  help="Jenkins API token")
    p.add_argument("--slack-webhook", default=None,   help="Slack webhook URL for alerts")
    p.add_argument("--email-to",      nargs="+",      help="Alert email recipients")
    p.add_argument("--smtp-host",     default="smtp.gmail.com")
    p.add_argument("--smtp-port",     default=465,    type=int)
    p.add_argument("--smtp-user",     default=None)
    p.add_argument("--smtp-pass",     default=None)
    p.add_argument("--watch",         action="store_true",
                   help="Keep watching — re-check on interval")
    p.add_argument("--interval",      default=60,     type=int,
                   help="Watch interval in seconds (default: 60)")
    p.add_argument("--report-json",   default=None,   help="Save JSON report to file")
    p.add_argument("--fail-on-red",   action="store_true",
                   help="Exit code 1 if any job failed (useful in CI)")
    return p.parse_args()


def run_once(client, analyser, args) -> tuple:
    jobs    = client.get_jobs()
    results = analyser.analyse_all(jobs)
    summary = PipelineHealthAnalyser.compute_summary(results)
    failed  = [r for r in results if r.get("status") == "FAILURE"]

    ReportGenerator.console_report(results, summary)

    if args.report_json:
        ReportGenerator.json_report(results, summary, args.report_json)

    # Alerts
    if args.slack_webhook:
        alerter = SlackAlerter(args.slack_webhook)
        alerter.alert_summary(summary, failed)
        for job in failed:
            alerter.alert_failure(job)

    if args.email_to and args.smtp_user:
        ea = EmailAlerter(
            args.smtp_host, args.smtp_port,
            args.smtp_user, args.smtp_pass or "",
            args.email_to,
        )
        for job in failed:
            ea.alert_failure(job)

    return results, summary, failed


def main():
    args   = parse_args()
    client = JenkinsClient(args.url, args.user, args.token)
    analyser = PipelineHealthAnalyser(client)

    if args.watch:
        log.info("Watch mode ON — checking every %ds. Ctrl+C to stop.", args.interval)
        while True:
            try:
                run_once(client, analyser, args)
                time.sleep(args.interval)
            except KeyboardInterrupt:
                log.info("Monitor stopped.")
                break
    else:
        _, summary, failed = run_once(client, analyser, args)
        if args.fail_on_red and failed:
            sys.exit(1)


if __name__ == "__main__":
    main()
