#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P2 解析器的单元测试（只依赖标准库 unittest，不需要 pytest）。

跑法（在仓库根目录）：
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src" / "p2_ingest"))

import csv_parser  # noqa: E402

SAMPLE = ROOT / "data" / "sample" / "activities_sample.csv"
SCRATCH_ROOT = ROOT / "out" / "_test_tmp"


@contextlib.contextmanager
def scratch():
    """仓库内的临时目录（沙箱不允许写系统 TEMP 的 ACL 时会报 WinError 5）。"""
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    path = pathlib.Path(tempfile_dir())
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def tempfile_dir() -> str:
    import uuid
    return str(SCRATCH_ROOT / uuid.uuid4().hex)
HEADER = (
    "date,start_time,sport,duration_s,distance_m,avg_hr,max_hr,"
    "elevation_gain_m,rpe,sleep_h,pain,source"
)


class ParseSampleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = csv_parser.load_csv(SAMPLE)
        self.activities, self.skipped, self.rejected, self.warnings = csv_parser.parse_rows(self.rows)

    def test_counts(self) -> None:
        """样例 4 行：2 条入库、1 条丢弃、1 条设备异常旁路。"""
        self.assertEqual(len(self.rows), 4)
        self.assertEqual(len(self.activities), 2)
        self.assertEqual(len(self.skipped), 1)
        self.assertEqual(len(self.rejected), 1)

    def test_skip_reason(self) -> None:
        line_no, reason = self.skipped[0]
        self.assertEqual(line_no, 5)
        self.assertIn("duration_s", reason)

    def test_anomaly_routed_to_rejected(self) -> None:
        item = self.rejected[0]
        self.assertEqual(item["rule_id"], "R02")
        self.assertEqual(item["line"], 4)

    def test_chinese_sport_mapped(self) -> None:
        sports = {a["sport"] for a in self.activities}
        self.assertIn("run", sports)

    def test_pace_computed(self) -> None:
        first = self.activities[0]
        self.assertEqual(first["date"], "2026-11-12")
        self.assertEqual(first["avg_pace_s_per_km"], 360)  # 2880s / 8000m = 6'00"

    def test_pain_kept_as_is(self) -> None:
        long_run = [a for a in self.activities if a["date"] == "2026-11-14"][0]
        self.assertIn("膝", long_run["pain"])

    def test_activity_id_format(self) -> None:
        for activity in self.activities:
            self.assertRegex(activity["activity_id"], r"^A\d{8}-\d{2}$")

    def test_document_shape(self) -> None:
        doc = csv_parser.build_document(self.activities, "anon_01")
        self.assertEqual(doc["schema_version"], "1.0")
        self.assertEqual(doc["timezone"], "Asia/Shanghai")
        self.assertIn("generated_at", doc)


class RobustnessTest(unittest.TestCase):
    def run_rows(self, body: str) -> tuple[list[dict], list[tuple[int, str]], list[dict], list[str]]:
        with scratch() as tmp:
            path = tmp / "case.csv"
            path.write_text(HEADER + "\n" + body, encoding="utf-8", newline="\n")
            rows = csv_parser.load_csv(path)
        return csv_parser.parse_rows(rows)

    def test_bom_tolerated(self) -> None:
        """Excel 另存的 CSV 带 BOM，表头不能被读成 \\ufeffdate。"""
        body = "2026-11-12,,run,1800,5000,150,170,,5,,,csv\n"
        with scratch() as tmp:
            path = tmp / "bom.csv"
            path.write_text("\ufeff" + HEADER + "\n" + body, encoding="utf-8", newline="\n")
            rows = csv_parser.load_csv(path)
        activities, skipped, rejected, _ = csv_parser.parse_rows(rows)
        self.assertEqual(len(activities), 1)
        self.assertEqual(skipped, [])
        self.assertEqual(rejected, [])

    def test_decimal_seconds_and_numbers(self) -> None:
        body = "2026-11-12,,run,1800.0,5000.0,150,170,,5.5,,,garmin\n"
        activities, *_ = self.run_rows(body)
        self.assertEqual(activities[0]["duration_s"], 1800)
        self.assertEqual(activities[0]["rpe"], 6)

    def test_missing_hr_row_dropped(self) -> None:
        body = "2026-11-12,,run,1800,5000,,170,,5,,,garmin\n"
        activities, skipped, _, _ = self.run_rows(body)
        self.assertEqual(activities, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("avg_hr", skipped[0][1])

    def test_unknown_sport_dropped(self) -> None:
        body = "2026-11-12,,滑板,1800,5000,150,170,,5,,,garmin\n"
        activities, skipped, _, _ = self.run_rows(body)
        self.assertEqual(activities, [])
        self.assertIn("sport", skipped[0][1])

    def test_pain_empty_is_null(self) -> None:
        body = "2026-11-12,,run,1800,5000,150,170,,5,,,garmin\n"
        activities, *_ = self.run_rows(body)
        self.assertIsNone(activities[0]["pain"])
        self.assertIsNone(activities[0]["elevation_gain_m"])


class EndToEndTest(unittest.TestCase):
    def test_output_passes_contract_validator(self) -> None:
        """解析器产出的 JSON 必须通过 contracts/validate_contract.py。"""
        with scratch() as tmp:
            out = tmp / "activity.json"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "src" / "p2_ingest" / "csv_parser.py"),
                 str(SAMPLE), "-o", str(out)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(out.exists())

            validator = subprocess.run(
                [sys.executable, str(ROOT / "contracts" / "validate_contract.py"), str(out)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(validator.returncode, 0, validator.stdout + validator.stderr)

            document = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(document["activities"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
