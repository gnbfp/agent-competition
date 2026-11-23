"""Acceptance checks for local encoding, data quality, and anonymization."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src.p2_ingest import anonymize
from tools import check_env


ROOT = Path(__file__).resolve().parents[1]


def run_script(script: str, *args: str | Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(ROOT / script), *map(str, args)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )


class ImportQualityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.out = self.temp / "out" / "activity.json"

    def require_success(self, run: subprocess.CompletedProcess) -> None:
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_gbk_device_export_reports_conversion_and_dropped_rows(self) -> None:
        original = ROOT / "data/sample/huawei_export_sample.csv"
        source = self.temp / "huawei.csv"
        source.write_bytes(original.read_text(encoding="utf-8").encode("gbk"))
        self.require_success(run_script("src/p2_ingest/import_export.py", source, "-o", self.out))
        self.require_success(run_script("contracts/validate_contract.py", self.out))
        report = self.out.with_name("data_check.md").read_text(encoding="utf-8")
        self.assertIn("输入编码：GBK", report)
        self.assertIn("入库 5 条，丢弃 0 条", report)
        self.assertIn("`avg_hr`：2 行", report)

    def test_middle_csv_report_separates_bad_rows_and_device_anomalies(self) -> None:
        source = self.temp / "middle.csv"
        source.write_bytes((
            "date,sport,duration_s,distance_m,avg_hr,max_hr,avg_pace_s_per_km,pain\n"
            "2026-11-12,跑步,1800,5000,150,170,360,测试原始主诉\n"
            "2026-11-13,跑步,1800,5000,200,170,,\n"
            "2026-11-14,测试私人标签,1800,5000,150,170,,\n"
            "2026-11-15,跑步,inf,5000,150,170,,\n"
            "2026-11-16,跑步,1800,5000,150,170,300,\n"
        ).encode("gbk"))
        self.require_success(run_script("src/p2_ingest/csv_parser.py", source, "-o", self.out))
        self.require_success(run_script("contracts/validate_contract.py", self.out))
        report = self.out.with_name("data_check.md").read_text(encoding="utf-8")
        self.assertIn("输入编码：GBK", report)
        self.assertIn("入库 1 条，丢弃 3 条，设备异常旁路 1 条", report)
        self.assertIn("第 3 行（R02）", report)
        self.assertIn("duration_s 不是有限数字", report)
        self.assertIn("配速相差超过 15 秒/公里", report)
        self.assertNotIn("测试私人标签", report)
        self.assertNotIn("测试原始主诉", report)
        self.assertEqual(json.loads(self.out.with_name("rejected.json").read_text(encoding="utf-8"))
                         ["items"][0]["rule_id"], "R02")

    def test_undecodable_input_fails_without_writing_outputs(self) -> None:
        source = self.temp / "broken.csv"
        source.write_bytes(b"date,sport\n\xff")
        for command in ("src/p2_ingest/csv_parser.py", "src/p2_ingest/import_export.py"):
            with self.subTest(command=command):
                result = run_script(command, source, "-o", self.out)
                self.assertEqual(result.returncode, 1)
                self.assertIn("不是有效的 UTF-8 或 GBK", result.stdout)
                self.assertFalse(self.out.exists())

    def test_missing_nonrunning_distance_is_not_a_measured_zero(self) -> None:
        source = self.temp / "middle.csv"
        source.write_text(
            "date,sport,duration_s,distance_m,avg_hr,max_hr\n"
            "2026-11-12,bike,1800,,150,170\n"
            "2026-11-13,strength,1800,0,130,150\n", encoding="utf-8",
        )
        self.require_success(run_script("src/p2_ingest/csv_parser.py", source, "-o", self.out))
        activities = json.loads(self.out.read_text(encoding="utf-8"))["activities"]
        self.assertEqual([(row["sport"], row["distance_m"]) for row in activities], [("strength", 0)])
        self.assertIn("distance_m 缺失", self.out.with_name("data_check.md").read_text(encoding="utf-8"))

    def test_environment_check_rejects_gbk_sample_but_ignores_raw_input(self) -> None:
        raw = self.temp / "data/raw"
        sample = self.temp / "data/sample"
        raw.mkdir(parents=True)
        sample.mkdir()
        payload = "项目\n跑步\n".encode("gbk")
        (raw / "private.csv").write_bytes(payload)
        with patch.object(check_env, "ROOT", self.temp), patch.object(check_env, "RESULT", []):
            check_env.check_encoding()
            self.assertEqual(check_env.RESULT[-1][1], "PASS")
            (sample / "export.csv").write_bytes(payload)
            check_env.check_encoding()
            _, status, detail = check_env.RESULT[-1]
            self.assertEqual(status, "FAIL")
            self.assertIn("export.csv", detail)
            self.assertNotIn("private.csv", detail)

    def test_anonymizer_checks_terms_before_writing_shareable_sample(self) -> None:
        input_path = self.temp / "activity_input.json"
        input_path.write_text(json.dumps({
            "schema_version": "1.0", "athlete_id": "测试姓名", "activities": [{
                "activity_id": "device-original", "date": "2026-11-12", "start_time": "06:31",
                "sport": "run", "duration_s": 1800, "distance_m": 5000,
                "avg_hr": 150, "max_hr": 170, "avg_pace_s_per_km": 360,
                "pain": "测试姓名在宿舍附近不适", "phone": "12345678",
                "gps": [31.71, 119.95], "device_serial": "device-original", "source": "garmin",
            }],
        }, ensure_ascii=False), encoding="utf-8")
        sample = self.temp / "data/sample"
        destination = sample / "activity_demo.json"
        denylist = self.temp / "private_terms.txt"
        args = [str(input_path), "-o", str(destination), "--athlete", "anon_12"]
        with patch.object(anonymize, "SAMPLE_DIR", sample), redirect_stdout(io.StringIO()):
            self.assertEqual(anonymize.main(args), 1)
            denylist.write_text("anon_12\n", encoding="utf-8")
            self.assertEqual(anonymize.main([*args, "--denylist", str(denylist)]), 1)
            self.assertFalse(destination.exists())
            denylist.write_text("测试姓名\n测试地点\n", encoding="utf-8")
            self.assertEqual(anonymize.main([*args, "--denylist", str(denylist)]), 0)
        self.require_success(run_script("contracts/validate_contract.py", destination))
        output = destination.read_text(encoding="utf-8")
        for private in ("测试姓名", "宿舍", "06:31", "12345678", "119.95", "device-original", "2026-11-12"):
            self.assertNotIn(private, output)
        sanitized = json.loads(output)
        self.assertEqual(sanitized["athlete_id"], "anon_12")
        activity = sanitized["activities"][0]
        self.assertEqual(activity["date"], "2000-01-06")
        self.assertEqual(activity["duration_s"], 1800)
