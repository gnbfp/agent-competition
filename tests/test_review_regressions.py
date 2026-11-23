"""Regressions from the first-use review of the V3.5 delivery."""
import unittest
from datetime import date
from src.p3_metrics.running_summary import compute_running_summary
from src.p4_agent.planner import draft_from_history, next_week


class FirstUseReviewTests(unittest.TestCase):
    def test_previous_week_unknown_and_confirmed_zero(self):
        end = date(2026, 11, 14)
        empty = {"activities": []}
        self.assertIsNone(compute_running_summary(empty, end)["week"]["previous_distance_km"])
        covered = compute_running_summary(empty, end, date(2026, 11, 1))
        self.assertEqual(covered["week"]["previous_distance_km"], 0)
        self.assertTrue(covered["week"]["previous_coverage_confirmed"])

    def test_only_identified_easy_activity_matches_target_weekday(self):
        end = date(2026, 11, 14)
        def activity(day):
            return {"date": day, "sport": "run", "distance_m": 5000, "duration_s": 1800, "avg_hr": 135}
        activities = {"activities": [activity(day) for day in ("2026-11-09", "2026-11-11", "2026-11-13")]}
        context = {"session_types": {"2026-11-09": ["interval"], "2026-11-11": ["easy"]}}
        days = draft_from_history(next_week(end), end, activities, context)
        self.assertEqual([d["date"] for d in days if d["kind"] == "easy"], ["2026-11-18"])
