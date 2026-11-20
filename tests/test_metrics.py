"""Reference values, missing measurements and v2 contract round trips."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from contracts.validate_contract import validate_file
from src.p3_metrics.compute import compute_metrics


ROOT = Path(__file__).resolve().parents[1]
ACTIVITY_SAMPLE = ROOT / "contracts" / "samples" / "activity_sample.json"
MEASUREMENTS_SAMPLE = ROOT / "data" / "sample" / "measurements_sample.json"
AS_OF = date(2026, 11, 14)


class MetricsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.activity = json.loads(ACTIVITY_SAMPLE.read_text(encoding="utf-8"))
        self.measurements = json.loads(MEASUREMENTS_SAMPLE.read_text(encoding="utf-8"))
        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def compute(self, measurements: dict | None, *, resting_hr: int = 55) -> dict:
        return compute_metrics(self.activity, as_of=AS_OF, history_start=date(2026, 11, 8),
                               resting_hr=resting_hr, max_hr=183, profile="female",
                               measurements=measurements)

    def validate(self, output: dict) -> list[str]:
        path = self.temp / "metrics.json"
        path.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
        return validate_file(path)

    def test_reference_estimates_and_recovery(self) -> None:
        output = self.compute(self.measurements)
        self.assertEqual(self.validate(output), [])
        values = {item["method"]: item["value"] for item in output["capacity"]["methods"]}
        # 183/55 * 15.3; VDOT at 5 km in 20 min; and at 10 km in 2501.917826 sec.
        self.assertEqual(values, {"uth_sorensen": 50.9073, "daniels": 49.8062, "riegel": 49.4792})
        self.assertEqual(output["capacity"]["estimate_range"], {"low": 49.4792, "high": 50.9073})
        self.assertTrue(output["capacity"]["consistency_ok"])
        self.assertEqual(output["capacity"]["vo2max"]["value"], 50.9073)
        result = output["recovery"]
        self.assertEqual(result["resting_hr_baseline"], 56)
        self.assertEqual(result["resting_hr_baseline_days"], 7)
        self.assertEqual(result["resting_hr_delta"], 2)
        self.assertEqual(result["hr_drift_pct"], 5)
        self.assertEqual(result["hrv_rmssd"], 48)
        self.assertEqual(result["sleep_days"], 3)
        self.assertEqual(result["sleep_h_avg"], 7)

    def test_r13_disagreement_hides_point_and_validator_rejects_one(self) -> None:
        output = self.compute(self.measurements, resting_hr=48)
        self.assertFalse(output["capacity"]["consistency_ok"])
        self.assertIsNone(output["capacity"]["vo2max"]["value"])
        self.assertIsNotNone(output["capacity"]["estimate_range"])
        self.assertEqual(self.validate(output), [])
        self.assertIn("VO2_METHOD_GAP", {item["code"] for item in output["flags"]})
        output["capacity"]["vo2max"].update(value=50, method="uth_sorensen")
        self.assertTrue(any("点估值" in error for error in self.validate(output)))

    def test_missing_measurements_stay_null_and_activity_sleep_is_used_once_per_day(self) -> None:
        activity = copy.deepcopy(self.activity["activities"][0])
        activity["activity_id"] += "-duplicate-sleep"
        self.activity["activities"].append(activity)
        output = self.compute(None)
        self.assertEqual(self.validate(output), [])
        self.assertIsNone(output["capacity"]["vo2max"]["value"])
        self.assertIsNone(output["capacity"]["consistency_ok"])
        self.assertIsNone(output["capacity"]["max_spread_pct"])
        self.assertIsNone(output["load"]["acwr_ewma"])
        for field in ("resting_hr_baseline", "resting_hr_delta", "hr_drift_pct", "hrv_rmssd"):
            self.assertIsNone(output["recovery"][field])
        self.assertEqual(output["recovery"]["sleep_days"], 2)
        self.assertEqual(output["recovery"]["sleep_h_avg"], 6.75)

    def test_do_not_use_a_future_race_or_nonsteady_splits(self) -> None:
        self.measurements["race"]["date"] = "2026-11-15"
        self.measurements["steady_run"]["second_pace_s_per_km"] = 400
        output = self.compute(self.measurements)
        self.assertIsNone(output["capacity"]["race_inputs"])
        self.assertIsNone(output["recovery"]["hr_drift_pct"])
        self.assertIsNotNone(output["recovery"]["hr_drift_inputs"])
        flags = {item["code"] for item in output["flags"]}
        self.assertIn("RACE_OUTSIDE_WINDOW", flags)
        self.assertIn("HR_DRIFT_PACE_MISMATCH", flags)

    def test_metrics_v2_preserves_acwr_gap_from_node04(self) -> None:
        self.activity["activities"] = [self.activity["activities"][0]]
        self.activity["activities"][0]["date"] = "2026-11-08"
        output = compute_metrics(self.activity, as_of=AS_OF, history_start=date(2026, 10, 18),
                                 resting_hr=55, max_hr=183, profile="female")
        self.assertEqual(output["load"]["acwr_rolling"], 4)
        self.assertIsNone(output["load"]["acwr_status"])
        self.assertEqual(self.validate(output), [])
        output["flags"] = [item for item in output["flags"] if item["code"] != "ACWR_METHOD_GAP"]
        self.assertTrue(any("ACWR_METHOD_GAP" in error for error in self.validate(output)))

    def test_other_athlete_measurements_are_rejected(self) -> None:
        self.measurements["athlete_id"] = "someone-else"
        with self.assertRaisesRegex(ValueError, "athlete_id"):
            self.compute(self.measurements)

    def test_cli_outputs_formal_metrics_and_keeps_v1_readable(self) -> None:
        output = self.temp / "metrics.json"
        result = subprocess.run(
            [sys.executable, "-B", "src/p3_metrics/compute.py", str(ACTIVITY_SAMPLE),
             "--as-of", AS_OF.isoformat(), "--history-start", "2026-11-08",
             "--trimp-profile", "female", "--resting-hr", "55", "--max-hr", "183",
             "--measurements", str(MEASUREMENTS_SAMPLE), "-o", str(output)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["schema_version"], "2.0")
        self.assertEqual(validate_file(output), [])
        self.assertEqual(validate_file(ROOT / "contracts/samples/metrics_sample.json"), [])
        self.assertEqual(validate_file(ROOT / "contracts/samples/report_sample.json"), [])
