"""Coverage and safety checks for the project risk checks and evidence tool."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from contracts.validate_contract import check, load_json
from src.p4_agent.evidence import load_rules, lookup_evidence
from src.p4_agent.risk_rules import evaluate_rules


ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "contracts/samples/metrics_v2_sample.json"
ACTIVITIES = ROOT / "contracts/samples/activity_sample.json"
CONTEXT = ROOT / "data/sample/risk_context_sample.json"
END = date(2026, 11, 14)


def index(result):
    return {item["rule_id"]: item for item in result["checks"]}


def activity(days_ago: int, distance: int, *, hr: int = 150, pace: int = 360) -> dict:
    day = END - timedelta(days=days_ago)
    return {"activity_id": f"A{day:%Y%m%d}-01", "date": day.isoformat(), "sport": "run",
            "duration_s": int(distance / 1000 * pace), "distance_m": distance, "avg_hr": hr,
            "max_hr": 170, "avg_pace_s_per_km": pace}


class RiskRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.metrics = load_json(METRICS)
        self.activities = load_json(ACTIVITIES)
        self.context = load_json(CONTEXT)

    def evaluate(self, *, activities=None, context=None):
        return evaluate_rules(self.metrics, activities=activities, context=context)

    def test_missing_inputs_produce_eighteen_checks_with_traceable_evidence(self) -> None:
        result = self.evaluate()
        checks = index(result)
        self.assertEqual(list(checks), [f"R{i:02d}" for i in range(1, 19)])
        for rule_id in ("R01", "R03", "R05", "R06", "R07", "R08", "R09", "R14", "R15", "R17", "R18"):
            self.assertEqual(checks[rule_id]["status"], "insufficient_data")
            self.assertTrue(checks[rule_id]["missing_data"])
        self.assertEqual(checks["R04"]["status"], "not_applicable")
        self.assertEqual(result["planning_gate"]["status"], "needs_confirmation")
        rules = load_rules()
        for rule_id, item in checks.items():
            self.assertEqual(item["evidence"]["source"], rules[rule_id]["source"])
            self.assertEqual(item["evidence"]["clause"], rules[rule_id]["clause"])
        self.assertEqual(lookup_evidence("  r15 ", rules)["clause"], rules["R15"]["clause"])
        self.assertIsNone(lookup_evidence("R99", rules))

    def test_pain_on_record_requires_review_even_if_current_answer_is_no(self) -> None:
        self.context["pain_reported"] = False
        result = self.evaluate(activities=self.activities, context=self.context)
        checks = index(result)
        self.assertEqual(checks["R15"]["status"], "triggered")
        self.assertEqual(checks["R18"]["observed"]["days_to_race"], 7)
        self.assertIn("R15", result["planning_gate"]["rule_ids"])
        self.assertEqual(result["planning_gate"]["status"], "hold_for_review")
        pain_text = self.activities["activities"][-1]["pain"]
        self.assertNotIn(pain_text, json.dumps(result, ensure_ascii=False))
        report = load_json(ROOT / "contracts/report.schema.json")
        self.assertEqual(check(result["risks"], report["properties"]["risks"]), [])

    def test_acwr_uses_ewma_and_defers_a_method_gap(self) -> None:
        self.metrics["load"].update(acwr_ewma=1.25, acwr_rolling=1.95, acwr_status="optimal")
        checks = index(self.evaluate())
        self.assertEqual((checks["R05"]["status"], checks["R06"]["status"]), ("triggered", "not_triggered"))
        self.metrics["load"].update(acwr_ewma=0.75, acwr_rolling=1.65, acwr_status="undertrained")
        self.assertEqual(index(self.evaluate())["R07"]["status"], "triggered")
        self.metrics["load"].update(acwr_ewma=1.55, acwr_rolling=1.35, acwr_status="danger")
        self.assertEqual(index(self.evaluate())["R06"]["status"], "triggered")
        self.metrics["load"].update(acwr_rolling=2.9, acwr_status=None)
        self.assertEqual(index(self.evaluate())["R06"]["status"], "insufficient_data")

    def test_r08_uses_distance_over_four_prior_weeks_and_r14_matches_pace(self) -> None:
        self.metrics["load_inputs"]["history_start"] = "2026-10-11"
        self.metrics["load"]["week_load_change_pct"] = -20  # R08 uses distance, not TRIMP.
        self.activities["activities"] = [
            activity(0, 12000, hr=160, pace=360), activity(1, 8000, hr=145),
            *(activity(offset, 10000, hr=150, pace=365) for offset in (7, 14, 21, 28)),
        ]
        checks = index(self.evaluate(activities=self.activities, context=self.context))
        self.assertEqual(checks["R08"]["observed"]["previous_4_week_mean_m"], 10000)
        self.assertEqual(checks["R08"]["observed"]["increase_pct"], 100)
        for rule_id in ("R08", "R10", "R14"):
            self.assertEqual(checks[rule_id]["status"], "triggered")
        self.assertEqual(checks["R14"]["observed"]["delta_bpm"], 10)
        self.metrics["load_inputs"]["history_start"] = "2026-10-12"
        self.assertEqual(index(self.evaluate(activities=self.activities))["R08"]["status"], "insufficient_data")

    def test_data_flags_use_confirmed_import_counts_and_max_hr_source(self) -> None:
        self.context["max_hr_source"] = "estimated_220_age"
        self.context["import_quality"] = {"incomplete_rows": 1, "device_anomaly_rows": 1}
        checks = index(self.evaluate(activities=self.activities, context=self.context))
        for rule_id in ("R01", "R02", "R03"):
            self.assertEqual(checks[rule_id]["status"], "triggered")
        self.assertEqual(checks["R10"]["status"], "insufficient_data")

    def test_consecutive_days_and_percent_thresholds(self) -> None:
        readings = self.metrics["recovery"]["daily"]
        self.metrics["recovery"]["resting_hr_baseline"] = 50
        for entry in readings[-3:]:
            entry.update(resting_hr_bpm=58, sleep_h=5.5)
        self.metrics["recovery"]["hr_drift_pct"] = 5
        self.metrics["capacity"]["max_spread_pct"] = 5.1
        for day in ("2026-11-12", "2026-11-13", "2026-11-14"):
            self.context["session_types"][day] = ["tempo"]
        checks = index(self.evaluate(context=self.context))
        for rule_id in ("R09", "R11", "R13", "R16"):
            self.assertEqual(checks[rule_id]["status"], "triggered")
        self.assertEqual(checks["R12"]["status"], "not_triggered")
        readings[-2]["resting_hr_bpm"] = None
        readings[-2]["sleep_h"] = None
        self.metrics["recovery"]["hr_drift_pct"] = 5.01
        self.context["session_types"].pop("2026-11-13")
        checks = index(self.evaluate(context=self.context))
        for rule_id in ("R09", "R11", "R16"):
            self.assertEqual(checks[rule_id]["status"], "insufficient_data")
        self.assertEqual(checks["R12"]["status"], "triggered")

    def test_weather_with_partial_input_and_past_race(self) -> None:
        self.context.update(environment={"temperature_c": 29}, target_race_date="2026-11-13",
                            pain_reported=False)
        result = self.evaluate(context=self.context)
        self.assertEqual(index(result)["R17"]["status"], "insufficient_data")
        self.assertEqual(index(result)["R18"]["status"], "not_triggered")
        self.assertEqual(result["planning_gate"]["status"], "no_hold_signal")
        self.context["environment"]["temperature_c"] = 31
        self.assertEqual(index(self.evaluate(context=self.context))["R17"]["status"], "triggered")

    def test_cli_evaluates_v2_sample_and_looks_up_rule(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "risk_checks.json"
            run = subprocess.run(
                [sys.executable, "-B", "-m", "src.p4_agent.risk_rules", "evaluate", str(METRICS),
                 "--activities", str(ACTIVITIES), "--context", str(CONTEXT), "-o", str(output)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(load_json(output)["planning_gate"]["rule_ids"], ["R15", "R18"])
        run = subprocess.run(
            [sys.executable, "-B", "-m", "src.p4_agent.risk_rules", "evidence", "R15"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(json.loads(run.stdout), lookup_evidence("R15", load_rules()))

    def test_direct_script_supports_evaluation_outside_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "risk_checks.json"
            run = subprocess.run(
                [sys.executable, "-B", str(ROOT / "src/p4_agent/risk_rules.py"),
                 "evaluate", str(METRICS), "-o", str(output)],
                cwd=tmp, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(len(load_json(output)["checks"]), 18)
