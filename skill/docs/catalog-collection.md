# 全量产品与套餐内容：来源、采集矩阵与实测结论

> 更新时间 2026-10-10 00:40（实测环境：门店 3570190 贵阳天一国际餐厅，到店自取 beType=1）。
> 关联：PRD §5 接口映射、§12 待确认问题；脚本 `scripts/mcd_catalog.py`。

## 1. 为什么「全量」要聚合

官方**没有**「全量目录」接口。`query-meals` 的维度是三者交叉：

```
门店(storeCode) × 渠道(orderType/beType) × 餐段(reservationDate)
```

每次返回「该门店该餐段当前可售」的菜单，所以：

- **同一门店不同餐段菜单完全不同**。实测同一门店：早餐快照 92 项 / 11 个分类，午餐快照 110 项 / 15 个分类，夜市快照 110 项 / 15 个分类；早餐与夜市「分类、编码均不同」。
- **同一门店不同渠道菜单不同**：到店自取 `beType=1 orderType=1`（不传 beCode）；得来速 `beType=5`（必传 beCode）；麦乐送 `beType=2 orderType=2`；团餐 `beType=6 orderType=2`。
- **地区/门店限定**：新品与季节品按门店铺货，全国「全量」需要多城市多门店采样才可能逼近。

结论：全量 = **多份快照的去重聚合**，不是一次调用。

## 2. 三个数据源

| 需求 | 接口 | 说明 |
|---|---|---|
| 商品名录与价格 | `query-meals` | 返回 `categories[]`（分类 → code + tags）与 `meals{}`（code → name / price / originalPrice / discountType / canWithOrder / **image**） |
| **套餐内容** | `query-meal-detail` | 返回 `rounds[]`，每 round 有 `name`（权威品类名：主食 / 小食 / 饮料）、`category`、`choices[]`（code / name / isDefault / diffPrice / supportModify） |
| 营养值 | `list-nutrition-foods` | 单品维度快照（当前 160 项），套餐不在此表内 |

### 套餐内容的匹配注意

- `rounds[].name` 是**权威品类来源**（优于名称关键词推断）。
- 套餐子项 `code` 与 `query-meals` 菜单 `code` **不一致**（例：套餐内「可乐中杯 3050」vs 菜单「可乐 9900008751」）→ 必须**按名称匹配**，不能按 code 关联。
- `diffPrice` 是相对套餐基准价的差价，可直接用于「换单品后的价格」估算，但 PRD 当前不做套餐内换品。

## 3. 采集矩阵（照此跑即可）

```json
{
  "query-meals": [
    {"storeCode": "<storeCode>", "orderType": 1, "beType": 1, "reservationDate": "<今天> 08:00"},
    {"storeCode": "<storeCode>", "orderType": 1, "beType": 1, "reservationDate": "<今天> 12:00"},
    {"storeCode": "<storeCode>", "orderType": 1, "beType": 1, "reservationDate": "<今天> 16:00"},
    {"storeCode": "<storeCode>", "orderType": 1, "beType": 1, "reservationDate": "<今天> 19:00"},
    {"storeCode": "<storeCode>", "orderType": 1, "beType": 1, "reservationDate": "<今天> 23:00"}
  ],
  "query-meals-delivery": [{"orderType": 2, "beType": 2, "beCode": "<delivery-query-stores 返回>"}],
  "query-meals-dt":       [{"orderType": 1, "beType": 5, "beCode": "<query-nearby-stores(beType=5) 返回>"}],
  "query-meal-detail":    [{"code": "<每个套餐 code，逐个调用>"}],
  "list-nutrition-foods": []
}
```

- 限速：每个 Token **600 次/分钟**，超限 429。批量跑建议 ≤60 次/分钟，并做断点续跑。
- 只有 `query-meals` 的非预约调用不必传 `reservationDate`；传了就等于切到该餐段。
- **套餐数决定调用量**：本次聚合出 89 个套餐 → 补齐全部套餐组成需要 89 次 `query-meal-detail`。

## 4. 落盘约定（沿用现有 fixtures 习惯）

```
fixtures/meals.<storeCode>.<orderType>.<daypart>.json    # 菜单快照
fixtures/meal-detail.<code>.json                         # 套餐组成
```

- **剔除 `image` 字段后再入库**（合规：不使用官方商品图片素材）。
- `_meta` 记录 storeCode / orderType / beType / reservationDate / fetchedAt / serverDaypart / traceId，便于复现。
- 原始响应用 `currentPrice`，精简样本用 `price`；聚合脚本两种都能吃。

## 5. 本次实测结论

```
快照数         : 3（早餐 / 午餐 / 夜市）
商品总数(去重) : 179   其中 套餐 89 / 单品 90
营养表覆盖     : 全部 60 命中 / 13 歧义 / 106 未知（33.5%）
  单品         : 命中 40 / 歧义 13 / 未知 37  → 44.4%
  套餐         : 命中 20 / 未知 69            → 22.5%（套餐名本就不在营养表，属预期）
跨餐段价格差异 : 6 个商品同 code 不同价
  例：麦咖啡™奶铁 早餐 13.9 / 午餐 9.9；马苏里拉拉丝芝士条 午餐 16 / 夜市 11
悬空引用       : 1 条 —— 夜市快照分类引用的 code 9900000881 未出现在该响应 meals 映射中
```

**三条对项目有直接影响的发现：**

1. **价格随餐段浮动**。同一 code 在早餐/午餐/夜市价格不同（麦咖啡系列、部分小食）。若聊天中报价或做「更低价格」排序，必须用**当次快照**的价格，不能用固定目录价。
2. **营养表对「当前在售单品」的覆盖率只有约 44%**。未命中的多是新品/季节品（北非蛋风味系列、BTS 联名、举杯邀月柚桂茶、美汁源系列等）。这正是 PRD §7「匹配不上标热量未知」的现实比例，也说明 `alias.json` 值得按「当前在售清单」补一轮。
3. **存在悬空引用**：`query-meals` 的分类里可能出现 `meals{}` 里查不到的 code。脚本会把它计入 `danglingRefs`，调用侧必须仍然按「热浪未知」兜底，不能假设映射完整。

## 6. 脚本用法

```bash
python3 scripts/mcd_catalog.py            # 聚合 fixtures → data/catalog.json，并打印报告
python3 scripts/mcd_catalog.py --calls    # 只打印采集矩阵（要跑哪些调用）
python3 scripts/mcd_catalog.py --out X    # 指定输出路径
```

产物 `data/catalog.json`：

```
_meta        来源文件、生成时间、各餐段对应快照
stores       storeCode → 门店名 / 覆盖餐段 / 分类名
products     code → name / dayparts / categories / tags / prices(按餐段) / isCombo / hasImage
comboDetails code → rounds[].choices[]（套餐组成）
stats        商品数、套餐数、营养表覆盖、跨餐段价差、悬空引用
```

**使用纪律**：目录用于「匹配、兜底、离线演示」；**推荐候选仍必须取自当次 `query-meals` 的实时返回**（PRD F3 / §9：所有推荐商品都来自当前可售结果）。

## 7. 接口能力已更新 —— 与 PRD 现文的差异（需回写 v0.2）

对照官方 README 的工具表与版本日志：

| 位置 | PRD 现文 | 现状 | 建议 |
|---|---|---|---|
| §12「是否带图片字段」 | 待确认 | **有**。`query-meals.meals[code].image`，实测域名 `menu-img.mcd.cn`；`mall-product-detail` 官方描述亦含图片 | 结案：有字段，但按 §8 合规不落盘、不展示 |
| §2 范围「没有餐品订单的列表接口，只能按订单号查询」 | 不做历史订单批量导入 | 官方 1.0.6（2026-07-16）已上线 **`order-list` 历史订单查询** | 可评估把「历史订单复盘」纳入后续版本 |
| §2「v1.0.3 暂不支持更换套餐内单品」 | 不做套餐内换品 | 官方 **1.0.5（2026-06-16）已支持「更换套餐内商品组合、部分餐品特制」**；`query-meal-detail` 返回 `supportModify` 与 `modificationSummary` | 结论过期，需改；点餐页里「暂不支持更换套餐内单品」的提示也要同步 |
| §5 工具清单 | 未含取消/备注/餐具 | 1.0.8–1.0.9 新增 `cancel-order`、餐具选择、麦乐送备注 | 补进 §5 |
| §12「daypart 数字含义」 | 待确认 | 仍未在文档中说明 → 用 `rounds[].category` 与门店 `reservationTimeOptions` 侧证更稳 | 保持待确认 |
| §12「营养字段单位」 | 待确认 | 仍未标注 → 按列名（energyKj / energyKcal / 蛋白 / 脂肪 / 碳水 / 钠 mg / 钙 mg）推定，需实测核对 | 保持待确认 |
