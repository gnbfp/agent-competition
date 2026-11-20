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

## 节点 06：风控信号与依据查询

用指标 v2 和模拟补充信息执行规则判断。活动文件和补充信息可省略，无证据的规则会标记为待补。

```bash
python -m src.p4_agent.risk_rules evaluate contracts/samples/metrics_v2_sample.json --activities contracts/samples/activity_sample.json --context data/sample/risk_context_sample.json
python -m src.p4_agent.risk_rules evidence R15
python -m unittest discover -s tests -p test_risk_rules.py
```

也可直接运行 `python src/p4_agent/risk_rules.py evidence R15`。两个入口接受相同的命令和参数。

结果写入 `out/risk_checks.json`。`checks` 按编号列出 R01–R18 的观测值、缺失数据和规则原文出处。判断状态是 `triggered`、`not_triggered` 或 `insufficient_data`。R04 是 P3 的计算规则，在这里记为 `not_applicable`，并携带实际 TRIMP 参数。`risks` 仅收录命中的检查，字段与现有报告的风险条目一致。

补充信息可参照模拟文件，实际文件放在本地 `data/raw/`。所有文件的 `athlete_id` 必须一致。

| 补充字段 | 用途 |
|---|---|
| `import_quality.incomplete_rows` / `device_anomaly_rows` | 从本次导入明细核对的缺字段和异常旁路计数，确认无异常才填写 0。 |
| `max_hr_source` | `estimated_220_age`、`measured` 或 `race`。 |
| `session_types` | 日期到训练类型列表的映射。已确认休息可用空列表，未知日期留空。 |
| `pain_reported` | 用户明确确认是否有疼痛。任何最近 7 天活动中的疼痛记录仍会要求复核，输出只保留是否报告过。 |
| `environment` / `target_race_date` | 计划地点的气温、相对湿度及目标赛事日期。可缺省。 |

规则使用指标截止日做快照。R05–R07 读取可分档的 EWMA ACWR。R08 比较截至当日 7 天的实际跑步距离与此前 4 个完整 7 天区间的平均跑量。R10 以本周最长单次跑步除以本周总公里数。R08 和 R10 需要覆盖期声明与足够的活动记录，已知有丢弃或旁路时暂不判断。R14 只对比本周与四周前同一日期且配速相近的跑步。R11 和 R16 分别检查截至当日的连续三天静息心率、连续两天睡眠。

`planning_gate` 给下一节点使用。高级别信号进入人工复核。疼痛证据不足时先确认；无暂停信号也只表示本次检查的结果。项目 ACWR 阈值用于标记负荷变化，后续安排需要结合更多观测由人确认。关于 ACWR 的局限，见 [运动负荷方法学研究](https://pubmed.ncbi.nlm.nih.gov/32502973/)。

## 后续主循环与报告

节点 07 将把规则结果接入工具编排和补问流程。节点 08 整合计划、自检和正式报告，报告引用的规则 ID 要能回查现有规则库。

## 三处必须可见的 agent 行为（答辩必看）

1. 缺数据追问（缺睡眠/疼痛就 `ask_athlete`，不硬算）
2. 条款检索无命中时换同义词/上位规则再试，两次失败才标"无依据"
3. 计划生成后自查打回（日志里要能看出"打回了一次"）

## 不要做

- 不要做多 Agent 辩论/投票（一眼假，且五人小队调试不起）
- 不要让 agent 自己编 rule_id 或依据（`contracts/rules.json` 是唯一真源）
- 不要全自动无人值守：R15 疼痛、高危结论必须停下来等人确认
