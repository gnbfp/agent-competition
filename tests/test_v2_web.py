"""Regression checks for new RunWise AI V2 local-only actions."""
from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from contracts.validate_contract import validate_document
from src.pipeline import browser_run
from src.report_server import make_report_server


class V2WebTest(unittest.TestCase):
    def test_history_replan_and_missing_demo(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "out"
            original = browser_run({"mode": "demo"}, output) / "report.json"
            server = make_report_server(original, 0, on_run=lambda payload: browser_run(payload, output))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            address = f"http://127.0.0.1:{server.server_port}"

            def call(path, payload=None):
                data = None if payload is None else json.dumps(payload).encode()
                headers = {"Host": f"127.0.0.1:{server.server_port}"}
                if data is not None:
                    headers.update({"Origin": address, "Content-Type": "application/json"})
                req = Request(address + path, data=data, headers=headers,
                              method="POST" if data is not None else "GET")
                try:
                    with urlopen(req, timeout=30) as response:
                        return response.status, json.loads(response.read())
                except HTTPError as exc:
                    return exc.code, json.loads(exc.read())

            try:
                status, snapshot = call("/api/snapshot")
                self.assertEqual(status, 200)
                self.assertEqual(snapshot["report"]["plan"]["status"], "draft")
                old_days = snapshot["report"]["plan"]["days"]
                date1, date2 = old_days[1]["date"], old_days[2]["date"]

                status, result = call("/api/replan", {"report_id": snapshot["report_id"],
                                                        "first_date": date1, "second_date": date2})
                self.assertEqual(status, 200, result)
                self.assertEqual(result["report"]["plan"]["days"][1]["kind"], old_days[2]["kind"])
                self.assertEqual(result["report"]["plan"]["days"][2]["kind"], old_days[1]["kind"])
                self.assertTrue(result["report"]["plan"]["self_check"]["passed"])
                self.assertEqual(validate_document(Path("report.json"), result["report"]), [])
                self.assertEqual(validate_document(Path("plan.json"), result["report"]["plan"]), [])

                status, stale = call("/api/replan", {"report_id": snapshot["report_id"],
                                                       "first_date": date1, "second_date": date2})
                self.assertEqual(status, 409, stale)
                self.assertEqual(stale["error"], "stale_report")
                status, invalid_question = call("/api/ask", {"report_id": result["report_id"],
                                       "api_key": "demo-key", "base_url": "https://api.openai.com/v1",
                                       "model": "gpt-5-mini", "question": ""})
                self.assertEqual(status, 400, invalid_question)
                self.assertEqual(invalid_question["error"], "ai_failed")
                status, history = call("/api/history")
                self.assertEqual(status, 200)
                self.assertGreaterEqual(len(history["reports"]), 2)
                history_id = history["reports"][0]["id"]
                status, historical = call("/api/history/" + history_id)
                self.assertEqual(status, 200)
                self.assertEqual(historical["report"]["schema_version"], "2.0")
                status, missing = call("/api/run", {"mode": "missing"})
                self.assertEqual(status, 200, missing)
                self.assertEqual(missing["report"]["plan"]["status"], "awaiting_input")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
