# P3 指标模块

**职责**：`activity.json` → `metrics.json`（只算指标，不做判断，不写报告文案）。

## 输入 / 输出

- 输入：`activity.json`（契约见 `contracts/activity.schema.json`）
- 输出：`metrics.json`（契约见 `contracts/metrics.schema.json`）
- 黄金样例：`contracts/samples/metrics_sample.json`（必须逐字段对齐，P4 和 P5 都按它开发）

## 计算范围（v1）

| 字段 | 公式 / 口径 | 依据 |
|---|---|---|
| `load.trimp_week` | TRIMP 逐条算完再按周汇总，男女系数不同 | Banister 1991，见 `contracts/rules.json#R04` |
| `load.acwr_rolling` | 近 7 天 / 近 28 天均值 | Gabbett 2016，R05–R07 |
| `load.acwr_ewma` | 指数加权，lambda=2/(N+1) | Williams 2017 |
| `load.acwr_status` | 0.8–1.3 optimal / >1.5 danger / <0.8 undertrained | R05–R07 |
| `capacity.vo2max` | Uth-Sorensen / Riegel / Daniels 三法，差异 >5% 置 consistency_ok=false | R13 |
| `recovery.*` | 静息心率基线（历史中位数）、漂移、睡眠均值 | R11 / R12 / R16 |
| `flags` | 数据问题（缺失、异常、口径不一致） | R01–R03 |

## 第一件事（可验收，约 2 天）

写 `compute.py`：读 `contracts/samples/activity_sample.json`，输出与 `metrics_sample.json` 逐字段相等的 `metrics.json`（浮点允许 +/-0.01）。然后：

```bash
python src/p3_metrics/compute.py contracts/samples/activity_sample.json -o out/metrics.json
python contracts/validate_contract.py out/metrics.json     # 必须 PASS
```

## 不要做

- 不要写报告文案、不要生成训练计划（那是 P4 的活）
- 不要引入 numpy/pandas（零依赖是硬约束）
- 不要把"男生系数"写死在流程里——系数必须来自常量表，并在输出里记录用了哪套

## 依赖

- P2 的 `activity.json` 字段已冻结 v1.0，可以直接开工
- 交给 P4：`metrics.json`；P5 不直接读你，只读 `report.json`
