# MCP 集成说明（MCP_INTEGRATION.md）

本文说明「热麦卡路里」Skill 实际接入的麦当劳 MCP Server、调用的 Tool、调用流程与业务价值。
底层实时数据（营养表、门店菜单、订单、报价、下单）全部经由官方 MCP 提供，本地脚本只负责计算与组合编排。

---

## 1. 实际使用的麦当劳 MCP Server

| 项 | 内容 |
|---|---|
| Server 名称 | 麦当劳中国官方 MCP 服务（`mcd-mcp`） |
| 官方源码 | https://github.com/M-China/mcd-mcp-server |
| 接入端点 | `https://mcp.mcd.cn`（Streamable HTTP） |
| 鉴权方式 | `Authorization: Bearer <MCP_TOKEN>`（Token 由用户在麦当劳 MCP 控制台申请，**仅配置在 MCP 客户端，不写入代码/对话/日志**） |
| 接入方式 | 在 WorkBuddy「自定义连接器 → 配置 MCP」中填入以下 JSON 并启用： |

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_TOKEN"
      }
    }
  }
}
```

> ⚠️ Token 属于敏感凭证，本项目所有代码与文档均使用 `YOUR_MCP_TOKEN` 占位，不含任何真实凭证（见 CONTEST_DECLARATION.md 信息安全声明）。

---

## 2. 实际调用的 Tool 清单

本项目实际调用官方 `mcd-mcp` 的 11 个 Tool（其中 `delivery-query-addresses` + `delivery-query-stores` 视作外送定位一组）。连接器还提供券包、积分账户、团餐、商城等额外能力，但本项目**主动收窄、未调用**（见 §4 合规与收窄说明）。

| Tool | 用途 | 调用阶段 | 关键字段 / 口径 |
|---|---|---|---|
| `now-time-info` | 当前时间，作为餐段判定的时钟 | A / B 入口 | 返回 success/code 200，连通性已实测 |
| `query-nearby-stores` | 按位置取附近门店，返回 `storeCode`(+`beCode`) | B / E 门店定位（到店） | 各店 `reservationTimeOptions` 含宵夜段，以实测为准 |
| `delivery-query-addresses` + `delivery-query-stores` | 外送地址管理与按地址查门店 | B / E 门店定位（外送） | 外送门店与到店门店集合可能不同 |
| `order-list` | 历史订单列表（**无入参**），取 `orderId` | A 兜底 / D 复盘 | 套餐子项名称字段是 `name`（非 `productName`） |
| `query-order` | 按 `orderId` 查订单明细（套餐/单品/金额） | A 估算 | 套餐子项 `comboItemList[].name`，顶层 `productName` |
| `list-nutrition-foods` | 全量营养表（热量/蛋白/脂肪/碳水/钠） | A / B / C 匹配 | **单品覆盖率 44.4%（40/90，实测门店 3570190），全量含套餐命中 60/179**（实测）；缓存 ≥24h 不重复拉取 |
| `query-meals` | 按门店与餐段取可售菜单 | B 推荐 | **无 daypart 字段，传 `reservationDate`=餐段代表时刻**；价格随餐段浮动，必须用当次返回值 |
| `query-meal-detail` | 套餐组成 / 换品 / 特调 | B 组合枚举 | `rounds[].name` 是轮次名**非品类**；`choices[].diffPrice` 即换品差价；特调看 `supportModify`/`modification`，传参用 `selectedKey`/`unselectedKey` |
| `query-store-coupons` | 当前门店可用优惠券 | E 下单前 | 仅标注，不参与排序 |
| `calculate-price` | 对选定组合报价 | E 下单（含确认闸门） | **金额单位为「分」，展示前 ÷100 转元**；到店返回 `takeWayList[].code` 作 `takeWayCode` |
| `create-order` | 创建订单，返回支付链接，由用户自行支付 | E 下单（确认后才调用） | 本 Skill 不代付、不轮询支付状态 |

---

## 3. 调用流程

Skill 把分散的 MCP 能力串成 8 条对话式工作流（与 `skill/SKILL.md` 工作流 A–G + D2 对齐，D2 为 D 同一历史订单链路的复盘入口）；本地脚本（`skill/scripts/*.py`）负责计算，MCP 负责实时数据：

### A. 订单热量估算（"这单多少热量？"）
1. `now-time-info` → 判定餐段（订单是历史事实，**优先取订单自带** `createTime`/`expectedDaypart`，否则用当前时刻）。
2. 有 `orderId` → `query-order(orderId)` 取明细；无单号 → `order-list` 引导取单号或直接进 B。
3. 本地 `mcd_order.py` 将套餐按 `comboItemList` 展开（兼容 `name`/`productName`）、剥离加料，逐项用 `list-nutrition-foods` 匹配热量。
4. 输出：逐项热量 → 整单合计 → 餐段档位对比结论；匹配不上标「热量未知」，合计写「≥ N kcal」，**绝不按 0 计算**。

### B. 档位推荐（"想吃 300 大卡左右的早餐"）
1. `now-time-info` → 餐段；`query-nearby-stores` / `delivery-query-stores` → 门店（用户显式指定餐段优先）。
2. `query-meals(storeCode, orderType, beType, reservationDate=<餐段代表时刻>)` 取该餐段菜单（**价格用当次返回**）。
3. 对候选套餐 `query-meal-detail` 取组成，本地 `mcd_combo.py` 枚举组合、按档位 ±12% 筛选、四种排序（near/protein/sodium/price）。
4. 输出 Top 3–4 组：热量/蛋白/脂肪/碳水/钠/参考价。

### C. 替换建议（"昨天那单偏高"）
1. 本地 `mcd_replace.py` 结合 `query-order` 明细与 `query-meals` 菜单（支持 `--daypart/--time` 透传，替换基准不再是固定午餐）。
2. 整单高于标准档 → 切标准档，输出替换组合与「少多少 kcal」。

### D. 一键导入历史订单并分析热量（"导入我的历史订单分析热量"）
1. `order-list`（无入参）→ 取历史订单**原始响应**（含 orderId / storeCode / storeName / beCode / traceId 等敏感字段）。
2. 本地 `mcd_import.py --raw <原始响应>` → **自动脱敏**（剔除 orderId / storeCode / storeName / beCode / traceId，门店以「门店A/B/C」代称）→ 落盘脱敏样本 → 逐单展开套餐 → 匹配营养表 → 合计 → 按 `createTime` 推断餐段 → 与标准档对比 → 汇总（排行/超档/平均/未知占比，`--json` 导出）。
3. 已有脱敏样本时用 `--no-deidentify` 直接复盘（同 D2 历史复盘）。对超档订单再接 C 生成更轻方案。
4. **脱敏是硬红线**：原始响应（含敏感字段）绝不落盘，只落脱敏后的样本。

### E. 下单（用户明确要求时）
1. `query-store-coupons` 查券（仅标注）。
2. `calculate-price` 报价（金额÷100 转元），**必须完整展示金额并以明确问句收尾，等待用户确认**。
3. 用户确认后 `create-order`（到店取②返回的 `takeWayList[].code` 作 `takeWayCode`），返回支付链接，用户自付；本 Skill 不代付、不轮询支付状态。

> 下单设不可绕过的「确认闸门」：未经明确确认，绝不调用 `create-order`（详见 `skill/docs/order-flow.md`）。

### F. 全量目录（离线匹配 / 兜底，非实时推荐）
`scripts/mcd_catalog.py` 把多份 `query-meals` 快照 + `meal-detail` 聚合成 `data/catalog.json`（179 商品 / 89 套餐 SKU / 90 单品，按餐段价格；`fixtures/` 已沉淀 90 份 meal-detail 快照支撑换品/特调枚举）并导出 `data/nutrition-gaps.json`（未收录单品 40 + 规格歧义 13 的 UNKNOWN 白名单，含 `origin=history-order` 的历史已下架品）。
**纪律**：目录只用于匹配与兜底；**推荐候选仍必须取自当次 `query-meals` 实时返回**（价格随餐段浮动，目录价会过期）。

### G. 目标场景推荐（"减脂吃什么" / "想控盐" / "今天还剩 600 卡"）
1. `now-time-info` → 餐段；`query-meals(...)` 取该餐段实时菜单（同 B）。
2. 本地 `mcd_goal.py` 把「餐段 × 档位 × 场景 × 入参」解析成推荐计划（`resolve_plan`）：13 场景各自决定推荐档位、排序评分器、整组硬上限（钠/碳水/脂肪/价格/预算）、池级关键词排除（素食/过敏原）与组合结构（件数上限、必含主食、纯小食拼组）。
3. 本地 `mcd_combo.py --goal <场景> [--sodium-max/--carb-max/--fat-max/--price-max/--budget/--allergens/--max-items]` 枚举并筛选，输出 Top 3–4 组。
4. 场景（减脂/增重/练后餐/放纵餐/低钠控盐/高蛋白增肌/低糖低碳水/低脂清淡/素食蛋奶素/儿童小份量/热量预算日控/过敏原规避/性价比省钱）自动切换档位与排序，无需手动传 `--tier/--sort`。
5. **粗筛告警**：素食与过敏原基于名称关键词（菜单无配料/过敏原表），结果不完整，须提示以门店配料与员工确认为准。

### 餐品数据实时更新（贯穿 A–G 的数据层能力，v0.8）

Skill 的餐品数据**不靠静态菜单维护**，而是随 MCP 实时接口持续刷新，并通过证据挖掘自我修正：

1. **实时层**：推荐候选 100% 来自当次 `query-meals` 实时可售结果——新品上架、下架、调价即时生效，无需改任何本地数据；本地快照仅作证据与离线兜底。
2. **证据层（`mcd_spec_evidence.py`，v0.8 新增）**：利用「同一 code 在 `query-meals` 与 `query-meal-detail` 中指向同一商品」，用套餐里的具体命名（如 4437「小杯玉米杯」）反推菜单名（4437「玉米杯」）缺失的规格，按五级分类：
   - **A 可补录（usable）**：菜单名未命中且套餐名是其扩写 → `--apply` 写入 `alias.json#defaults`（仅订单/套餐上下文启用）；
   - **B 多值（multivalue）**：菜单名自带多值标记或涉及「冰/热」做法差异 → 保持歧义让用户选；
   - **C1 疑似错误映射（conflict-mapping）**：现网命中 ≠ 套餐证据 → 人工修正 `mappings`；
   - **C2 证据冲突（conflict）**：同一 code 在不同套餐里出现多个规格 → 禁止补录；
   - **D 已解决（resolved）**：无需处理。
3. **实测（2026-10-10）**：A 级证据的同 code 命名一致率 100%（如 4810 出现 35 次全为「中薯条」）；据此补录 5 条默认规格（优品豆浆→小杯、怡泉+C→中杯、玉米杯→小杯、鲜萃咖啡→小杯、麦乐鸡→5块），修正 2 条错误映射（菜单「牛奶」→热牛奶中杯、菜单「麦咖啡™奶铁」→冰奶铁中杯，修正前后均跑回归）；常见订单集匹配率由 92.3% 提升至 **13/13 = 100%**（歧义 0 / 未知 0）。
4. **红线**：「冰/热」是做法差异（冰奶铁 148 vs 热奶铁 186 kcal）而非规格，涉及冰热的证据一律保持歧义；B / C 级证据一律不自动补录——**用证据消歧，而非猜测**。

---

## 4. 关键实测结论与字段口径

- **价格随餐段浮动**：同一单品在早餐/午餐/夜市价差可达数元（如麦咖啡™奶铁 13.9 / 9.9），报价与排序**必须用当次 `query-meals` 返回价**，目录价仅作兜底。
- **营养表覆盖率 44.4%**：`list-nutrition-foods` 对当前在售单品覆盖 40/90（实测门店 3570190），全量含套餐命中 60/179；缺口集中在 BTS 联名、新品等；未命中项走「热量未知」而非编造，缺口登记在 `data/nutrition-gaps.json`。
- **跨接口字段差异（已修真 bug）**：`order-list` 套餐子项用 `name`，`query-order` 用 `productName`；原 `expand_order` 只认后者 → 历史订单 92.3% 被误判「热量未知」。修复后兼容两者，未知率降至 10.3%。
- **`query-meals` 无 daypart**：以 `reservationDate`=目标餐段代表时刻代替；分类可出现 `meals{}` 里没有的 code（夜市 9900000881）→ 必须保留 UNKNOWN 兜底。
- **换品 vs 特调**：换品在 `rounds`/`choices` 层（差价 `diffPrice`）；特调看 `supportModify`/`modification`（去冰、换燕麦奶等），传参须同时带 `selectedKey` 与 `unselectedKey`。
- **同一 code 跨接口共享**：`query-meals` 与 `query-meal-detail` 的 code 指向同一商品——套餐内该 code 的具体命名即菜单名缺失规格的证据（v0.8 规格证据挖掘的依据）；但两个接口**均无营养字段**，`list-nutrition-foods` 仍是唯一营养数据源。
- **限流与缓存**：连接器 600 次/分钟；营养表缓存 ≥24h，菜单按 店+餐段 缓存 10min；429 退避重试。
- **主动收窄的能力**：券包（`available-coupons`/`query-my-coupons`/`auto-bind-coupons`）、积分账户、团餐（`party-*`/`query-promotions`）、商城（`mall-*`）官方已提供，但本期仅用 `query-store-coupons` 标注、不介入核销，保持最小依赖、降低合规面。

---

## 5. 业务价值

- **能力闭环**：将营养查询、菜单、订单、报价、下单、历史复盘等原子 MCP 工具，编排成「估算 → 推荐 → 替换 → 复盘 → 下单」一条可用链路，单点工具变成用户场景。
- **餐品数据实时更新、自我进化**：实时餐品以当次 `query-meals` 为唯一来源（上新/下架/调价即时生效）；本地快照沉淀为规格证据（`mcd_spec_evidence.py` 五级分级），别名表只在有实测证据时更新——菜单名缺规格的歧义从 92.3% 匹配率收敛到 13/13 = 100%，且全程「用证据消歧、不猜测」。
- **计算与数据分离**：实时数据交给官方 MCP 保证准确与合规；热量匹配、组合枚举、档位筛选、历史复盘等计算下沉到本地无依赖脚本，可离线评测（常见订单集匹配率 **13/13 = 100% PASS**，≥90% 验收）。
- **安全与合规内建**：下单强制确认闸门、Token 不落盘、营养失败不凭记忆编造、不使用官方图片商标；图片字段一律不落盘；契合活动合规要求。
- **低门槛复用**：以 Agent Skill 形态交付，在支持 MCP 的客户端（如 WorkBuddy）配置 Token 后即可对话使用，无需额外部署。
