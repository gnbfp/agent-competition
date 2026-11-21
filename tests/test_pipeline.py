"""Exercise the one-command pipeline and the live report transport."""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from http.client import HTTPResponse
from pathlib import Path
from types import SimpleNamespace

from contracts.validate_contract import load_json, validate_file
from src.report_server import report_handler


ROOT = Path(__file__).resolve().parents[1]


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.output = self.scratch / "runs"

    def run_pipeline(self, *args):
        return subprocess.run(
            [sys.executable, "-B", "-m", "src.pipeline", *map(str, args), "-o", str(self.output)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )

    def require_run(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        completed = list(self.output.iterdir())
        self.assertEqual(len(completed), 1, completed)
        self.assertTrue(completed[0].name.startswith("run-"))
        for name in ("activity", "metrics", "plan", "report"):
            self.assertEqual(validate_file(completed[0] / f"{name}.json"), [])
        return completed[0]

    def test_demo_publishes_all_artifacts_and_preserves_partial_import(self):
        run = self.require_run(self.run_pipeline("--demo"))
        metrics, report = (load_json(run / name) for name in ("metrics.json", "report.json"))
        self.assertTrue((run / "data_check.md").is_file())
        self.assertEqual(load_json(run / "import_quality.json"),
                         {"input_rows": 4, "accepted_rows": 2, "skipped_rows": 1,
                          "incomplete_rows": 1, "device_anomaly_rows": 1})
        self.assertIsNone(metrics["load_inputs"]["history_start"])
        self.assertIn("P2_IMPORT_PARTIAL", {item["code"] for item in metrics["flags"]})
        self.assertEqual(report["plan"]["status"], "hold_for_review")
        self.assertEqual(report["plan"]["days"], [])
        self.assertIn("R02", {item["rule_id"] for item in report["risks"]})

    def test_raw_gbk_csv_autodetects_and_normalizes(self):
        source = self.scratch / "device.csv"
        original = ROOT / "data/sample/huawei_export_sample.csv"
        source.write_bytes(original.read_text(encoding="utf-8").encode("gbk"))
        run = self.require_run(self.run_pipeline(
            source, "--as-of", "2026-11-17", "--trimp-profile", "female", "--resting-hr", 55, "--max-hr", 190))
        self.assertEqual(load_json(run / "import_quality.json")["accepted_rows"], 3)
        self.assertTrue((run / "activities_middle.csv").is_file())
        self.assertIn("输入编码：GBK", (run / "data_check.md").read_text(encoding="utf-8"))

    def test_failed_stages_do_not_publish_partial_or_reuse_a_previous_report(self):
        completed = self.require_run(self.run_pipeline("--demo"))
        prior_report = (completed / "report.json").read_bytes()
        strict = self.run_pipeline("--demo", "--strict")
        self.assertEqual(strict.returncode, 1)
        self.assertIn("[P2 导入]", strict.stderr)
        bad_date = self.run_pipeline(ROOT / "data/sample/activities_sample.csv", "--as-of", "bad",
                                     "--trimp-profile", "female", "--resting-hr", 55, "--max-hr", 183)
        self.assertEqual(bad_date.returncode, 1)
        self.assertIn("[P3 指标]", bad_date.stderr)
        self.assertEqual(list(self.output.iterdir()), [completed])
        self.assertEqual((completed / "report.json").read_bytes(), prior_report)

    def test_clean_csv_and_confirmed_context_generate_a_draft(self):
        start = date(2026, 10, 18)
        end = start + timedelta(days=27)
        source, daily, context = (self.scratch / name for name in ("activity.csv", "daily.json", "context.json"))
        types = {}
        with source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("date", "sport", "duration_s", "distance_m", "avg_hr", "max_hr"))
            for offset in range(28):
                day = (start + timedelta(days=offset)).isoformat()
                easy = offset % 7 in (1, 3, 5)
                types[day] = ["easy"] if easy else []
                if easy:
                    writer.writerow((day, "run", 1800, 5000, 130, 160))
        daily.write_text(json.dumps({"athlete_id": "anon_01", "daily": [
            {"date": (end - timedelta(days=offset)).isoformat(), "resting_hr_bpm": 55, "sleep_h": 7}
            for offset in range(9)]}), encoding="utf-8")
        context.write_text(json.dumps({"athlete_id": "anon_01", "pain_reported": False,
                                       "max_hr_source": "measured", "session_types": types}), encoding="utf-8")
        run = self.require_run(self.run_pipeline(source, "--as-of", end.isoformat(), "--history-start", start.isoformat(),
                               "--trimp-profile", "female", "--resting-hr", 55, "--max-hr", 183,
                               "--context", context, "--measurements", daily))
        plan = load_json(run / "plan.json")
        self.assertEqual(plan["status"], "draft")
        self.assertEqual(plan["weekly_targets"]["sessions"], 3)
        self.assertTrue(plan["self_check"]["passed"])

    def test_api_serves_only_the_selected_report_and_clear_failure_statuses(self):
        run = self.require_run(self.run_pipeline("--demo"))
        path = run / "report.json"
        expected = load_json(path)

        handler_type = report_handler(path)

        def request(route, host="127.0.0.1:8080"):
            handler = object.__new__(handler_type)
            handler.server = SimpleNamespace(server_port=8080)
            handler.requestline = f"GET {route} HTTP/1.1"
            handler.request_version = "HTTP/1.1"
            handler.path = route
            handler.headers = {"Host": host}
            handler.wfile = io.BytesIO()
            handler.do_GET()
            handler.wfile.seek(0)
            with HTTPResponse(SimpleNamespace(makefile=lambda *_: handler.wfile)) as response:
                response.begin()
                return response.status, response.headers, response.read()

        status, headers, body = request("/api/report")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(body), expected)
        self.assertEqual(request("/")[1]["Location"], "/live")
        self.assertIn(b"window.location.pathname", request("/live")[2])
        self.assertEqual(request("/api/health")[0], 200)
        self.assertEqual(request("/activity.json")[0], 404)
        self.assertEqual(request("/api/report", "other.example")[0], 400)
        path.write_text("{", encoding="utf-8")
        status, _, body = request("/api/report")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["error"], "report_unavailable")
        path.unlink()
        self.assertEqual(request("/api/report")[0], 404)
        self.assertEqual(request("/api/health")[0], 503)
