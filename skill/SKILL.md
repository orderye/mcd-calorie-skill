---
name: mcd-calorie-combo
description: >
  麦当劳订单热量估算与餐段档位套餐推荐。用户问"这单多少热量""300 大卡左右吃什么"
  "想吃轻一点""帮我换个更低的组合"时使用。基于官方 MCP（M-China/mcd-mcp-server）。
  不提供医学、减重或疾病相关建议，热量仅为估算参考。
version: 0.1.0
---

# 订单热量与套餐推荐 Skill

把「订单热量 → 餐段档位对比 → 门店可售推荐 → 替换建议 → 报价下单」串成闭环。
本地脚本目录：`scripts/`（无第三方依赖，Python 3.10+）。

## 触发词

- "这单多少热量" / "热量高吗" / "帮我看看这单"
- "300 大卡左右吃什么" / "早餐想吃轻一点" / "别超过 200 大卡"
- "换个低热量的" / "昨天那单偏高，今天来点轻的"
- "吃饱但钠低一点"

## 工具链（MCP）

| 步骤 | 工具 | 说明 |
|---|---|---|
| 当前时间 | `now-time-info` | 餐段判定的时钟 |
| 门店 | `query-nearby-stores` / `delivery-query-addresses` + `delivery-query-stores` | 取 `storeCode`（+`beCode`） |
| 订单 | `query-order` | 按 orderId；无列表接口，用户须提供单号 |
| 营养表 | `list-nutrition-foods` | 全量缓存 ≥24h，勿重复拉取 |
| 菜单 | `query-meals` | **按餐段取菜单：传 `reservationDate`=目标餐段代表时刻**（接口无 daypart 字段，已实测） |
| 套餐组成 | `query-meal-detail` | rounds 名称即品类；默认项 `isDefault=1` |
| 优惠券 | `query-store-coupons` | 只标注，不参与排序 |
| 报价/下单 | `calculate-price` / `create-order` | **下单必须先展示金额并获用户明确确认** |

## 工作流

### A. 订单热量估算（"这单多少热量？"）

1. 用户无订单号 → 说明历史订单无法列出，请其提供，或直接进推荐流程（B）。
2. `query-order(orderId)` → 本地脚本 `scripts/mcd_order.py --order <展开后的订单JSON>`
   （套餐按 `comboItemList` 展开；"加…(加)"加料剥离，热量不计入并告知）。
3. 展示：逐项热量 → 整单合计 → 餐段档位对比结论。
4. 匹配不上的项标 **热量未知**，合计说成 **「≥ N kcal（实际会更高）」**，绝不按 0 算。
5. 名称歧义（可乐/薯条/新地/派等缺规格）→ 列出候选项让用户确认，不要猜。

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

### D. 下单（用户明确要求时）

严格按 `docs/order-flow.md`：查券（只标注）→ `calculate-price` 报价 →
**展示金额并等待明确确认** → `create-order` → 返回支付链接由用户自付。

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
scripts/mcd_combo.py       品类三级归类 + 组合枚举 + ±12% 筛选 + 四种排序
scripts/mcd_order.py       订单展开 + 加料剥离 + 合计与档位对比
scripts/mcd_replace.py     替换建议（标准档触发规则）
tools/eval_match.py        匹配率评测（常见订单集 ≥90% 验收）
data/alias.json            别名表 + 有证据默认规格（query-meal-detail isDefault=1）
data/category-rules.json   品类兜底关键词
fixtures/                  实测快照（营养表/菜单×2餐段/套餐详情/订单样本）
docs/                      nutrition-schema / store-chain / order-flow
```
