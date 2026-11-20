"""Read rule evidence by ID from the project rulebook."""

from __future__ import annotations

import json
from pathlib import Path


RULES_PATH = Path(__file__).resolve().parents[2] / "contracts" / "rules.json"


def load_rules(path: Path = RULES_PATH) -> dict[str, dict]:
    entries = json.loads(path.read_text(encoding="utf-8-sig"))["rules"]
    rules = {entry["rule_id"]: entry for entry in entries}
    expected = {f"R{index:02d}" for index in range(1, 21)}
    if set(rules) != expected or len(entries) != len(expected):
        raise ValueError("规则库编号必须完整且唯一（R01–R20）")
    return rules


def lookup_evidence(rule_id: str, rules: dict[str, dict]) -> dict | None:
    rule = rules.get(rule_id.strip().upper())
    if rule is None or not rule.get("clause") or not rule.get("source"):
        return None
    threshold = rule["threshold"]
    return {"clause": rule["clause"], "source": rule["source"],
            "threshold": threshold if isinstance(threshold, str)
            else json.dumps(threshold, ensure_ascii=False, sort_keys=True)}
