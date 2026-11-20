#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P2 数据入口：把「CSV 中间格式」转成 activity.json（符合 contracts/activity.schema.json）。

用法：
    python src/p2_ingest/csv_parser.py data/sample/activities_sample.csv -o out/activity.json
    python src/p2_ingest/csv_parser.py data/raw/export.csv --athlete anon_01 --strict

设计约束（照 docs/CSV中间格式.md 来）：
- 只读中间格式，不猜原始导出的各种奇怪格式；适配器由 P2 另外写。
- 缺失一律 null，绝不填 0；缺必填字段的行整行丢弃并记录原因。
- 心率不合理的行按 R02 不入库，单独写入 rejected.json（旁路保留，让人看得见）。
- 输出 UTF-8、LF、缩进 2；写入前不做静默修正。
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import sys
from datetime import datetime

if __package__:
    from .csv_input import CsvInputError, read_csv
else:
    from csv_input import CsvInputError, read_csv

SCHEMA_VERSION = "1.0"
TIMEZONE = "Asia/Shanghai"
DEFAULT_ATHLETE = "anon_01"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")

SPORT_MAP = {
    "run": "run", "跑步": "run", "跑": "run", "越野跑": "run",
    "bike": "bike", "骑行": "bike", "自行车": "bike", "cycling": "bike",
    "swim": "swim", "游泳": "swim", "swimming": "swim",
    "strength": "strength", "力量": "strength", "力量训练": "strength", "gym": "strength",
    "other": "other", "走": "other", "徒步": "other", "hike": "other", "其他": "other",
}
SOURCE_ALLOWED = {"garmin", "coros", "huawei", "keep", "manual", "csv"}
REQUIRED_FIELDS = ("date", "sport", "duration_s", "distance_m", "avg_hr", "max_hr")
OPTIONAL_FIELDS = ("start_time", "elevation_gain_m", "avg_pace_s_per_km", "rpe", "sleep_h", "pain", "source")

HR_RANGE = (30, 230)
HR_MAX_RANGE = (30, 250)


class RowError(ValueError):
    """一行数据不能入库的原因。"""


class DeviceAnomalyError(RowError):
    """心率等指标明显是设备/录入异常：不入库，单独旁路记录（R02）。"""


def _text(row: dict, key: str) -> str:
    value = (row.get(key) or "").strip()
    return value


def _opt_int(row: dict, key: str, low: int, high: int) -> int | None:
    raw = _text(row, key)
    if raw == "":
        return None
    try:
        value = round(float(raw))
    except (ValueError, OverflowError):
        raise RowError(f"{key} 不是有限数字") from None
    if not low <= value <= high:
        raise RowError(f"{key} 超出范围 {low}–{high}")
    return value


def _opt_float(row: dict, key: str, low: float, high: float) -> float | None:
    raw = _text(row, key)
    if raw == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        raise RowError(f"{key} 不是数字") from None
    if not low <= value <= high:
        raise RowError(f"{key} 超出范围 {low}–{high}")
    return value


def build_activity(row: dict, athlete_seq: int) -> tuple[dict, list[str]]:
    """把一行 CSV 转成 activity 对象；不合格的行抛 RowError。"""
    warnings: list[str] = []

    date = _text(row, "date")
    if not DATE_RE.match(date):
        raise RowError("date 缺失或不是 YYYY-MM-DD")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise RowError("date 不是有效日期") from None

    raw_sport = _text(row, "sport")
    sport = SPORT_MAP.get(raw_sport.lower()) or SPORT_MAP.get(raw_sport)
    if sport is None:
        raise RowError("sport 缺失或无法识别")

    raw_duration = _text(row, "duration_s")
    if raw_duration == "":
        raise RowError("duration_s 缺失（本行丢弃，不猜）")
    try:
        duration_s = int(float(raw_duration))
    except (ValueError, OverflowError):
        raise RowError("duration_s 不是有限数字") from None
    if duration_s < 1:
        raise RowError("duration_s 必须 ≥ 1 秒")

    raw_distance = _text(row, "distance_m")
    if sport == "run" and not raw_distance:
        raise RowError("distance_m 缺失，跑步活动需要实测距离")
    try:
        distance_m = float(raw_distance or "0")
    except ValueError:
        raise RowError("distance_m 不是数字") from None
    if not math.isfinite(distance_m) or distance_m < 0:
        raise RowError("distance_m 必须为有限的非负数字")
    distance_m = round(distance_m, 1)

    avg_hr = _opt_int(row, "avg_hr", *HR_RANGE)
    max_hr = _opt_int(row, "max_hr", *HR_MAX_RANGE)
    if avg_hr is None or max_hr is None:
        raise RowError("avg_hr / max_hr 缺失（不猜，整行丢弃）")

    if avg_hr > max_hr or avg_hr <= 0:
        raise DeviceAnomalyError(
            f"心率不合理（avg {avg_hr} > max {max_hr}），按 R02 不入库，写入 rejected.json"
        )

    start_time = _text(row, "start_time") or None
    if start_time is not None:
        try:
            if not TIME_RE.match(start_time):
                raise ValueError
            datetime.strptime(start_time, "%H:%M")
        except ValueError:
            raise RowError("start_time 不是有效的 HH:MM") from None

    elevation = _opt_float(row, "elevation_gain_m", 0, 10000)
    rpe = _opt_int(row, "rpe", 0, 10)
    sleep_h = _opt_float(row, "sleep_h", 0, 24)
    pain = _text(row, "pain") or None

    pace = _opt_float(row, "avg_pace_s_per_km", 120, 1200)
    if distance_m > 0:
        estimate = duration_s / distance_m * 1000
        if pace is None:
            pace = round(estimate) if math.isfinite(estimate) else None
            if pace is None or not 120 <= pace <= 1200:
                warnings.append("按距离推算的配速超出合理区间，置为 null")
                pace = None
        elif sport == "run" and abs(estimate - pace) > 15:
            raise RowError("avg_pace_s_per_km 与用时和距离推算的配速相差超过 15 秒/公里")

    raw_source = _text(row, "source").lower()
    source = raw_source if raw_source in SOURCE_ALLOWED else "csv"
    if raw_source and raw_source not in SOURCE_ALLOWED:
        warnings.append("source 未知，按 csv 处理")

    activity = {
        "activity_id": f"A{date.replace('-', '')}-{athlete_seq:02d}",
        "date": date,
        "start_time": start_time,
        "sport": sport,
        "duration_s": duration_s,
        "distance_m": distance_m,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "elevation_gain_m": elevation,
        "avg_pace_s_per_km": pace,
        "rpe": rpe,
        "sleep_h": sleep_h,
        "pain": pain,
        "source": source,
        "device_anomaly": False,
    }
    return activity, warnings


def parse_rows(rows: list[dict]) -> tuple[list[dict], list[tuple[int, str]], list[dict], list[str]]:
    """返回 (活动列表, [(行号, 丢弃原因)], [设备异常记录], [警告])。"""
    activities: list[dict] = []
    skipped: list[tuple[int, str]] = []
    rejected: list[dict] = []
    warnings: list[str] = []
    per_date: dict[str, int] = {}

    for index, row in enumerate(rows, start=2):  # 第 1 行是表头
        try:
            date_hint = _text(row, "date")
            per_date[date_hint] = per_date.get(date_hint, 0) + 1
            activity, row_warnings = build_activity(row, per_date[date_hint])
        except DeviceAnomalyError as exc:
            rejected.append({
                "line": index,
                "reason": str(exc),
                "rule_id": "R02",
                "row": {k: v for k, v in row.items() if v not in (None, "")},
            })
            continue
        except RowError as exc:
            skipped.append((index, str(exc)))
            continue
        activities.append(activity)
        warnings.extend(f"第 {index} 行：{w}" for w in row_warnings)

    activities.sort(key=lambda a: (a["date"], a["start_time"] or ""))
    return activities, skipped, rejected, warnings


def read_middle_csv(path: pathlib.Path) -> tuple[list[dict], str]:
    fieldnames, rows, encoding = read_csv(path)
    missing = [c for c in REQUIRED_FIELDS if c not in fieldnames]
    if missing:
        raise CsvInputError(f"表头缺列：{', '.join(missing)}（见 docs/CSV中间格式.md）")
    return rows, encoding


def load_csv(path: pathlib.Path) -> list[dict]:
    return read_middle_csv(path)[0]


def build_document(activities: list[dict], athlete_id: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "athlete_id": athlete_id,
        "timezone": TIMEZONE,
        "generated_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "activities": activities,
    }


def write_data_check(path: pathlib.Path, rows: list[dict], activities: list[dict],
                     skipped: list[tuple[int, str]], rejected: list[dict], warnings: list[str], *,
                     encoding: str, adapter_warning_count: int) -> None:
    lines = [
        "# 数据体检报告", "",
        f"- 输入编码：{encoding}",
        f"- 读入 {len(rows)} 行，入库 {len(activities)} 条，丢弃 {len(skipped)} 条，设备异常旁路 {len(rejected)} 条。",
        f"- 格式适配警告 {adapter_warning_count} 条，入库警告 {len(warnings)} 条。",
        "", "## 输入缺失字段", "",
    ]
    counts = [(field, sum(not _text(row, field) for row in rows))
              for field in (*REQUIRED_FIELDS, *OPTIONAL_FIELDS)]
    lines.extend([f"- `{field}`：{count} 行" for field, count in counts if count] or ["无。"])
    lines.extend(["", "## 丢弃记录", ""])
    lines.extend([f"- 第 {index} 行：{reason}" for index, reason in skipped] or ["无。"])
    lines.extend(["", "## 设备异常旁路", ""])
    lines.extend([f"- 第 {item['line']} 行（{item['rule_id']}）：平均心率高于最大心率。"
                  for item in rejected] or ["无。"])
    lines.extend(["", "## 入库警告", ""])
    lines.extend([f"- {warning}" for warning in warnings] or ["无。"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def import_rows(rows: list[dict], out_path: pathlib.Path, *, source_name: str, encoding: str,
                athlete_id: str, strict: bool, adapter_warning_count: int = 0) -> int:
    if out_path.name.lower() in {"rejected.json", "data_check.md"}:
        print("FAIL activity 输出路径与导入附属文件重名")
        return 1
    activities, skipped, rejected, warnings = parse_rows(rows)
    document = build_document(activities, athlete_id)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(
        f"读入 {len(rows)} 行 → 入库 {len(activities)} 条，"
        f"丢弃 {len(skipped)} 条，设备异常旁路 {len(rejected)} 条"
    )
    for line_no, reason in skipped:
        print(f"  [丢弃] 第 {line_no} 行：{reason}")
    for item in rejected:
        print(f"  [旁路] 第 {item['line']} 行：{item['reason']}")
    for warning in warnings:
        print(f"  [警告] {warning}")
    print(f"已写出 {out_path}（{out_path.stat().st_size} B）")

    reject_path = out_path.with_name("rejected.json")
    if rejected or reject_path.is_file():
        reject_path.write_text(
            json.dumps({"schema_version": SCHEMA_VERSION, "source": source_name, "items": rejected},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if rejected:
            print(f"设备异常 {len(rejected)} 条已旁路到 {reject_path}（R02，不进主数据）")

    report_path = out_path.with_name("data_check.md")
    write_data_check(report_path, rows, activities, skipped, rejected, warnings,
                     encoding=encoding, adapter_warning_count=adapter_warning_count)
    print(f"数据体检报告已写出 {report_path}")

    if strict and (skipped or rejected):
        print("结论：--strict 模式下不允许丢弃行。")
        return 1
    print("结论：解析完成，请继续跑 contracts/validate_contract.py 校验。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CSV 中间格式 → activity.json")
    parser.add_argument("csv_path", help="输入 CSV（UTF-8，兼容 BOM 和 GBK）")
    parser.add_argument("-o", "--out", default="out/activity.json", help="输出路径")
    parser.add_argument("--athlete", default=DEFAULT_ATHLETE, help="匿名 ID，如 anon_01")
    parser.add_argument("--strict", action="store_true", help="有任何行被丢弃就以退出码 1 结束")
    args = parser.parse_args(argv)
    path = pathlib.Path(args.csv_path)
    output = pathlib.Path(args.out)
    if path.resolve() in {candidate.resolve() for candidate in
                          (output, output.with_name("data_check.md"), output.with_name("rejected.json"))}:
        print("FAIL 输入与输出路径不得重合")
        return 1
    try:
        rows, encoding = read_middle_csv(path)
        return import_rows(rows, output, source_name=path.name, encoding=encoding,
                           athlete_id=args.athlete, strict=args.strict)
    except (CsvInputError, OSError) as exc:
        print(f"FAIL {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
