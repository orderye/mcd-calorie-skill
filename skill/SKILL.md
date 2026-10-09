---
name: mcd-calorie-combo
description: >
  麦当劳订单热量估算与餐段档位套餐推荐。用户问"这单多少热量""300 大卡左右吃什么"
  "想吃轻一点""帮我换个更低的组合"时使用。基于官方 MCP（M-China/mcd-mcp-server）。
  支持目标场景：减脂、增重、练后餐、放纵餐。
  不提供医学、减重或疾病相关建议，热量仅为估算参考。
version: 0.3.0
---

# 订单热量与套餐推荐 Skill

把「订单热量 → 餐段档位对比 → 门店可售推荐 → 替换建议 → 报价下单」串成闭环。
本地脚本目录：`scripts/`（无第三方依赖，Python 3.10+）。

## 触发词

- "这单多少热量" / "热量高吗" / "帮我看看这单"
- "300 大卡左右吃什么" / "早餐想吃轻一点" / "别超过 200 大卡"
- "换个低热量的" / "昨天那单偏高，今天来点轻的"
- "吃饱但钠低一点"
- **目标场景**："减脂吃什么" / "想增重/增肌" / "练完吃什么/练后餐" / "今天想放纵一下/随便吃点好的"

## 工具链（MCP）

| 步骤 | 工具 | 说明 |
|---|---|---|
| 当前时间 | `now-time-info` | 餐段判定的时钟 |
| 门店 | `query-nearby-stores` / `delivery-query-addresses` + `delivery-query-stores` | 取 `storeCode`（+`beCode`） |
| 订单 | `query-order`（单号） / `order-list`（历史，无入参） | **字段差异**：order-list 的套餐子项名称字段是 `name`，query-order 是 `productName`，展开时必须兼容两者 |
| 营养表 | `list-nutrition-foods` | 全量缓存 ≥24h，勿重复拉取；**对当前在售单品覆盖率约 44%**（实测），缺口见 `data/nutrition-gaps.json` |
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

### G. 目标场景推荐（"减脂吃什么" / "练完吃什么"）

在餐段 × 档位之上叠加一个**目标场景（goal）**，各自是一套营养策略。四个场景：

| 场景 | goal | 推荐档位 | 目标热量 | 策略要点 |
|---|---|---|---|---|
| 减脂 | `cut` | 轻量 | 该餐段轻量档 | 蛋白密度优先 + 钠偏低 + 剔甜品、小食 ≤1 |
| 增重 | `bulk` | 吃饱 | 该餐段吃饱档 | 蛋白与碳水双高 + 小食 ≤2、允许甜品 |
| 练后餐 | `post` | 标准 | 该餐段标准档 | 蛋白总量优先 + 必含主食回补碳水 |
| 放纵餐 | `cheat` | 吃饱 | 该餐段吃饱档（容差 ±15%） | 热量上浮 + 允许甜品 + 性价比排序 |

1. `now-time-info` → 餐段（用户显式指定优先，同 B）。
2. `query-meals(...)` 取该餐段菜单（同 B）。
3. `scripts/mcd_combo.py --menu <菜单> --daypart <餐段> --goal <cut|bulk|post|cheat> [--top N]`。
4. 场景会自动切换推荐档位与排序器（如减脂→轻量档 + 蛋白密度排序），无需手动传 `--tier`/`--sort`；显式传参可覆盖。
5. 输出 Top 3–4 组，含总热量/蛋白/脂肪/碳水/钠/参考价，并注明场景策略一句话说明。
6. **红线不变**：候选仍 100% 来自 query-meals 当前可售；营养表无记录不进入候选；档位内无解提示换档位、不放宽筛选；热量为估算参考，不构成减重/增肌处方。

### D. 历史订单批量复盘（"我最近都吃了些什么 / 哪天吃重了"）

1. `order-list`（无入参）→ 取订单列表；**落盘前必须脱敏**（去 orderId / storeCode / storeName / beCode）。
2. `scripts/mcd_history.py --path <脱敏样本>` → 逐单：展开套餐 → 匹配营养表 → 合计热量 → 按 `createTime` 推断餐段 → 与标准档对比 → 按期排序并汇总。
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
scripts/mcd_goal.py        目标场景策略层（减脂/增重/练后餐/放纵餐 + 场景评分器）
scripts/mcd_combo.py       品类三级归类 + 组合枚举 + ±12% 筛选 + 四种排序 + 场景推荐
scripts/mcd_order.py       订单展开（兼容 productName / name）+ 加料剥离 + 合计与档位对比
scripts/mcd_replace.py     替换建议（标准档触发规则）
scripts/mcd_history.py     历史订单批量复盘（order-list → 逐单热量与档位对比）
scripts/mcd_catalog.py     全量目录聚合（多快照 → catalog.json / nutrition-gaps.json）
tools/eval_match.py        匹配率评测（常见订单集 ≥90% 验收）
data/alias.json            别名表 + 有证据默认规格（query-meal-detail isDefault=1）
data/category-rules.json   品类兜底关键词
data/catalog.json          全量目录（179 商品 / 89 套餐，按餐段价格）
data/nutrition-gaps.json   营养缺口：未收录单品 + 规格歧义（UNKNOWN 兜底白名单）
                           含 `origin=history-order` 条目（历史订单里的已下架/限定品）
fixtures/                  实测快照（营养表/菜单×3餐段/套餐详情/订单样本/脱敏历史订单）
docs/                      nutrition-schema / store-chain / order-flow / catalog-collection
```
