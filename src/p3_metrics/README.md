# P3 指标模块

P3 从 `activity.json` 和可选的补充量测计算训练负荷、有氧能力与恢复指标，默认生成 `out/metrics.json`（契约 v2.0）。如需仅运行训练负荷计算，使用 `--load-only`，默认生成 `out/load_metrics.json`。

## 运行指标计算

下面的量测、心率和覆盖起始日都是演示参数。使用实际活动时，传入该跑者的静息心率、个人最大心率、TRIMP 系数和确认导出完整的日期范围。

```bash
python src/p3_metrics/compute.py contracts/samples/activity_sample.json --measurements data/sample/measurements_sample.json --as-of 2026-11-14 --history-start 2026-11-08 --trimp-profile female --resting-hr 55 --max-hr 183
python contracts/validate_contract.py out/metrics.json
```

输出包含个人计算参数、纳入计算的逐条 TRIMP、28 日序列、周负荷、上周环比和两种 ACWR。截止日包含当天，未来活动排除。已确认覆盖的日期没有活动时计零，未确认的空白日保留 `null`。日期有无法计算的活动时，即使当天另有有效活动，全天负荷也保留 `null`。

## 计算口径

| 指标 | 口径 |
|---|---|
| TRIMP | R04 的心率储备模型，逐条按活动时长和平均心率计算，再按日期汇总。两套系数及所用心率参数写入 `load_inputs`。 |
| 滚动 ACWR | 最近 7 日日均 TRIMP ÷ 最近 28 日日均 TRIMP。 |
| EWMA ACWR | 两个平滑序列都从窗口首日负荷开始处理 28 天数据，短期和长期使用不同的平滑系数 `2/(N+1)`，其中 N 分别为 7 和 28。最后用短期值除以长期值。 |
| 负荷分档 | 依据 R05、R06 的边界，使用 EWMA 值。差异超过 1.0 时保留两种比值，标记 `ACWR_METHOD_GAP`，暂不分档。 |
| 缺失与零值 | 需要的日期不足或分母为零时，指标为 `null`，在 `flags` 中给出原因。周环比需要两个完整的 7 日窗口。 |

公式依据见 [TRIMP 研究](https://journals.physiology.org/doi/full/10.1152/japplphysiol.00482.2003) 和 [Williams 等人的 EWMA 方法说明](https://doi.org/10.1136/bjsports-2016-096589)。窗首初始化与缺失处理是本项目为保证复算而选定的实现口径。

## 补充量测与个体指标

模拟量测的结构见 `data/sample/measurements_sample.json`。实际文件放在本地 `data/raw/`，其 `athlete_id` 必须和活动一致。

计算用静息心率范围读取 `contracts/rules.json` 的 R02。记录层能保留历史或需复核的日量测，统计时会排除超出 R02 范围的读数，并给出 `RESTING_HR_REVIEW` 标记。当前 R02 范围是 30–110 bpm，属于项目数据复核口径。

| 输入 | 计算及缺失处理 |
|---|---|
| 心率参数 | 用个人最大与静息心率的比值得到 Uth–Sørensen 估算。依据见 [Uth 等人的原研究](https://pure.au.dk/portal/en/publications/estimation-of-vo2max-from-the-ratio-between-hrmax-and-hrrest-the-/)。 |
| 28 日内的 `race` | Daniels 路径用给定赛绩计算 VDOT。Riegel 路径用项目选定的 1.06 指数外推到 5 km，原赛事恰为 5 km 时则外推到 10 km，再用同一 VDOT 公式换算。两条赛绩路径共享输入和换算模型。依据见 [Riegel 原文](https://www.jstor.org/stable/27850427) 和 [Daniels 与 Gilbert 原著](https://www.vivamarathon.com/oxygenpower.pdf)。 |
| 估算范围 | 取可用结果的最小值与最大值。集齐三条结果才能按 R13 比较。差异超过 5% 时保留范围，点估值为空。满足一致性时，点估值采用 Uth–Sørensen。范围表示方法间差异。 |
| 按日期的 `daily` | 以截止日前、28 日窗口内至少 7 天的静息心率中位数为基线，用截止日的测量计算偏差。RMSSD 直接读取截止日的实测毫秒值。 |
| 睡眠 | 最近 7 天按日期取有效记录均值，同时输出记录天数。优先使用 `daily` 的测量，活动中的同日相同值只计一次，同日冲突且没有补充量测时该日留空。 |
| 28 日内的 `steady_run` | 两段配速相差不超过前段的 5% 时，用后段与前段平均心率的相对变化计算漂移，单位为百分数。两段心率及配速随结果保留。 |

缺少补充数据时会继续生成指标文件。各项空值都有相应的数据质量标记，供后续规则判断和追问。

## 验收

```bash
python -m unittest discover -s tests
```

`contracts/samples/metrics_v2_sample.json` 由上述命令生成。它有两条活动，ACWR 因缺少完整 28 日历史而保留 `null`。负荷单测另用可手算的 28 日样例验证两种 ACWR。
