# P3 指标模块

P3 从 `activity.json` 计算指标。节点 04 交付可独立运行的训练负荷计算，默认输出 `out/load_metrics.json`。节点 05 将加入有氧能力和恢复指标，再组成正式的 `metrics.json`。

## 运行训练负荷计算

下面的心率和覆盖起始日为演示参数。使用实际活动时，传入该跑者的静息心率、个人最大心率、TRIMP 系数和确认导出完整的日期范围。

```bash
python src/p3_metrics/compute.py contracts/samples/activity_sample.json --as-of 2026-11-14 --history-start 2026-11-08 --trimp-profile female --resting-hr 52 --max-hr 190
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

## 验收

```bash
python -m unittest discover -s tests -p test_training_load.py
```

现有 `activity_sample.json` 只有两条活动，`metrics_sample.json` 是接口示意，两者不能作为同一输入输出对。上述演示会输出两条活动的 TRIMP 和周总量，ACWR 因缺少完整 28 日历史而保留 `null`。负荷单测另用可手算的 28 日样例验证两种 ACWR。正式指标契约当前还有必填的能力、恢复字段，且限制两种 ACWR 的差异。本节点保留中间结果，节点 05 需先明确正式契约如何表达这些缺失及差异。
