"""Generate a shareable derivative of a locally imported activity document."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

if __package__:
    from .csv_parser import DEFAULT_ATHLETE, SCHEMA_VERSION, TIMEZONE
else:
    from csv_parser import DEFAULT_ATHLETE, SCHEMA_VERSION, TIMEZONE


SAMPLE_DIR = Path(__file__).resolve().parents[2] / "data" / "sample"
DEMO_MONDAY = date(2000, 1, 3)
REQUIRED_NUMBERS = ("duration_s", "distance_m", "avg_hr", "max_hr")
OPTIONAL_NUMBERS = ("elevation_gain_m", "avg_pace_s_per_km", "rpe", "sleep_h")
SPORTS = ("run", "bike", "swim", "strength", "other")
DEFAULT_PRIVATE_TERMS = ("常州", "宿舍")


def anonymize(document: dict, athlete_id: str) -> dict:
    if not re.fullmatch(r"anon_[0-9]{2,6}", athlete_id):
        raise ValueError("匿名 ID 应形如 anon_01")
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("请输入 P2 生成的 v1.0 activity.json")
    activities = document.get("activities")
    if not isinstance(activities, list):
        raise ValueError("输入缺少 activities 列表")

    records: list[tuple[date, dict]] = []
    for index, activity in enumerate(activities, start=1):
        if not isinstance(activity, dict):
            raise ValueError(f"第 {index} 条活动不是对象")
        try:
            day = date.fromisoformat(activity.get("date", ""))
        except (TypeError, ValueError):
            raise ValueError(f"第 {index} 条活动的日期无效") from None
        sport = activity.get("sport")
        if sport not in SPORTS:
            raise ValueError(f"第 {index} 条活动的运动类型无效")
        sanitized = {"sport": sport}
        for field in (*REQUIRED_NUMBERS, *OPTIONAL_NUMBERS):
            value = activity.get(field)
            if value is None and field in OPTIONAL_NUMBERS:
                continue
            if type(value) not in (int, float) or (isinstance(value, float) and not math.isfinite(value)):
                raise ValueError(f"第 {index} 条活动的 {field} 不是有效数值")
            sanitized[field] = value
        records.append((day, sanitized))

    records.sort(key=lambda record: record[0])
    output = []
    if records:
        first_day = records[0][0]
        origin = first_day - timedelta(days=first_day.weekday())
        day_counts: Counter[date] = Counter()
        for day, sanitized in records:
            demo_day = DEMO_MONDAY + (day - origin)
            day_counts[demo_day] += 1
            sanitized["date"] = demo_day.isoformat()
            sanitized["activity_id"] = f"A{demo_day:%Y%m%d}-{day_counts[demo_day]:02d}"
            output.append(sanitized)
    return {"schema_version": SCHEMA_VERSION, "athlete_id": athlete_id,
            "timezone": TIMEZONE, "activities": output}


def no_private_terms(text: str, terms: list[str]) -> None:
    def normalize(value: str) -> str:
        return "".join(unicodedata.normalize("NFKC", value).casefold().split())

    normalized_text = normalize(text)
    if any(normalize(term) in normalized_text for term in terms):
        raise ValueError("脱敏自检发现禁止词，未写出文件")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="将本地 activity.json 转成脱敏演示数据")
    parser.add_argument("input", type=Path, help="本地 P2 活动 JSON")
    parser.add_argument("-o", "--out", type=Path, default=Path("out/activity_anonymized.json"))
    parser.add_argument("--athlete", default=DEFAULT_ATHLETE, help="匿名 ID，如 anon_01")
    parser.add_argument("--denylist", type=Path, help="本地 UTF-8 文件，每行一个姓名或定位词")
    args = parser.parse_args(argv)
    try:
        output = args.out.resolve()
        if output == args.input.resolve() or (args.denylist and output == args.denylist.resolve()):
            raise ValueError("输入与输出路径不得重合")
        private_terms = []
        if args.denylist:
            private_terms = [term for line in args.denylist.read_text(encoding="utf-8-sig").splitlines()
                             if (term := line.strip())]
        if output.is_relative_to(SAMPLE_DIR.resolve()) and not private_terms:
            raise ValueError("写入 data/sample/ 前须提供非空的本地 --denylist")
        document = json.loads(args.input.read_text(encoding="utf-8-sig"))
        sanitized = anonymize(document, args.athlete)
        text = json.dumps(sanitized, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        no_private_terms(text, [*DEFAULT_PRIVATE_TERMS, *private_terms])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8", newline="\n")
    except (OSError, OverflowError, ValueError) as exc:
        print(f"FAIL {exc}")
        return 1
    print(f"脱敏输出 {len(sanitized['activities'])} 条，禁止词命中 0，已写出 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
