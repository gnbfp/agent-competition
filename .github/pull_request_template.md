## 这个 PR 做了什么

<!-- 一句话说清，例：P2 解析器支持 .fit 导出并产出符合 activity.schema.json 的 JSON -->

## 四项自检（缺一项不合并）

- [ ] **1. 契约改动**：无 / 改了 `字段名`（改了要写清影响 P2/P3/P4/P5 哪几方）
- [ ] **2. 校验跑过**：把 `check_env.py` 与 `validate_contract.py` 的输出贴到下面的代码块
- [ ] **3. 界面改动截图**：有界面改动必须贴图；没有就写"无"
- [ ] **4. AI 留痕**：含 AI 生成代码时，链接到 `docs/AI使用留痕.md` 的对应行

### 命令输出

```
（粘贴 python tools/check_env.py 与 python contracts/validate_contract.py 的结果）
```

### 截图 / 说明

<!-- 界面改动放这里；纯逻辑改动写清如何手工验证 -->

---

## 审查人检查（reviewer 打勾，全绿才点 Merge）

- [ ] 没有绕过契约：字段名、单位、枚举与 `contracts/*.schema.json` 一致
- [ ] 没有重复实现别人的算法（同类指标只在 P3 算一次）
- [ ] 边界与异常处理到位（空数据、缺失值、非法值）
- [ ] 我能读懂这段代码；有疑问已当场问过
- [ ] 直推 `main` 的提交未被夹带（`git log main --not origin/main` 为空）
