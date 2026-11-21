"""Exercise the one-command pipeline and the live report transport."""

from __future__ import annotations

import base64
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
from src.pipeline import SAMPLE, browser_run
from src.report_server import report_handler


ROOT = Path(__file__).resolve().parents[1]


def request(handler_type, route, host="127.0.0.1:8080", *, data=None, origin=None):
    method = "POST" if data is not None else "GET"
    handler = object.__new__(handler_type)
    handler.server = SimpleNamespace(server_port=8080)
    handler.requestline = f"{method} {route} HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.path = route
    handler.headers = {"Host": host}
    handler.wfile = io.BytesIO()
    if method == "POST":
        payload = json.dumps(data).encode()
        handler.headers.update({"Content-Type": "application/json", "Content-Length": str(len(payload))})
        if origin is not None:
            handler.headers["Origin"] = origin
        handler.connection = SimpleNamespace(settimeout=lambda _: None)
        handler.rfile = io.BytesIO(payload)
        handler.do_POST()
    else:
        handler.do_GET()
    handler.wfile.seek(0)
    with HTTPResponse(SimpleNamespace(makefile=lambda *_: handler.wfile)) as response:
        response.begin()
        return response.status, response.headers, response.read()


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

        status, headers, body = request(handler_type, "/api/report")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(body), expected)
        self.assertEqual(request(handler_type, "/")[1]["Location"], "/live")
        self.assertIn(b"dashboard.js", request(handler_type, "/live")[2])
        self.assertIn(b"window.location.pathname", request(handler_type, "/dashboard.js")[2])
        self.assertEqual(request(handler_type, "/api/health")[0], 200)
        self.assertEqual(request(handler_type, "/activity.json")[0], 404)
        self.assertEqual(request(handler_type, "/api/report", "other.example")[0], 400)
        path.write_text("{", encoding="utf-8")
        status, _, body = request(handler_type, "/api/report")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["error"], "report_unavailable")
        path.unlink()
        self.assertEqual(request(handler_type, "/api/report")[0], 404)
        self.assertEqual(request(handler_type, "/api/health")[0], 503)

    def test_browser_submissions_publish_only_successful_same_origin_runs(self):
        first = self.require_run(self.run_pipeline("--demo"))
        server = report_handler(first / "report.json", on_run=lambda payload: browser_run(payload, self.output))
        previous = json.loads(request(server, "/api/snapshot")[2])
        self.assertEqual(previous["report"]["plan"]["status"], "hold_for_review")
        self.assertEqual(previous["import_quality"]["device_anomaly_rows"], 1)

        def submit(payload, origin="http://127.0.0.1:8080"):
            return request(server, "/api/run", data=payload, origin=origin)

        self.assertEqual(submit({"mode": "demo"}, None)[0], 403)
        self.assertEqual(submit({"mode": "demo"}, "https://other.example")[0], 403)
        self.assertEqual(submit({"mode": "csv", "csv": "not base64"})[0], 422)
        self.assertEqual(json.loads(request(server, "/api/snapshot")[2]), previous)
        self.assertEqual(list(self.output.iterdir()), [first])

        status, _, body = submit({"mode": "demo"})
        self.assertEqual(status, 200, body)
        result = json.loads(body)
        plan = result["report"]["plan"]
        self.assertEqual(plan["status"], "draft")
        self.assertEqual(len(plan["days"]), 7)
        self.assertEqual([check["passed"] for check in plan["attempts"][0]["checks"]], [False, False])
        self.assertTrue(plan["self_check"]["passed"])
        self.assertEqual(result["import_quality"]["accepted_rows"], 12)
        self.assertEqual(json.loads(request(server, "/api/snapshot")[2]), result)
        self.assertEqual(len(list(self.output.iterdir())), 2)

    def test_browser_csv_preserves_gbk_and_reuses_the_p4_answer_flow(self):
        sample = (SAMPLE / "huawei_export_sample.csv").read_text(encoding="utf-8")
        payload = {"mode": "csv", "csv": base64.b64encode(sample.encode("gbk")).decode(),
                   "options": {"as_of": "2026-11-17", "resting_hr": 55, "max_hr": 190,
                               "trimp_profile": "female"}}
        first = browser_run(payload, self.output)
        self.assertIn("输入编码：GBK", (first / "data_check.md").read_text(encoding="utf-8"))
        report = load_json(first / "report.json")
        self.assertIn("pain_reported", {question["key"] for question in report["questions"]})

        second = browser_run({**payload, "answers": {"pain_reported": True}}, self.output)
        report = load_json(second / "report.json")
        self.assertEqual(report["plan"]["status"], "hold_for_review")
        self.assertIn("R15", {risk["rule_id"] for risk in report["risks"]})
        self.assertEqual(report["plan"]["days"], [])
