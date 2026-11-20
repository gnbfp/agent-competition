"""Exercise the weekly draft, both self-checks, and report compatibility."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from contracts.validate_contract import load_json, validate_document, validate_file
from src.p3_metrics.compute import compute_metrics
from src.p4_agent.evidence import load_rules
from src.p4_agent.planner import generate_plan, next_week, rest_day
from src.p4_agent.report import build_report
from src.p4_agent.run import run_agent

ROOT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 11, 14)
START = AS_OF - timedelta(days=27)


def demo_inputs():
    sessions, types = [], {}
    for offset in range(28):
        day = (START + timedelta(days=offset)).isoformat()
        if offset % 7 in (1, 3, 5):
            types[day] = ["easy"]
            sessions.append({"activity_id": day, "date": day, "sport": "run", "duration_s": 1800,
                             "distance_m": 5000, "avg_hr": 130, "max_hr": 160, "avg_pace_s_per_km": 360})
        else:
            types[day] = []
    activities = {"schema_version": "1.0", "athlete_id": "anon_01", "timezone": "Asia/Shanghai",
                  "activities": sessions}
    readings = {"athlete_id": "anon_01", "daily": [
        {"date": (AS_OF - timedelta(days=offset)).isoformat(), "resting_hr_bpm": 55, "sleep_h": 7}
        for offset in range(9)
    ]}
    metrics = compute_metrics(activities, as_of=AS_OF, history_start=START, resting_hr=55,
                              max_hr=183, profile="female", measurements=readings)
    context = {"athlete_id": "anon_01", "pain_reported": False, "max_hr_source": "measured",
               "import_quality": {"incomplete_rows": 0, "device_anomaly_rows": 0}, "session_types": types}
    return activities, metrics, context


def failing_candidate():
    week = next_week(AS_OF)
    days = [rest_day(day) for day in week]
    days[0] = {"date": week[0], "kind": "easy", "duration_s": 7200, "distance_m": 20000,
               "reference_avg_hr_bpm": 150, "rules": ["R04"]}
    days[2] = {"date": week[2], "kind": "easy", "duration_s": 1800, "distance_m": 5000,
               "reference_avg_hr_bpm": 130, "rules": ["R99"]}
    return {"athlete_id": "anon_01", "days": days}


class PlanReportTest(unittest.TestCase):
    def setUp(self):
        self.activities, self.metrics, self.context = demo_inputs()
        self.rules = load_rules()

    def build(self, candidate=None):
        assessment = run_agent(self.metrics, activities=self.activities, context=self.context, rules=self.rules)
        plan = generate_plan(self.metrics, assessment, self.rules, activities=self.activities,
                             context=self.context, candidate=candidate)
        report = build_report(self.metrics, assessment, plan, self.rules, generated_at="2026-11-15T09:00:00+08:00")
        self.assertEqual(validate_document("plan.json", plan), [])
        self.assertEqual(validate_document("report.json", report), [])
        return plan, report

    def test_default_draft_reuses_confirmed_easy_runs_without_adding_pace_targets(self):
        plan, report = self.build()
        self.assertEqual(plan["status"], "draft")
        self.assertEqual(plan["week_start"], "2026-11-16")
        self.assertEqual(plan["weekly_targets"]["sessions"], 3)
        self.assertAlmostEqual(plan["weekly_targets"]["load_target_trimp"], plan["baseline_trimp"], places=5)
        self.assertTrue(all(day["target_pace_s_per_km"] is None for day in plan["days"]))
        self.assertEqual(report["summary"]["plan_status"], "draft")

    def test_bad_candidate_is_rechecked_and_only_repaired_days_are_published(self):
        plan, report = self.build(failing_candidate())
        self.assertEqual(plan["status"], "draft")
        self.assertEqual(len(plan["attempts"]), 2)
        self.assertEqual([check["passed"] for check in plan["attempts"][0]["checks"]], [False, False])
        self.assertEqual([check["passed"] for check in plan["attempts"][1]["checks"]], [True, True])
        self.assertEqual(plan["days"][2]["kind"], "rest")
        self.assertLess(plan["days"][0]["duration_s"], 7200)
        self.assertLessEqual(plan["weekly_targets"]["load_target_trimp"], plan["baseline_trimp"])
        self.assertNotIn("R99", {item["rule_id"] for item in report["evidence"]})
        self.assertEqual([item["status"] for item in report["agent_trace"] if item["tool"] == "generate_plan"],
                         ["retry", "ok"])

    def test_pain_holds_plan_even_with_a_candidate(self):
        self.context["pain_reported"] = True
        plan, report = self.build(failing_candidate())
        self.assertEqual(plan["status"], "hold_for_review")
        self.assertEqual(plan["days"], [])
        self.assertIsNone(plan["weekly_targets"])
        self.assertIn("R15", {item["rule_id"] for item in report["evidence"]})
        self.assertFalse(plan["self_check"]["passed"])

    def test_missing_resting_hr_observation_withholds_draft(self):
        self.metrics["recovery"]["daily"][-1]["resting_hr_bpm"] = None
        self.metrics["recovery"]["resting_hr_delta"] = None
        plan, _ = self.build()
        self.assertEqual(plan["status"], "awaiting_input")
        self.assertEqual(plan["attempts"], [])

    def test_validation_rejects_missing_report_ref_and_forged_weekly_total(self):
        plan, report = self.build()
        report["evidence"] = [item for item in report["evidence"] if item["rule_id"] != "R04"]
        self.assertTrue(any("$.evidence" in err for err in validate_document("report.json", report)))
        plan["weekly_targets"]["load_target_trimp"] += 20
        self.assertTrue(any("$.weekly_targets" in err for err in validate_document("plan.json", plan)))

    def test_nested_versioned_schema_copies_remain_identical(self):
        report = load_json(ROOT / "contracts/report.v2.schema.json")["properties"]
        for name in ("plan", "metrics"):
            standalone = load_json(ROOT / f"contracts/{name}.v2.schema.json")
            standalone.pop("$schema")
            self.assertEqual(report[name], standalone)

    def test_cli_writes_both_new_files_and_legacy_examples_still_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {"activity.json": self.activities, "metrics.json": self.metrics, "context.json": self.context,
                     "candidate.json": failing_candidate()}
            for name, data in files.items():
                (root / name).write_text(json.dumps(data), encoding="utf-8")
            out = root / "result"
            result = subprocess.run(
                [sys.executable, "-B", str(ROOT / "src/p4_agent/report.py"), str(root / "metrics.json"),
                 "--activities", str(root / "activity.json"), "--context", str(root / "context.json"),
                 "--candidate", str(root / "candidate.json"), "-o", str(out)],
                cwd=root, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("第 1 轮 打回", result.stdout)
            self.assertIn("第 2 轮 通过", result.stdout)
            for name in ("plan", "report"):
                self.assertEqual(validate_file(out / f"{name}.json"), [])
                self.assertEqual(validate_file(ROOT / f"contracts/samples/{name}_sample.json"), [])
