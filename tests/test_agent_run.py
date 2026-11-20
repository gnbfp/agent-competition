"""Follow-up transitions, evidence retries, and local agent CLI tests."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from contracts.validate_contract import check, load_json
from src.p3_metrics.compute import compute_metrics
from src.p4_agent.evidence import load_rules, retrieve_evidence
from src.p4_agent.run import run_agent


ROOT = Path(__file__).resolve().parents[1]
ACTIVITIES = ROOT / "contracts/samples/activity_sample.json"
ANSWERS = ROOT / "data/sample/agent_answers_sample.json"


class AgentRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.activities = load_json(ACTIVITIES)
        self.metrics = compute_metrics(
            self.activities, as_of=date(2026, 11, 16), history_start=date(2026, 11, 8),
            resting_hr=55, max_hr=183, profile="female",
        )

    def test_questions_and_phases_are_visible_without_answers(self) -> None:
        result = run_agent(self.metrics)
        self.assertEqual(result["status"], "awaiting_input")
        self.assertEqual([item["phase"] for item in result["phases"]], ["Plan", "Act", "Observe", "Self-check"])
        self.assertEqual([question["key"] for question in result["questions"]],
                         ["pain_reported", "max_hr_source", "sleep_h.2026-11-15", "sleep_h.2026-11-16"])
        self.assertEqual(result["answer_count"], 0)
        self.assertTrue(result["self_check"]["passed"])

    def test_real_answers_recheck_only_missing_observations(self) -> None:
        result = run_agent(self.metrics, answerer=lambda _: load_json(ANSWERS)["answers"])
        self.assertEqual(result["status"], "assessment_ready")
        self.assertEqual(result["questions"], [])
        self.assertEqual(result["answer_count"], 4)
        changes = {item["rule_id"]: (item["before"], item["after"]) for item in result["changed_checks"]}
        self.assertEqual(changes["R15"], ("insufficient_data", "not_triggered"))
        self.assertEqual(changes["R16"], ("insufficient_data", "triggered"))
        self.assertEqual(changes["R03"], ("insufficient_data", "not_triggered"))
        check16 = next(item for item in result["checks"] if item["rule_id"] == "R16")
        self.assertEqual(set(check16["observed"]["supplemented_dates"]), {"2026-11-15", "2026-11-16"})
        self.assertEqual([item["tool"] for item in result["agent_trace"]].count("check_risk"), 2)
        trace_schema = load_json(ROOT / "contracts/report.schema.json")["properties"]["agent_trace"]
        self.assertEqual(check(result["agent_trace"], trace_schema), [])

    def test_positive_pain_answer_and_prior_pain_remain_gated(self) -> None:
        answered = run_agent(self.metrics, answerer=lambda _: {"pain_reported": True})
        self.assertEqual(answered["planning_gate"], {"status": "hold_for_review", "rule_ids": ["R15"]})
        previous = run_agent(self.metrics, activities=self.activities,
                             context={"athlete_id": "ATH-001", "pain_reported": False})
        self.assertEqual(previous["status"], "hold_for_review")
        self.assertNotIn(self.activities["activities"][-1]["pain"], json.dumps(previous, ensure_ascii=False))

    def test_preexisting_device_sleep_cannot_be_overwritten_by_reply(self) -> None:
        result = run_agent(self.metrics, context={"athlete_id": "ATH-001",
                                                  "sleep_readings": {"2026-11-16": 8}})
        self.assertNotIn("sleep_h.2026-11-16", {q["key"] for q in result["questions"]})
        with self.assertRaisesRegex(ValueError, "本轮追问"):
            run_agent(self.metrics, context={"athlete_id": "ATH-001", "sleep_readings": {"2026-11-16": 8}},
                      answerer=lambda _: {"sleep_h.2026-11-16": 5})

    def test_synonym_lookup_retries_and_missing_evidence_blocks_handoff(self) -> None:
        rules = load_rules()
        found = retrieve_evidence("膝痛", rules)
        self.assertEqual(found["rule_id"], "R15")
        self.assertEqual([item["status"] for item in found["attempts"]], ["miss", "found"])
        unknown = retrieve_evidence("未登记的词", rules)
        self.assertIsNone(unknown["evidence"])
        self.assertEqual([item["status"] for item in unknown["attempts"]], ["miss", "miss"])
        rules["R15"]["source"] = ""
        result = run_agent(self.metrics, answerer=lambda _: {"pain_reported": True}, rules=rules)
        self.assertEqual(result["status"], "hold_for_review")
        self.assertFalse(result["self_check"]["passed"])
        self.assertIn("R15", result["self_check"]["missing_evidence_rule_ids"])
        self.assertNotIn("R15", {item["rule_id"] for item in result["risks"]})
        self.assertIn("failed", {item["status"] for item in result["agent_trace"]
                                 if item["tool"] == "retrieve_evidence"})

    def test_cli_file_and_interactive_runs_produce_same_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metric_path = root / "metrics.json"
            metric_path.write_text(json.dumps(self.metrics), encoding="utf-8")
            json_path, interactive_path = root / "file.json", root / "interactive.json"
            arguments = [sys.executable, "-B", str(ROOT / "src/p4_agent/run.py"), str(metric_path),
                         "--evidence-query", "膝痛"]
            for path, mode, stdin in ((json_path, ["--answers", str(ANSWERS)], None),
                                      (interactive_path, ["--interactive"], "否\nmeasured\n5.5\n5.0\n")):
                result = subprocess.run([*arguments, *mode, "-o", str(path)], input=stdin, cwd=root,
                                        capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Self-check", result.stdout)
            self.assertEqual(json_path.read_bytes(), interactive_path.read_bytes())
            self.assertEqual(load_json(json_path)["evidence_lookup"]["rule_id"], "R15")
