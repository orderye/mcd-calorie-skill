---
name: mcd-calorie-combo
description: >
  麦当劳订单热量估算与餐段档位套餐推荐。用户问"这单多少热量""300 大卡左右吃什么"
  "想吃轻一点""帮我换个更低的组合"时使用。基于官方 MCP（M-China/mcd-mcp-server）。
  支持 13 个目标场景：减脂、增重、练后餐、放纵餐、低钠控盐、高蛋白增肌、低糖低碳水、
  低脂清淡、素食/蛋奶素、儿童/小份量、热量预算日控、过敏原规避、性价比/省钱。
  不提供医学、减重或疾病相关建议，热量仅为估算参考。
version: 0.8.0
---

# 订单热量与套餐推荐 Skill

把「订单热量 → 餐段档位对比 → 门店可售推荐 → 替换建议 → 报价下单」串成闭环。
本地脚本目录：`scripts/`（无第三方依赖，Python 3.10+）。

## 触发词

- "这单多少热量" / "热量高吗" / "帮我看看这单"
- "300 大卡左右吃什么" / "早餐想吃轻一点" / "别超过 200 大卡"
- "换个低热量的" / "昨天那单偏高，今天来点轻的"
- "吃饱但钠低一点"
- **一键导入历史订单**："导入我的历史订单分析热量" / "把我最近的订单都算一下热量" / "一键分析历史订单卡路里"
- **目标场景**："减脂吃什么" / "想增重/增肌" / "练完吃什么/练后餐" / "今天想放纵一下/随便吃点好的"
  / "想控盐/钠低一点" / "想多吃蛋白" / "低碳水/少糖" / "清淡点/少油" / "吃素/素食"
  / "给孩子点/小份量" / "今天还剩 X 卡能吃" / "花生过敏/不吃奶" / "便宜点/省钱"

## 工具链（MCP）

| 步骤 | 工具 | 说明 |
|---|---|---|
| 当前时间 | `now-time-info` | 餐段判定的时钟 |
| 门店 | `query-nearby-stores` / `delivery-query-addresses` + `delivery-query-stores` | 取 `storeCode`（+`beCode`） |
| 订单 | `query-order`（单号） / `order-list`（历史，无入参） | **字段差异**：order-list 的套餐子项名称字段是 `name`，query-order 是 `productName`，展开时必须兼容两者 |
| 营养表 | `list-nutrition-foods` | **官方 MCP 里唯一的营养数据源**（`query-meals` / `query-meal-detail` / `query-order` 原始响应均无营养字段，2026-10-10 实测）；全量缓存 ≥24h，勿重复拉取；**对当前在售单品覆盖率 44.4%（单品 40/90，实测门店 3570190）**，全量（含套餐）命中 60/179，缺口见 `data/nutrition-gaps.json` |
| 菜单 | `query-meals` | **按餐段取菜单：传 `reservationDate`=目标餐段代表时刻**（接口无 daypart 字段，已实测）；价格随餐段浮动，**必须用当次返回值** |
| 套餐组成 | `query-meal-detail` | `rounds[].name` 只是轮次名、**不是品类**（可能叫「新升级巨无霸」）；品类优先取 `rounds[].category`，该字段可能缺失 → 缺失时按名称反查。`choices[]` 的 `diffPrice` 即换品差价 |
| 换品 vs 特调 | `query-meal-detail` | **换品**在 rounds/choices 层；**特调**看 `supportModify`/`modification`（去冰、换燕麦奶等）。特调传参：含 `unselectedKey` 的组，选中项传 `selectedKey`、未选中项传 `unselectedKey`，两者都要传给报价与下单 |
| 优惠券 | `query-store-coupons` | 只标注，不参与排序 |
| 报价/下单 | `calculate-price` / `create-order` | 金额单位为「分」，÷100 转元；到店下单 `takeWayCode` 取自报价返回 `takeWayList[].code`；**下单必须先展示金额并获用户明确确认** |

## 工作流

### A. 订单热量估算（"这单多少热量？"）

1. 用户无订单号 → 可提示用 `order-list` 查历史订单取单号；仍不便则请其提供，或直接进推荐流程（B）。
2. `query-order(orderId)` → 本地脚本 `scripts/mcd_order.py --order <展开后的订单JSON>`
   （套餐按 `comboItemList` 展开；"加…(加)"加料剥离，热量不计入并告知）。
3. 展示：逐项热量 → 整单合计 → 餐段档位对比结论。
4. 匹配不上的项标 **热量未知**，合计说成 **「≥ N kcal（实际会更高）」**，绝不按 0 算。
5. 名称歧义（可乐/薯条/新地/派等缺规格）→ 列出候选项让用户确认，不要猜。
6. **餐段来源**：订单是历史事实，餐段优先取订单自带（下单时间 / 餐段声明），无则用当前时刻；
   `scripts/mcd_order.py` 提供 `--daypart/--user-daypart/--time` 显式覆盖。

### B. 档位推荐（"想吃 300 大卡左右的早餐"）

1. `now-time-info` → 餐段；用户显式指定（"我想吃早餐"）优先。
2. 门店餐段时段以 `reservationTimeOptions` 实测为准（各店不同，且有宵夜段）。
3. `query-meals(storeCode, orderType, beType, reservationDate=<餐段代表时刻>)` 取该餐段菜单。
4. 本地脚本 `scripts/mcd_combo.py --menu <菜单JSON> --daypart <餐段> --tier <档位> --sort <排序>`。
5. 档位默认值（kcal）：早餐 300/450/600；午餐 500/750/1000；晚餐 500/750/1000；
   **宵夜（单列档，约 22:14 起，跨零点以门店为准）300/450/600**；随便吃吃 150/300/450。
   宵夜组合规则同正餐（1 主食 + 0~1 小食 + 0~1 饮品），候选来自宵夜时段菜单。
6. 展示 Top 3–4 组：总热量/蛋白/脂肪/碳水/钠/参考价；已读订单时附「较本单 ±kcal」。
7. 档位内无解 → 提示换档位，**不放宽 ±12% 筛选**。
8. 排序四选一：最接近档位(near) / 蛋白质更高(protein) / 钠更低(sodium) / 价格更低(price)。

### C. 替换建议（"昨天那单偏高"）

1. `scripts/mcd_replace.py --order ... --menu ...`。
2. 整单 > 该餐段标准档 → 切标准档；否则用最接近的档位。
3. 输出替换组合 + 少多少 kcal + 参考价；价格差在未接真实订单金额前显示"需按实付口径计算"。

### G. 目标场景推荐（"减脂吃什么" / "练完吃什么" / "想控盐"）

在餐段 × 档位之上叠加一个**目标场景（goal）**，各自是一套营养策略。共 13 个场景：

| 场景 | goal | 推荐档位 | 策略要点 | 场景入参 |
|---|---|---|---|---|
| 减脂 | `cut` | 轻量 | 蛋白密度优先 + 钠偏低 + 剔甜品、小食 ≤1 | — |
| 增重 | `bulk` | 吃饱 | 蛋白与碳水双高 + 小食 ≤2、允许甜品 | — |
| 练后餐 | `post` | 标准 | 蛋白总量优先 + 必含主食回补碳水 | — |
| 放纵餐 | `cheat` | 吃饱（容差 ±15%） | 热量上浮 + 允许甜品 + 性价比排序 | — |
| 低钠控盐 | `low-sodium` | 轻量 | 钠硬上限（默认 ≤1000mg）+ 钠升序 | `--sodium-max` |
| 高蛋白增肌 | `high-protein` | 标准 | 蛋白密度优先 + 蛋白总量（日常版） | — |
| 低糖低碳水 | `low-carb` | 轻量 | 碳水硬上限（默认 ≤60g）+ 碳水升序 | `--carb-max` |
| 低脂清淡 | `low-fat` | 轻量 | 脂肪硬上限（默认 ≤30g）+ 脂肪升序 | `--fat-max` |
| 素食/蛋奶素 | `vegetarian` | 轻量 | 关键词排除肉类/水产（蛋奶可食）+ 无主食时拼小食达档 | — |
| 儿童/小份量 | `kids` | 轻量（×0.85） | 热量下浮 + 单组 ≤2 件 | `--max-items` |
| 热量预算日控 | `daily-budget` | 按剩余预算 | 用满预算但不超；区间 [0.7B, B] | `--budget` |
| 过敏原规避 | `allergen` | 标准 | 按过敏原展开关键词排除（粗筛，带告警） | `--allergens` |
| 性价比/省钱 | `value` | 标准 | 价格硬上限 + 价格升序 | `--price-max` |

1. `now-time-info` → 餐段（用户显式指定优先，同 B）。
2. `query-meals(...)` 取该餐段菜单（同 B）。
3. `scripts/mcd_combo.py --menu <菜单> --daypart <餐段> --goal <场景> [场景入参] [--top N]`。
   例：`--goal low-sodium --sodium-max 800`、`--goal daily-budget --budget 600`、
   `--goal allergen --allergens 花生,乳制品`、`--goal value --price-max 30`。
4. 场景会自动切换推荐档位与排序器（如减脂→轻量档 + 蛋白密度排序），无需手动传 `--tier`/`--sort`；显式传参可覆盖。
5. 输出 Top 3–4 组，含总热量/蛋白/脂肪/碳水/钠/参考价，并注明场景策略与生效约束（硬上限/排除项）。
6. **场景入参**：`--sodium-max/--carb-max/--fat-max/--price-max` 传 0 表示关闭该上限；`--budget` 为当日剩余热量预算。
7. **红线不变**：候选仍 100% 来自 query-meals 当前可售；营养表无记录不进入候选；档位内无解提示换档位、不放宽筛选；热量为估算参考，不构成减重/增肌处方。
8. **两处粗筛告警（输出必须带）**：素食与过敏原均基于**名称关键词**，菜单无配料/过敏原表 → 结果不完整，须提示用户以门店配料与员工确认为准。

### D. 一键导入历史订单并分析热量（"导入我的历史订单分析热量"）

1. `order-list`（无入参）→ 取历史订单**原始响应**（含 orderId / storeCode / storeName / beCode 等敏感字段）。
2. `scripts/mcd_import.py --raw <原始响应JSON> [--out <落盘路径>]` → **自动脱敏**（去敏感字段，门店以「门店A/B/C」代称）→ 落盘本地脱敏样本 → 逐单展开套餐 → 匹配营养表 → 计算热量 → 按 `createTime` 推断餐段 → 与标准档对比 → 汇总报告。
3. 输出：热量排行、超标准档的单子、平均热量、未知项占比；对超档订单再接 C 生成更轻方案。加 `--json` 导出可二次处理的结构化报告。
4. **脱敏是硬红线**：原始响应（含敏感字段）绝不落盘；只落盘脱敏后的样本。未知项照旧标「热量未知」，不得按 0 计算。

### D2. 历史订单批量复盘（"我最近都吃了些什么 / 哪天吃重了"）

1. 已有脱敏样本（`data/history-orders.json` / `fixtures/order-list.sample.json`）时，`scripts/mcd_import.py --raw <脱敏样本> --no-deidentify`（或等价的 `scripts/mcd_history.py --path <脱敏样本>`）直接复盘（跳过脱敏）。
2. 逐单：展开套餐 → 匹配营养表 → 合计热量 → 按 `createTime` 推断餐段 → 与标准档对比 → 按期排序并汇总。
3. 输出：热量排行、超标准档的单子、平均热量、未知项占比；对超档订单再接 C 生成更轻方案。
4. 未知项照旧标「热量未知」，不得按 0 计算。

### E. 下单（用户明确要求时）

严格按 `docs/order-flow.md`：查券（只标注）→ `calculate-price` 报价（金额单位为「分」，÷100 转元）→
**展示金额并等待明确确认** → `create-order`（到店取②返回的 `takeWayList[].code` 作 `takeWayCode`）→ 返回支付链接由用户自付。

### F. 全量目录（离线匹配 / 兜底，非实时推荐）

`scripts/mcd_catalog.py` 把多份 `query-meals` 快照聚合成 `data/catalog.json`（商品 / 套餐组成 / 按餐段价格）并导出 `data/nutrition-gaps.json`。
**纪律**：目录只用于匹配与兜底；**推荐候选仍必须取自当次 `query-meals` 实时返回**（价格随餐段浮动，目录价会过期）。

## 输出模板

```
【订单估算】
  ✓ 板烧鸡腿堡        391 kcal｜钠 1041mg
  ✓ 中薯条            289 kcal｜钠 165mg
  ✓ 可乐中杯          147 kcal｜钠 0mg
  整单：827 kcal（午餐·标准档 750 kcal → 落档内，合适）

【推荐 · 早餐 · 轻量】目标 300 kcal
  1. 猪柳麦满分  308 kcal｜蛋白 16g｜钠 781mg｜≈¥14.0
  …
```

## 边界与合规（不可省略）

- 热量为**估算参考**，不提供医学/减重/疾病饮食建议，不给"你应该吃多少"的处方。
- 营养表调用失败或为空 → 只提示稍后重试，**不凭记忆给热量数字**。
- 不使用官方商品图片与商标素材；演示材料标注"模拟"。
- Token 只在 MCP 客户端配置，不写入对话、日志或演示页。
- 下单前必须展示金额并得到用户明确确认；本 Skill 不代付。
- 限流 600 次/分钟：营养表缓存 ≥24h，菜单按 店+餐段 缓存 10min；429 退避重试。

## 本地脚本

```
scripts/mcd_nutrition.py   营养表解析 / 名称归一化 / 四级匹配器（UNKNOWN 保护）
scripts/mcd_daypart.py     餐段时段解析（门店实测 > 固定兜底）+ 档位表
scripts/mcd_goal.py        目标场景策略层（13 场景定义 + 场景评分器 + 硬上限/关键词排除/计划解析）
scripts/mcd_combo.py       品类三级归类 + 组合枚举 + 档位筛选 + 排序 + 场景推荐
scripts/mcd_order.py       订单展开（兼容 productName / name）+ 加料剥离 + 合计与档位对比
scripts/mcd_replace.py     替换建议（标准档触发规则）
scripts/mcd_import.py      一键导入历史订单（order-list 原始响应 → 自动脱敏 → 落盘 → 逐单热量与档位对比）
scripts/mcd_history.py     历史订单批量复盘（已脱敏样本 → 逐单热量与档位对比）
scripts/mcd_catalog.py     全量目录聚合（多快照 → catalog.json / nutrition-gaps.json）
scripts/mcd_spec_evidence.py 菜单规格证据挖掘（套餐默认搭配 → 消解菜单名缺规格的歧义；A 级可补 alias.json#defaults，B/C 级保持歧义）
tools/eval_match.py        匹配率评测（常见订单集 ≥90% 验收）
data/alias.json            别名表 + 有证据默认规格（query-meal-detail isDefault=1）
data/category-rules.json   品类兜底关键词
data/catalog.json          全量目录（179 商品：单品 90 / 套餐 SKU 89；套餐组成详情 90 份已采，见 comboDetails）
data/nutrition-gaps.json   营养缺口：未收录单品 + 规格歧义（UNKNOWN 兜底白名单）
                           含 `origin=history-order` 条目（历史订单里的已下架/限定品）
fixtures/                  实测快照（营养表/菜单×4餐段/套餐详情×90/订单样本/脱敏历史订单）
docs/                      nutrition-schema / store-chain / order-flow / catalog-collection
```
