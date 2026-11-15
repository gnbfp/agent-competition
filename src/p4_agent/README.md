# P4 Agent 编排 / 后端

**职责**：`metrics.json` → `plan.json` + `report.json`。单 agent + 8 工具 + 一轮自校验。

## 输入 / 输出

- 输入：`metrics.json`、`contracts/rules.json`（20 条规则）、用户追问回答
- 输出：`report.json`（契约见 `contracts/report.schema.json`，**P5 只消费这一个文件**）
- 中间：`plan.json`（`contracts/plan.schema.json`）

## 主循环（必须能演示出来）

```
Plan（列本次应覆盖的风险类型）
  -> Act（按需调工具，不是固定跑一遍）
  -> Observe（逐条记：已判 / 数据不足 / 无依据）
  -> Self-check（R19 负荷增幅、R20 依据覆盖率，不过就打回重排）
  -> 出报告
```

## 8 个工具（工具名与契约枚举一致）

`load_activities` / `compute_load` / `estimate_vo2max` / `check_risk` / `retrieve_evidence` / `ask_athlete` / `generate_plan` / `explain`

## 第一件事（可验收，约 3 天）

先用样例数据把"一条线"跑通：读 `contracts/samples/metrics_sample.json` -> 跑 R01–R18 -> 生成 `plan.json` -> 自检 R19/R20 -> 写出 `report.json`，**并让 `contracts/validate_contract.py` PASS**（它含 C8：report 引用的 rule_id 必须在 evidence 里有依据）。

```bash
python src/p4_agent/run.py contracts/samples/metrics_sample.json -o out/report.json
python contracts/validate_contract.py out/report.json
```

## 三处必须可见的 agent 行为（答辩必看）

1. 缺数据追问（缺睡眠/疼痛就 `ask_athlete`，不硬算）
2. 条款检索无命中时换同义词/上位规则再试，两次失败才标"无依据"
3. 计划生成后自查打回（日志里要能看出"打回了一次"）

## 不要做

- 不要做多 Agent 辩论/投票（一眼假，且五人小队调试不起）
- 不要让 agent 自己编 rule_id 或依据（`contracts/rules.json` 是唯一真源）
- 不要全自动无人值守：R15 疼痛、高危结论必须停下来等人确认
