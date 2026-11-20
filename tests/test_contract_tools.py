"""Regression tests for schema support and the versioned mock metrics route."""

import unittest
from unittest.mock import Mock

from contracts.mock_api import Handler
from contracts.validate_contract import check


class ContractToolTest(unittest.TestCase):
    def test_unknown_keywords_fail_even_when_property_is_absent(self) -> None:
        schema = {"type": "object", "properties": {
            "future": {"type": "array", "minItems": 1, "items": {"$ref": "#/definitions/future"}}
        }}
        errors = check({}, schema)
        self.assertTrue(any("minItems" in error and "future" in error for error in errors))
        self.assertTrue(any("$ref" in error and "future" in error for error in errors))

    def test_mock_metrics_supports_both_versions(self) -> None:
        for route, version in (("/api/metrics", "1.0"), ("/api/metrics?version=2.0", "2.0")):
            with self.subTest(route=route):
                handler = Mock(path=route)
                Handler.do_GET(handler)
                handler._send.assert_called_once()
                self.assertEqual(handler._send.call_args.args[0]["schema_version"], version)
        handler = Mock(path="/api/metrics?version=99.0")
        Handler.do_GET(handler)
        self.assertEqual(handler._send.call_args.kwargs["status"], 400)
