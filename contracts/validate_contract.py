#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contract validator — stdlib only, no pip install required.

Checks a JSON file against its schema and adds a few cross-field rules that
JSON Schema cannot express (unit / range / consistency).

Usage
  python validate_contract.py                     # validate contracts/samples/*
  python validate_contract.py <file.json> [...]   # validate specific files
  python validate_contract.py --dir out/          # validate every *.json under a dir
Exit code 0 = all pass, 1 = at least one error.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "samples")

SCHEMA_BY_PREFIX = [
    ("activity", "activity.schema.json"),
    ("metrics", "metrics.schema.json"),
    ("plan", "plan.schema.json"),
    ("report", "report.schema.json"),
]

TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def fmt_path(path):
    return "$" + path


def check(instance, schema, path="", errors=None):
    errors = errors if errors is not None else []

    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(TYPE_CHECKS[t](instance) for t in types):
            errors.append("%s: 类型应为 %s，实际是 %s" % (
                fmt_path(path), "/".join(types), type(instance).__name__))
            return errors

    if "enum" in schema and instance not in schema["enum"]:
        errors.append("%s: 值 %r 不在允许列表 %s 中" % (fmt_path(path), instance, schema["enum"]))

    if "pattern" in schema and isinstance(instance, str):
        if not re.search(schema["pattern"], instance):
            errors.append("%s: 值 %r 不匹配正则 %s" % (fmt_path(path), instance, schema["pattern"]))

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append("%s: %s < 最小值 %s" % (fmt_path(path), instance, schema["minimum"]))
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append("%s: %s > 最大值 %s" % (fmt_path(path), instance, schema["maximum"]))

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append("%s: 缺少必填字段 %r" % (fmt_path(path), key))
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    errors.append("%s: 出现未定义字段 %r（拼写错误或未走契约变更）" % (fmt_path(path), key))
        for key, sub in props.items():
            if key in instance:
                check(instance[key], sub, path + "." + key, errors)

    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            check(item, schema["items"], path + "[%d]" % i, errors)

    return errors


def load_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def schema_for(path):
    base = os.path.basename(path).lower()
    for prefix, schema_name in SCHEMA_BY_PREFIX:
        if base.startswith(prefix):
            return os.path.join(HERE, schema_name)
    return None


def num(value):
    """Return value only when it is a real number (guard against bad samples)."""
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) else None


def cross_checks(name, doc, errors):
    """Rules JSON Schema cannot express for this project."""
    if name.startswith("activity"):
        seen = set()
        for i, act in enumerate(doc.get("activities", [])):
            if not isinstance(act, dict):
                continue
            aid = act.get("activity_id")
            if aid in seen:
                errors.append("$.activities[%d]: activity_id %r 重复" % (i, aid))
            seen.add(aid)
            avg_hr, max_hr = num(act.get("avg_hr")), num(act.get("max_hr"))
            if avg_hr is not None and max_hr is not None and max_hr < avg_hr:
                errors.append("$.activities[%d]: max_hr(%s) < avg_hr(%s)" % (i, max_hr, avg_hr))
            dur, dist = num(act.get("duration_s")), num(act.get("distance_m"))
            stated = num(act.get("avg_pace_s_per_km"))
            if dur and dist and stated is not None and act.get("sport") == "run":
                pace = dur / (dist / 1000.0)
                if abs(pace - stated) > 15:
                    errors.append("$.activities[%d]: avg_pace_s_per_km(%s) 与 duration/distance 推算值(%.0f) 不一致"
                                  % (i, stated, pace))
    if name.startswith("metrics"):
        load = doc.get("load") or {}
        roll, ewma = num(load.get("acwr_rolling")), num(load.get("acwr_ewma"))
        if roll is not None and ewma is not None and abs(roll - ewma) > 1.0:
            errors.append("$.load: acwr_rolling 与 acwr_ewma 差 %.2f，超过 1.0，检查是否单位/口径不一致" % abs(roll - ewma))
        cap = doc.get("capacity") or {}
        vals = [num(m.get("value")) for m in cap.get("methods", []) if isinstance(m, dict)]
        vals = [v for v in vals if v is not None]
        if len(vals) >= 2 and max(vals) > 0:
            spread = (max(vals) - min(vals)) / max(vals) * 100
            if spread > 5 and cap.get("consistency_ok") is True:
                errors.append("$.capacity: 三法差异 %.1f%% > 5%%，但 consistency_ok=true" % spread)
    if name.startswith("plan"):
        days = [d for d in doc.get("days", []) if isinstance(d, dict)]
        dates = [d.get("date") for d in days]
        if len(dates) != len(set(dates)):
            errors.append("$.days: 日期重复")
        for i, d in enumerate(days):
            if not d.get("rules"):
                errors.append("$.days[%d]: 没有任何 rule_id，违反 R20 依据覆盖率" % i)
            if d.get("kind") == "rest" and (num(d.get("duration_min")) or 0) > 0:
                errors.append("$.days[%d]: kind=rest 但 duration_min > 0" % i)
    if name.startswith("report"):
        plan = doc.get("plan") or {}
        rules_in_plan = {r for d in plan.get("days", []) if isinstance(d, dict)
                         for r in (d.get("rules") or [])}
        rules_in_risk = {r.get("rule_id") for r in doc.get("risks", []) if isinstance(r, dict)}
        rules_in_ev = {e.get("rule_id") for e in doc.get("evidence", []) if isinstance(e, dict)}
        missing = rules_in_plan - (rules_in_risk | rules_in_ev)
        if missing:
            errors.append("$.evidence: 计划里引用的 %s 在 risks/evidence 中找不到依据" % sorted(missing))
        norm = {r for r in rules_in_risk | rules_in_ev if r}
        unused = norm - rules_in_plan
        if unused:
            errors.append("$.evidence: %s 有依据但计划里没用到（规则库与计划脱节）" % sorted(unused))


def validate_file(path):
    schema_path = schema_for(path)
    if not schema_path:
        return ["无法按文件名判断该用哪个 schema（应以 activity/metrics/plan/report 开头）"]
    doc = load_json(path)
    errors = check(doc, load_json(schema_path))
    cross_checks(os.path.basename(path).lower(), doc, errors)
    return errors


def main(argv):
    targets = []
    if not argv:
        targets = sorted(os.path.join(SAMPLES, f) for f in os.listdir(SAMPLES) if f.endswith(".json"))
    elif argv[0] == "--dir" and len(argv) > 1:
        for root, _, files in os.walk(argv[1]):
            targets += [os.path.join(root, f) for f in sorted(files) if f.endswith(".json")
                        and not f.endswith(".schema.json")]
    else:
        targets = argv

    total_errors = 0
    for path in targets:
        name = os.path.basename(path)
        try:
            errors = validate_file(path)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            errors = ["读取失败: %s" % exc]
        if errors:
            total_errors += len(errors)
            print("[FAIL] %s  (%d 处)" % (name, len(errors)))
            for e in errors:
                print("       - " + e)
        else:
            print("[PASS] %s" % name)

    print("\n%d 个文件，%d 处错误" % (len(targets), total_errors))
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
