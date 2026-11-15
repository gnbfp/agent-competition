# CHANGELOG —— 契约变更台账

格式：`版本 | 日期 | 变更人 | 变更内容 | 影响方`
规则：只加可选字段升小版本；改类型 / 改单位 / 删字段 / 改必填升大版本，并在阶段交界处合并。

## v1.0 — 2026-11-15 — P4（初始化）

- 首次冻结：`activity` / `metrics` / `plan` / `report` 四份 schema + 黄金样例。
- 跨字段校验 8 条（C1–C8）：activity_id 唯一、max_hr ≥ avg_hr、配速互算、ACWR 双口径、
  VO₂max 三法一致性、计划日期与休息日、每天必须挂 rule_id、依据链完整性。
- 提供 `validate_contract.py`（标准库）与 `mock_api.py`（假后端）。
- 影响方：P2 / P3 / P4 / P5 全体。

## 待定变更（讨论中，未合并）

- 是否在 `report.json` 增加 `week_index`（用于历史报告列表分页）——等 P5 确认是否需要。
