"""
Unit tests for DevOps Pipeline Monitor
"""
import json
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

from monitor import (
    JenkinsClient,
    PipelineHealthAnalyser,
    ReportGenerator,
    SlackAlerter,
)


class TestPipelineHealthAnalyser(unittest.TestCase):

    def setUp(self):
        self.client = MagicMock(spec=JenkinsClient)
        self.analyser = PipelineHealthAnalyser(self.client)

    # ── get_status ────────────────────────────────────────────────
    def test_get_status_blue_is_success(self):
        self.assertEqual(self.analyser.get_status("blue"), "SUCCESS")

    def test_get_status_red_is_failure(self):
        self.assertEqual(self.analyser.get_status("red"), "FAILURE")

    def test_get_status_yellow_is_unstable(self):
        self.assertEqual(self.analyser.get_status("yellow"), "UNSTABLE")

    def test_get_status_anime_suffix_is_running(self):
        self.assertEqual(self.analyser.get_status("blue_anime"), "RUNNING")
        self.assertEqual(self.analyser.get_status("red_anime"), "RUNNING")

    def test_get_status_unknown_color(self):
        self.assertEqual(self.analyser.get_status("notacolor"), "UNKNOWN")

    # ── analyse_job ───────────────────────────────────────────────
    def test_analyse_job_success(self):
        self.client.get_build.return_value = {
            "number":    42,
            "duration":  120000,   # 2 minutes in ms
            "timestamp": 1_700_000_000_000,
            "url":       "http://jenkins/job/my-job/42/",
            "culprits":  [],
            "actions":   [{"causes": [{"userName": "saksham"}]}],
        }
        job = {"name": "my-job", "color": "blue"}
        result = self.analyser.analyse_job(job)

        self.assertEqual(result["name"],   "my-job")
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["build_num"], 42)
        self.assertEqual(result["duration_s"], 120.0)

    def test_analyse_job_failure_with_culprits(self):
        self.client.get_build.return_value = {
            "number":    10,
            "duration":  5000,
            "timestamp": 1_700_000_000_000,
            "url":       "http://jenkins/job/fail-job/10/",
            "culprits":  [{"fullName": "Bob"}, {"fullName": "Alice"}],
            "actions":   [],
        }
        job = {"name": "fail-job", "color": "red"}
        result = self.analyser.analyse_job(job)

        self.assertEqual(result["status"], "FAILURE")
        self.assertIn("Bob",   result["culprits"])
        self.assertIn("Alice", result["culprits"])

    def test_analyse_job_api_error_returns_partial(self):
        self.client.get_build.side_effect = Exception("Connection refused")
        job = {"name": "broken-job", "color": "red"}
        result = self.analyser.analyse_job(job)

        self.assertEqual(result["name"],   "broken-job")
        self.assertEqual(result["status"], "FAILURE")
        self.assertIn("error", result)

    # ── compute_summary ───────────────────────────────────────────
    def test_compute_summary_all_success(self):
        results = [{"status": "SUCCESS"}] * 10
        s = PipelineHealthAnalyser.compute_summary(results)
        self.assertEqual(s["health_pct"], 100.0)
        self.assertEqual(s["grade"], "A")
        self.assertEqual(s["success"], 10)
        self.assertEqual(s["failed"],  0)

    def test_compute_summary_all_failed(self):
        results = [{"status": "FAILURE"}] * 5
        s = PipelineHealthAnalyser.compute_summary(results)
        self.assertEqual(s["health_pct"], 0.0)
        self.assertEqual(s["grade"], "F")
        self.assertEqual(s["failed"], 5)

    def test_compute_summary_mixed(self):
        results = (
            [{"status": "SUCCESS"}] * 7 +
            [{"status": "FAILURE"}] * 2 +
            [{"status": "RUNNING"}] * 1
        )
        s = PipelineHealthAnalyser.compute_summary(results)
        self.assertEqual(s["total"],      10)
        self.assertEqual(s["success"],     7)
        self.assertEqual(s["failed"],      2)
        self.assertEqual(s["running"],     1)
        self.assertEqual(s["health_pct"], 70.0)
        self.assertEqual(s["grade"], "C")

    def test_compute_summary_empty(self):
        s = PipelineHealthAnalyser.compute_summary([])
        self.assertEqual(s["health_pct"], 0.0)
        self.assertEqual(s["total"], 0)

    def test_grade_boundaries(self):
        def make(n_success, total):
            r = [{"status": "SUCCESS"}] * n_success
            r += [{"status": "FAILURE"}] * (total - n_success)
            return PipelineHealthAnalyser.compute_summary(r)

        self.assertEqual(make(9, 10)["grade"], "A")   # 90%
        self.assertEqual(make(8, 10)["grade"], "B")   # 80%
        self.assertEqual(make(7, 10)["grade"], "C")   # 70% → C (need ≥75 for B)
        self.assertEqual(make(6, 10)["grade"], "C")   # 60%
        self.assertEqual(make(5, 10)["grade"], "F")   # 50%


class TestReportGenerator(unittest.TestCase):

    def test_json_report_creates_file(self):
        import os, tempfile
        results = [{"name": "job-1", "status": "SUCCESS", "build_num": 1,
                    "duration_hr": "0:02:00", "built_at": "2026-06-14 10:00:00"}]
        summary = {"total": 1, "success": 1, "failed": 0,
                   "running": 0, "other": 0, "health_pct": 100.0, "grade": "A"}
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        ReportGenerator.json_report(results, summary, path)
        with open(path) as f:
            data = json.load(f)
        self.assertIn("summary",      data)
        self.assertIn("jobs",         data)
        self.assertIn("generated_at", data)
        self.assertEqual(data["summary"]["health_pct"], 100.0)
        os.unlink(path)


class TestSlackAlerter(unittest.TestCase):

    @patch("monitor.requests.post")
    def test_send_success(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.raise_for_status = MagicMock()
        alerter = SlackAlerter("https://hooks.slack.com/fake")
        result  = alerter.send("Test message")
        self.assertTrue(result)
        mock_post.assert_called_once()

    @patch("monitor.requests.post", side_effect=Exception("Timeout"))
    def test_send_failure_returns_false(self, _):
        alerter = SlackAlerter("https://hooks.slack.com/fake")
        result  = alerter.send("Test message")
        self.assertFalse(result)

    @patch("monitor.requests.post")
    def test_alert_failure_message_contains_job_name(self, mock_post):
        mock_post.return_value.raise_for_status = MagicMock()
        alerter = SlackAlerter("https://hooks.slack.com/fake")
        job = {
            "name": "my-pipeline", "status": "FAILURE",
            "build_num": 7, "culprits": ["Alice"],
            "duration_hr": "0:01:30", "url": "http://jenkins/job/7/"
        }
        alerter.alert_failure(job)
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if call_kwargs.args else {}
        text = str(payload)
        self.assertIn("my-pipeline", text)
        self.assertIn("Alice",       text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
