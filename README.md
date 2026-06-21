# ⚙️ DevOps Pipeline Monitor

> CLI tool to monitor Jenkins pipelines, track build health, detect failures, and send real-time alerts via Slack or email.

![Python](https://img.shields.io/badge/Python-3.8+-3B82F6?style=flat-square&logo=python&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-17%20passing-22C55E?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-F97316?style=flat-square)

---

## 🧩 What It Does

When you manage multiple Jenkins pipelines, it's painful to:
- Check each job manually to see if builds are green
- Know *why* a build failed and *who* broke it
- Get notified immediately when something goes red
- Generate a health report across all pipelines

This tool does all of that from a single command.

---

## ✨ Features

- ✅ **Pipeline health dashboard** — scans all jobs at once
- ✅ **Failure detection** — identifies failed builds + culprit authors
- ✅ **Slack alerts** — instant notification when a pipeline fails
- ✅ **Email alerts** — SMTP-based failure emails
- ✅ **Health grading** — A/B/C/F grade based on success rate
- ✅ **Watch mode** — continuously re-checks on a set interval
- ✅ **JSON reports** — machine-readable output for dashboards
- ✅ **CI integration** — `--fail-on-red` flag for use inside pipelines

---

## 🚀 Quick Start

```bash
git clone https://github.com/saksham-bhambota/devops-pipeline-monitor
cd devops-pipeline-monitor
pip install -r requirements.txt

# Basic scan
python monitor.py --url http://your-jenkins:8080 --user admin --token YOUR_API_TOKEN

# With Slack alerts
python monitor.py --url http://jenkins:8080 --user admin --token TOKEN \
    --slack-webhook https://hooks.slack.com/services/...

# Watch mode — re-check every 2 minutes
python monitor.py --url http://jenkins:8080 --user admin --token TOKEN \
    --watch --interval 120

# Save JSON report
python monitor.py --url http://jenkins:8080 --user admin --token TOKEN \
    --report-json report.json
```

---

## 📊 Sample Output

```
════════════════════════════════════════════════════════════════════════
  PIPELINE HEALTH REPORT  —  2026-06-14 10:30
════════════════════════════════════════════════════════════════════════
  🏆 Health Score : 87.5% (Grade B)
  ✅ Success : 7   ❌ Failed : 1   🔄 Running : 0   Total : 8
────────────────────────────────────────────────────────────────────────
  JOB                            STATUS       BUILD    DURATION     BUILT AT
────────────────────────────────────────────────────────────────────────
  android-build-a15              ✅ SUCCESS   #142     0:18:32      2026-06-14 10:12:00
  android-build-a14              ✅ SUCCESS   #139     0:17:45      2026-06-14 10:11:00
  unit-tests-python              ✅ SUCCESS   #87      0:02:10      2026-06-14 10:28:00
  integration-tests              ❌ FAILURE   #56      0:04:22      2026-06-14 10:25:00
  docker-build-gerrit            ✅ SUCCESS   #23      0:05:14      2026-06-14 09:50:00
  terraform-apply-dev            ✅ SUCCESS   #11      0:01:45      2026-06-14 09:30:00
  multi-repo-sync                ✅ SUCCESS   #201     0:08:12      2026-06-14 10:00:00
  release-comparator             ✅ SUCCESS   #34      0:12:03      2026-06-14 08:45:00
════════════════════════════════════════════════════════════════════════
```

---

## 🏗️ Architecture

```
monitor.py
├── JenkinsClient          # REST API wrapper (jobs, builds, logs)
├── PipelineHealthAnalyser # Analyse results, compute health grade
├── SlackAlerter           # Webhook-based Slack notifications
├── EmailAlerter           # SMTP email alerts
└── ReportGenerator        # Console + JSON output
```

---

## 🧪 Tests

```bash
python3 -m unittest tests/test_monitor.py -v
# Ran 17 tests — OK
```

Tests cover: status mapping, health grading, JSON reports, Slack alerting, API error handling.

---

## 📋 CLI Reference

| Flag | Description |
|------|-------------|
| `--url` | Jenkins base URL (required) |
| `--user` | Jenkins username (required) |
| `--token` | Jenkins API token (required) |
| `--slack-webhook` | Slack webhook for alerts |
| `--email-to` | Email recipients for alerts |
| `--watch` | Re-check continuously |
| `--interval` | Watch interval in seconds (default: 60) |
| `--report-json` | Save JSON report to file |
| `--fail-on-red` | Exit 1 if any job failed (for CI use) |

---

*Built by [Saksham Bhambota](https://linkedin.com/in/saksham-bhambota) · DevOps Engineer · Pune, India*
