"""Cover the external model request and safe handling of bad provider responses."""

import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from contracts.validate_contract import load_json
from src.ai_analysis import AnalysisError, NoRedirect, analyze_report, connection_options


ROOT = Path(__file__).resolve().parents[1]
CONFIG = {"base_url": "https://api.openai.com/v1", "model": "test-model", "api_key": "test-only-secret"}


class AiAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.report = load_json(ROOT / "contracts/samples/report_v2_sample.json")

    @patch("src.ai_analysis.build_opener")
    def test_posts_summary_with_bearer_header_and_no_redirects(self, build):
        self.report["athlete_id"] = "PRIVATE-ATHLETE-ID"
        self.report["metrics"]["load"]["trimp_daily"][0]["date"] = "PRIVATE-SESSION-DATE"
        self.report["summary"]["headline"] = "PRIVATE-FREE-TEXT"
        open_request = build.return_value.open
        open_request.return_value = io.BytesIO(json.dumps({
            "choices": [{"message": {"content": "R05 根据摘要解释负荷。"}}],
        }).encode("utf-8"))
        self.assertIn("R05", analyze_report(self.report, CONFIG))
        self.assertIsInstance(build.call_args.args[0], NoRedirect)
        self.assertIsNone(build.call_args.args[0].redirect_request(None, None, 307, "", None, None))
        req = open_request.call_args.args[0]
        self.assertEqual(req.full_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer test-only-secret")
        body = json.loads(req.data)
        self.assertEqual(body["model"], "test-model")
        self.assertIn("max_completion_tokens", body)
        self.assertNotIn("test-only-secret", str(body))
        self.assertNotIn("PRIVATE-", str(body))
        summary = json.loads(body["messages"][1]["content"])
        self.assertEqual(summary["plan_status"], "draft")
        self.assertEqual(summary["load"]["trimp_week"], self.report["metrics"]["load"]["trimp_week"])
        self.assertEqual(summary["risk_signals"][0]["rule_id"], "R05")

    @patch("src.ai_analysis.build_opener")
    def test_provider_error_and_secret_are_not_echoed(self, build):
        provider_open = build.return_value.open
        provider_open.side_effect = HTTPError("https://api.openai.com/v1/chat/completions", 401,
                                              "test-only-secret", {}, io.BytesIO(b"test-only-secret"))
        with self.assertRaises(AnalysisError) as caught:
            analyze_report(self.report, CONFIG)
        self.assertEqual(caught.exception.status, 401)
        self.assertNotIn("test-only-secret", str(caught.exception))

    def test_custom_endpoint_validation(self):
        endpoint, _, _ = connection_options({**CONFIG, "base_url": "https://example.com/compatible/v1/"})
        self.assertEqual(endpoint, "https://example.com/compatible/v1/chat/completions")
        for base in ("http://example.com/v1", "https://name:pass@example.com/v1", "https://example.com/?key=1"):
            with self.subTest(base=base), self.assertRaises(AnalysisError):
                connection_options({**CONFIG, "base_url": base})
