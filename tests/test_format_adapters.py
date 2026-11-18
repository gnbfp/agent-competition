#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P2 导入适配器的单元测试（只依赖标准库 unittest）。

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
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src" / "p2_ingest"))

import csv_parser  # noqa: E402
import format_adapters as fa  # noqa: E402
import import_export  # noqa: E402

GARMIN_SAMPLE = ROOT / "data" / "sample" / "garmin_export_sample.csv"
HUAWEI_SAMPLE = ROOT / "data" / "sample" / "huawei_export_sample.csv"
SCRATCH_ROOT = ROOT / "out" / "_test_tmp"


@contextlib.contextmanager
def scratch():
    """仓库内临时目录（沙箱不允许写系统 TEMP 的 ACL 时会报 WinError 5）。"""
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    path = SCRATCH_ROOT / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class HeaderTest(unittest.TestCase):
    def test_split_unit(self) -> None:
        """表头括号里的单位要能拆出来，全角括号也要认。"""
        self.assertEqual(fa.split_header("距离(km)"), ("距离", "km"))
        self.assertEqual(fa.split_header("累计爬升（m）"), ("累计爬升", "m"))
        self.assertEqual(fa.split_header("Avg HR"), ("avghr", ""))

    def test_map_columns_requires_core_columns(self) -> None:
        with self.assertRaises(fa.AdapterError):
            fa.map_columns(["Distance", "Avg HR"])

    def test_map_columns_warns_on_duplicate(self) -> None:
        """日期 与 开始时间 都映射到 date 时取前者并留警告，不静默取舍。"""
        mapped = fa.map_columns(["日期", "开始时间", "运动类型", "时长"])
        self.assertEqual(mapped.columns["date"], "日期")
        self.assertTrue(any("开始时间" in w for w in mapped.warnings))

    def test_detect_format(self) -> None:
        garmin = ["Activity Type", "Date", "Distance", "Time", "Avg HR", "Max HR"]
        huawei = ["运动类型", "开始时间", "时长", "距离(km)", "平均心率"]
        self.assertEqual(fa.detect_format(garmin), "garmin")
        self.assertEqual(fa.detect_format(huawei), "huawei")
        self.assertIsNone(fa.detect_format(["姓名", "得分"]))


class ValueParserTest(unittest.TestCase):
    def test_duration(self) -> None:
        self.assertEqual(fa.parse_duration("48:00"), 2880)
        self.assertEqual(fa.parse_duration("0:48:00"), 2880)
        self.assertEqual(fa.parse_duration("1:02:03"), 3723)
        self.assertEqual(fa.parse_duration("2880"), 2880)
        self.assertEqual(fa.parse_duration("48分"), 2880)
        self.assertEqual(fa.parse_duration("1小时2分"), 3720)
        self.assertEqual(fa.parse_duration("48", "min"), 2880)
        self.assertIsNone(fa.parse_duration(""))
        self.assertIsNone(fa.parse_duration("—"))

    def test_duration_garbage_raises(self) -> None:
        with self.assertRaises(fa.AdapterError):
            fa.parse_duration("四十八分钟")

    def test_pace(self) -> None:
        self.assertEqual(fa.parse_pace("6:00"), 360)
        self.assertEqual(fa.parse_pace('6\'00"'), 360)
        self.assertEqual(fa.parse_pace("360"), 360)
        self.assertEqual(fa.parse_pace("5:44/km"), 344)
        self.assertIsNone(fa.parse_pace(""))

    def test_distance_units(self) -> None:
        self.assertEqual(fa.parse_distance_m("8.00", "km"), 8000.0)
        self.assertEqual(fa.parse_distance_m("8000", "m"), 8000.0)
        self.assertEqual(fa.parse_distance_m("1,234.5", "m"), 1234.5)
        self.assertIsNone(fa.parse_distance_m("N/A"))

    def test_distance_negative_raises(self) -> None:
        with self.assertRaises(fa.AdapterError):
            fa.parse_distance_m("-3")

    def test_hr(self) -> None:
        self.assertEqual(fa.parse_int("152 bpm"), 152)
        self.assertEqual(fa.parse_int("152.4"), 152)
        self.assertIsNone(fa.parse_int("-"))

    def test_start_time(self) -> None:
        self.assertEqual(fa.parse_start_time("2026-11-12 06:30:00"), ("2026-11-12", "06:30"))
        self.assertEqual(
            fa.parse_start_time("2026-11-12T06:30:00+08:00"), ("2026-11-12", "06:30")
        )
        self.assertEqual(fa.parse_start_time("2026/11/12"), ("2026-11-12", None))
        self.assertEqual(fa.parse_start_time(""), ("", None))

    def test_start_time_invalid_date_raises(self) -> None:
        with self.assertRaises(fa.AdapterError):
            fa.parse_start_time("2026-02-30 06:30:00")
        with self.assertRaises(fa.AdapterError):
            fa.parse_start_time("十一月十二日")

    def test_map_sport(self) -> None:
        self.assertEqual(fa.map_sport("户外跑步"), "run")
        self.assertEqual(fa.map_sport("室内跑步"), "run")
        self.assertEqual(fa.map_sport("Running"), "run")
        self.assertEqual(fa.map_sport("骑行"), "bike")
        self.assertEqual(fa.map_sport("力量训练"), "strength")
        self.assertEqual(fa.map_sport("健走"), "other")
        self.assertIsNone(fa.map_sport("滑板"))


class GarminSampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fieldnames, cls.rows = import_export.read_raw_csv(GARMIN_SAMPLE)
        cls.adapted, cls.warnings = fa.adapt(cls.fieldnames, cls.rows, "garmin")

    def test_row_count(self) -> None:
        self.assertEqual(len(self.adapted), 5)

    def test_distance_and_pace_converted(self) -> None:
        first = self.adapted[0]
        self.assertEqual(first["date"], "2026-11-12")
        self.assertEqual(first["start_time"], "06:30")
        self.assertEqual(first["duration_s"], "2880")
        self.assertEqual(first["distance_m"], "8000.0")
        self.assertEqual(first["avg_pace_s_per_km"], "360")
        self.assertEqual(first["source"], "garmin")

    def test_machine_readable_fields_are_strings(self) -> None:
        for row in self.adapted:
            for value in row.values():
                self.assertIsInstance(value, str)

    def test_cycling_without_pace_keeps_null(self) -> None:
        cycling = self.adapted[2]
        self.assertEqual(cycling["sport"], "bike")
        self.assertEqual(cycling["avg_pace_s_per_km"], "")

    def test_missing_distance_and_max_hr_are_empty(self) -> None:
        last = self.adapted[4]
        self.assertEqual(last["distance_m"], "")
        self.assertEqual(last["max_hr"], "")
        self.assertEqual(last["duration_s"], "180")

    def test_into_csv_parser_counts(self) -> None:
        activities, skipped, rejected, _ = csv_parser.parse_rows(self.adapted)
        self.assertEqual(len(activities), 3)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["rule_id"], "R02")


class HuaweiSampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fieldnames, cls.rows = import_export.read_raw_csv(HUAWEI_SAMPLE)
        cls.adapted, cls.warnings = fa.adapt(cls.fieldnames, cls.rows, "huawei")

    def test_dash_becomes_missing_not_zero(self) -> None:
        cycling = self.adapted[2]
        self.assertEqual(cycling["avg_hr"], "")
        self.assertEqual(cycling["max_hr"], "")

    def test_strength_keeps_zero_distance(self) -> None:
        """距离 0 是真实值（力量课），不能被当成缺失。"""
        strength = self.adapted[3]
        self.assertEqual(strength["sport"], "strength")
        self.assertEqual(strength["distance_m"], "0.0")

    def test_pace_min_sec_parsed(self) -> None:
        self.assertEqual(self.adapted[0]["avg_pace_s_per_km"], "344")

    def test_rows_without_hr_dropped_by_parser(self) -> None:
        activities, skipped, rejected, _ = csv_parser.parse_rows(self.adapted)
        self.assertEqual(len(activities), 3)
        self.assertEqual(len(skipped), 2)
        self.assertEqual(rejected, [])


class ZeroHrTest(unittest.TestCase):
    def test_zero_hr_treated_as_missing(self) -> None:
        """Keep 这类导出缺心率时写 0：0 要按缺失处理，不能让 0 进数据。"""
        headers = ["运动类型", "开始时间", "时长", "距离(km)", "平均心率", "最大心率"]
        rows = [{"运动类型": "跑步", "开始时间": "2026-11-12 06:30:00",
                 "时长": "0:30:00", "距离(km)": "5.0", "平均心率": "0", "最大心率": "0"}]
        adapted, warnings = fa.adapt(headers, rows, "huawei")
        self.assertEqual(adapted[0]["avg_hr"], "")
        self.assertEqual(adapted[0]["max_hr"], "")
        self.assertTrue(any("视为缺失" in w for w in warnings))
        activities, skipped, _, _ = csv_parser.parse_rows(adapted)
        self.assertEqual(activities, [])
        self.assertEqual(len(skipped), 1)


class CommandLineTest(unittest.TestCase):
    def test_auto_detect_and_validate(self) -> None:
        """CLI 产出的 activity.json 必须通过 contracts/validate_contract.py。"""
        with scratch() as tmp:
            out = tmp / "activity.json"
            run = subprocess.run(
                [sys.executable, str(ROOT / "src" / "p2_ingest" / "import_export.py"),
                 str(GARMIN_SAMPLE), "-o", str(out), "--middle", str(tmp / "middle.csv")],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("自动识别格式：garmin", run.stdout)

            validator = subprocess.run(
                [sys.executable, str(ROOT / "contracts" / "validate_contract.py"), str(out)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(validator.returncode, 0, validator.stdout + validator.stderr)
            document = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(document["activities"]), 3)

    def test_unknown_format_fails_cleanly(self) -> None:
        with scratch() as tmp:
            bad = tmp / "bad.csv"
            bad.write_text("姓名,得分\n张三,90\n", encoding="utf-8", newline="\n")
            run = subprocess.run(
                [sys.executable, str(ROOT / "src" / "p2_ingest" / "import_export.py"),
                 str(bad), "-o", str(tmp / "activity.json")],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(run.returncode, 1)
            self.assertIn("认不出格式", run.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
