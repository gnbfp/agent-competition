"""Reference calculations and incomplete-data tests for the P3 training load."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from src.p3_metrics.compute import compute_load, trimp


ROOT = Path(__file__).resolve().parents[1]
WINDOW_START = date(2026, 10, 18)
WINDOW_END = date(2026, 11, 14)


def session(offset: int, *, duration_s: int = 1800, avg_hr: int = 120, serial: int = 1) -> dict:
    day = WINDOW_START + timedelta(days=offset)
    return {"activity_id": f"A{day:%Y%m%d}-{serial:02d}", "date": day.isoformat(),
            "duration_s": duration_s, "avg_hr": avg_hr}


def load(activities: list[dict], history_start: date | None = WINDOW_START) -> dict:
    return compute_load({"schema_version": "1.0", "athlete_id": "anon_01", "activities": activities},
                        as_of=WINDOW_END, history_start=history_start,
                        resting_hr=60, max_hr=180, profile="male")


class TrainingLoadTest(unittest.TestCase):
    def test_r04_matches_three_reference_calculations(self) -> None:
        # The first two use half of the HR reserve. The last uses three quarters.
        cases = [(3600, 120, "male", 50.14457229), (3600, 120, "female", 59.46420245),
                 (1800, 150, "male", 60.77801976)]
        for duration, hr, profile, expected in cases:
            with self.subTest(duration=duration, hr=hr, profile=profile):
                result = trimp(duration, hr, resting_hr=60, max_hr=180, profile=profile)
                self.assertAlmostEqual(result, expected, places=7)

    def test_step_up_matches_both_reference_ratios_and_week_change(self) -> None:
        # One equal session per day for 21 days; double that load for the next seven.
        activities = [session(day) for day in range(28)]
        activities.extend(session(day, serial=2) for day in range(21, 28))
        activities.append(session(28, duration_s=7200))  # excluded by the cutoff
        output = load(activities)
        result = output["load"]
        self.assertEqual(output["window"], {"start": "2026-10-18", "end": "2026-11-14", "days": 28})
        self.assertEqual(len(output["activity_trimp"]), 35)
        self.assertAlmostEqual(result["trimp_daily"][-1]["trimp"], 50.144572, places=6)
        self.assertAlmostEqual(result["trimp_week"], 351.012006, places=6)
        self.assertEqual(result["week_load_change_pct"], 100)
        self.assertAlmostEqual(result["acwr_rolling"], 1.6, places=6)
        # Closed form for a step from 1 to 2 with seven updates at each alpha.
        expected = (2 - 0.75**7) / (2 - (27 / 29)**7)
        self.assertAlmostEqual(result["acwr_ewma"], expected, places=6)
        self.assertEqual(result["acwr_status"], "high")

    def test_missing_history_keeps_unknown_days_and_ratios_null(self) -> None:
        output = load([session(27)], history_start=None)
        result = output["load"]
        self.assertIsNone(result["trimp_daily"][0]["trimp"])
        self.assertGreater(result["trimp_daily"][-1]["trimp"], 0)
        self.assertIsNone(result["trimp_week"])
        self.assertIsNone(result["acwr_rolling"])
        self.assertIsNone(result["acwr_ewma"])
        self.assertIn("ACWR_INSUFFICIENT_HISTORY", {item["code"] for item in output["flags"]})

    def test_invalid_session_marks_whole_day_incomplete(self) -> None:
        output = load([session(27), session(27, avg_hr=200, serial=2)])
        self.assertGreater(output["activity_trimp"][0]["trimp"], 0)
        self.assertIsNone(output["activity_trimp"][1]["trimp"])
        self.assertIsNone(output["load"]["trimp_daily"][-1]["trimp"])
        self.assertIsNone(output["load"]["acwr_status"])
        self.assertIn("TRIMP_INCOMPLETE_DAYS", {item["code"] for item in output["flags"]})

    def test_confirmed_rest_can_be_zero_but_zero_baseline_has_no_ratio(self) -> None:
        output = load([])
        result = output["load"]
        self.assertEqual(result["trimp_week"], 0)
        self.assertEqual([row["trimp"] for row in result["trimp_daily"]], [0] * 28)
        for key in ("acwr_rolling", "acwr_ewma", "acwr_status", "week_load_change_pct"):
            self.assertIsNone(result[key])
        self.assertIn("ACWR_ZERO_BASELINE", {item["code"] for item in output["flags"]})

    def test_method_gap_keeps_both_ratios_and_withholds_status(self) -> None:
        # One session six days before the cutoff yields a rolling ratio of four.
        output = load([session(21)])
        result = output["load"]
        self.assertEqual(result["acwr_rolling"], 4)
        self.assertAlmostEqual(result["acwr_ewma"], 0.99056047, places=6)
        self.assertIsNone(result["acwr_status"])
        self.assertIn("ACWR_METHOD_GAP", {item["code"] for item in output["flags"]})

    def test_cli_reads_existing_activity_sample_and_records_formula_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "load_metrics.json"
            completed = subprocess.run(
                [sys.executable, "-B", "src/p3_metrics/compute.py", "contracts/samples/activity_sample.json",
                 "--as-of", "2026-11-14", "--history-start", "2026-11-08",
                 "--trimp-profile", "female", "--resting-hr", "52", "--max-hr", "190", "--load-only",
                 "-o", str(destination)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            output = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(output["load_inputs"]["coefficient_a"], 0.86)
        self.assertEqual(output["load_inputs"]["coefficient_b"], 1.67)
        self.assertEqual(output["load_inputs"]["resting_hr"], 52)
        self.assertEqual(output["load_inputs"]["max_hr"], 190)
        self.assertGreater(output["load"]["trimp_week"], 0)
        self.assertIsNone(output["load"]["acwr_rolling"])
