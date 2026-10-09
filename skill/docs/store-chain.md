# 门店与渠道参数链路（T5 产出）

> 实测时间 2026-10-09 23:36 GMT+8，城市：贵阳。

## 1. 到店自取（beType=1）

```
query-nearby-stores(beType=1, searchType=2, city=城市, keyword=位置关键词)
  → data[].storeCode        ← 必需
  → data[].beCode           ← 实测到店自取返回中 beCode 为空/缺省
  → 后续 query-meals(storeCode, orderType=1, beType=1)，不传 beCode
```

实测样例（贵阳）：
| storeCode | 门店 | 营业时间 | reservation |
|---|---|---|---|
| 3570122 | 贵阳北站餐厅 | 06:30–21:00 | true |
| 3570190 | 天一国际餐厅 | 07:00–02:00 | true |
| 3570271 | 招商银行大厦餐厅 | 08:00–00:00 | true |
| 3570165 | 金融城餐厅 | 00:00–23:59 | true |

## 2. 得来速（beType=5）

```
query-nearby-stores(beType=5, ...) → 门店带 beCode
  → query-meals(storeCode, orderType=1, beType=5, beCode=<必传>)
```

## 3. 麦乐送 / 团餐（beType=2 / 6）

```
delivery-query-addresses() → data[].地址列表（含 addressId）
delivery-query-stores(...) → 门店 beCode
  → query-meals(storeCode, orderType=2, beType=2|6, beCode=<必传>)
```

## 4. reservationTimeOptions = 逐店真实餐段时段（D2 依据）

实测文本格式（一条字符串内多段逗号分隔）：

```
早餐(07:14至10:15)，午餐(10:44至14:15)，下午茶(14:44至16:45)，夜市(17:14至21:45)
宵夜(00:00至04:45,22:14至23:59)，早餐(05:14至10:15)…
```

- 括号内可有**多段时间**（逗号分隔，如宵夜跨零点）。
- 「today=true」的日期条目是今天。
- 解析正则：`(?<name>早餐|午餐|下午茶|夜市|宵夜)\((?<ranges>[^)]+)\)`，range 内 `(\d{2}:\d{2})至(\d{2}:\d{2})`。
- 各店早餐起始差异大（05:14 / 06:44 / 07:14 / 08:14）→ **餐段判定必须用本表，不用固定值**。
- `reservation=true` 时展示预约选项不可省略时段信息（官方输出要求）。

## 5. 餐段判定优先级（T15 结论）

1. 用户显式指定（"我想吃早餐"）→ 最高
2. 门店 reservationTimeOptions 当前时刻落点
3. PRD 固定值兜底（06:00–10:29 / 10:30–15:29 / 15:30–17:59 / 18:00 起，宵夜 22:00 起）

## 6. 已知失败分支

- 到店自取收藏搜索无记录 → 改 `searchType=2` 按位置搜。
- `beCode` 传错场景（如 beType=1 却传 beCode）→ 400 类错误，脚本侧按场景白名单校验。
