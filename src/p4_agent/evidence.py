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


EVIDENCE_ALIASES = {
    "膝痛": "R15", "膝盖疼": "R15", "疼痛": "R15",
    "睡眠": "R16", "连续少睡": "R16",
    "静息心率": "R11", "心率漂移": "R12",
    "赛前": "R18", "跑量增幅": "R08",
}


def retrieve_evidence(query: str, rules: dict[str, dict]) -> dict:
    """Try the exact ID, then unambiguous titles and explicit synonyms."""
    exact_id = query.strip().upper()
    initial = lookup_evidence(exact_id, rules)
    attempts = [{"strategy": "rule_id", "status": "found" if initial else "miss"}]
    if initial:
        return {"rule_id": exact_id, "evidence": initial, "attempts": attempts}

    name = "".join(query.casefold().split())
    title_ids = {rule_id for rule_id, rule in rules.items()
                 if "".join(rule["title"].casefold().split()) == name}
    if name in EVIDENCE_ALIASES:
        title_ids.add(EVIDENCE_ALIASES[name])
    matched = next(iter(title_ids)) if len(title_ids) == 1 else None
    alternative = lookup_evidence(matched, rules) if matched else None
    attempts.append({"strategy": "title_or_alias", "status": "found" if alternative else "miss"})
    return {"rule_id": matched if alternative else None, "evidence": alternative, "attempts": attempts}
