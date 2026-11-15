#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""规则库自检：校验 contracts/rules.json 的结构，并检查样例数据引用的 rule_id 是否都存在。

只做静态检查，不跑业务逻辑。用法：
    python tools/check_rules.py            # 全量检查
    python tools/check_rules.py -v         # 打印每条规则的标题与等级

退出码：0 全通过；1 有 FAIL。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "contracts" / "rules.json"
SAMPLES_DIR = ROOT / "contracts" / "samples"

REQUIRED_KEYS = [
    "rule_id", "title", "kind", "category", "level", "trigger",
    "metric", "operator", "threshold", "clause", "source", "action",
    "evidence_required",
]
PLACEHOLDERS = ("TODO", "待补", "待定", "占位", "xxx", "XXX", "？？")
RULE_ID_RE = re.compile(r"^R\d{2}$")

results: list[tuple[str, str, str]] = []  # (level, name, detail)


def add(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))


def check_structure(doc: dict) -> list[dict]:
    if doc.get("schema_version") != "1.0":
        add("FAIL", "schema_version", f"期望 1.0，实际 {doc.get('schema_version')!r}")
    rules = doc.get("rules")
    if not isinstance(rules, list):
        add("FAIL", "rules", "rules 必须是数组")
        return []
    add("PASS" if len(rules) == 20 else "FAIL", "规则条数", f"{len(rules)} 条（标准是 20 条）")

    levels = set(doc.get("levels") or [])
    categories = set(doc.get("categories") or [])
    kinds = set(doc.get("kinds") or [])

    seen: dict[str, int] = {}
    expected_ids = [f"R{i:02d}" for i in range(1, 21)]

    for index, rule in enumerate(rules):
        rid = rule.get("rule_id", f"<第{index + 1}条>")
        missing = [k for k in REQUIRED_KEYS if k not in rule]
        if missing:
            add("FAIL", f"{rid} 字段缺失", ", ".join(missing))
            continue
        seen[rid] = seen.get(rid, 0) + 1

        if not RULE_ID_RE.match(rid):
            add("FAIL", f"{rid} 编号格式", "必须形如 R01")
        if rule["kind"] not in kinds:
            add("FAIL", f"{rid} kind", f"{rule['kind']!r} 不在 {sorted(kinds)}")
        if rule["category"] not in categories:
            add("FAIL", f"{rid} category", f"{rule['category']!r} 不在 {sorted(categories)}")

        if rule["kind"] == "risk":
            if rule["level"] not in levels:
                add("FAIL", f"{rid} level", f"risk 类必须有 level，实际 {rule['level']!r}")
        else:
            if rule["level"] is not None:
                add("WARN", f"{rid} level", f"{rule['kind']} 类不需要 level，建议置 null")

        for key in ("title", "trigger", "clause", "source", "action", "metric", "operator"):
            value = rule.get(key)
            if not isinstance(value, str) or not value.strip():
                add("FAIL", f"{rid}.{key}", "不能为空")
            elif any(p in value for p in PLACEHOLDERS):
                add("FAIL", f"{rid}.{key}", f"含占位内容：{value[:30]}")

        evidence = rule.get("evidence_required")
        if not isinstance(evidence, list) or not evidence:
            add("FAIL", f"{rid} evidence_required", "至少要一条证据要求")
        elif any((not isinstance(x, str)) or not x.strip() for x in evidence):
            add("FAIL", f"{rid} evidence_required", "存在空项")

        if rule.get("threshold") is None:
            add("FAIL", f"{rid}.threshold", "不能为空")

    dups = [rid for rid, count in seen.items() if count > 1]
    if dups:
        add("FAIL", "rule_id 唯一", f"重复：{', '.join(sorted(dups))}")
    else:
        add("PASS", "rule_id 唯一", f"{len(seen)} 个")

    ordered = [r.get("rule_id") for r in rules if isinstance(r, dict)]
    if ordered != expected_ids:
        add("FAIL", "编号连续", "应为 R01–R20 顺序排列")
    else:
        add("PASS", "编号连续", "R01–R20")

    if "R15" in seen:
        r15 = next(r for r in rules if r.get("rule_id") == "R15")
        ok = r15.get("level") == "high"
        add("PASS" if ok else "FAIL", "R15 疼痛优先级", f"level={r15.get('level')}（必须 high）")

    return rules


def collect_sample_ids() -> dict[str, list[str]]:
    """从黄金样例里收集被引用的 rule_id：{来源文件: [rule_id, ...]}"""
    found: dict[str, list[str]] = {}
    plan_sample = SAMPLES_DIR / "plan_sample.json"
    report_sample = SAMPLES_DIR / "report_sample.json"

    if plan_sample.exists():
        plan = json.loads(plan_sample.read_text(encoding="utf-8"))
        ids = [rid for day in plan.get("days", []) for rid in day.get("rules", [])]
        found["plan_sample.json"] = ids

    if report_sample.exists():
        report = json.loads(report_sample.read_text(encoding="utf-8"))
        ids = [r.get("rule_id", "") for r in report.get("risks", [])]
        ids += [e.get("rule_id", "") for e in report.get("evidence", [])]
        found["report_sample.json"] = [i for i in ids if i]
    return found


def check_references(rules: list[dict]) -> None:
    known = {r.get("rule_id") for r in rules if isinstance(r, dict)}
    found = collect_sample_ids()
    if not found:
        add("WARN", "样例引用", "没找到 plan/report 样例，跳过引用检查")
        return
    unknown: list[str] = []
    for source, ids in found.items():
        bad = sorted({i for i in ids if i not in known})
        unknown += bad
        add("PASS" if not bad else "FAIL", f"{source} 引用合法性",
            f"{len(set(ids))} 个 rule_id" + (f"，未定义：{', '.join(bad)}" if bad else ""))
    if not unknown:
        used = {i for ids in found.values() for i in ids}
        unused = sorted(known - used)
        if unused:
            add("WARN", "未被样例引用", ", ".join(unused) + "（样例只覆盖常用规则，可接受）")


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 contracts/rules.json")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印每条规则")
    args = parser.parse_args()

    if not RULES_PATH.exists():
        print(f"FAIL 找不到 {RULES_PATH}")
        return 1

    try:
        doc = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"FAIL rules.json 不是合法 JSON：{exc}")
        return 1

    add("PASS", "JSON 解析", str(RULES_PATH.name))
    rules = check_structure(doc)
    check_references(rules)

    width = max(len(name) for _, name, _ in results)
    for status, name, detail in results:
        mark = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[status]
        print(f"{mark} {name.ljust(width)}  {detail}")

    if args.verbose:
        print("\n规则清单：")
        for rule in rules:
            level = rule.get("level") or "-"
            print(f"  {rule['rule_id']}  {level:<7} {rule.get('title', '')}")

    count = {s: sum(1 for x, _, _ in results if x == s) for s in ("PASS", "WARN", "FAIL")}
    print("-" * 60)
    print(f"结果：{count['PASS']} PASS / {count['WARN']} WARN / {count['FAIL']} FAIL")
    failed = count["FAIL"] > 0
    print("结论：规则库可用。" if not failed else "结论：规则库还有问题，先修 FAIL。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
