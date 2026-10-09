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

| Tool | 用途 | 在 Skill 中的调用阶段 |
|---|---|---|
| `now-time-info` | 提供当前时间，作为餐段判定的时钟 | A 订单估算 / B 档位推荐入口 |
| `query-nearby-stores` | 按位置取附近门店，返回 `storeCode` | 门店定位（到店场景） |
| `delivery-query-addresses` + `delivery-query-stores` | 外送地址管理与按地址查门店 | 门店定位（外送场景） |
| `order-list` | 查询历史订单，取 `orderId` | A 订单估算兜底（用户无单号时） |
| `query-order` | 按 `orderId` 查询订单明细（套餐/单品/金额） | A 订单估算 |
| `list-nutrition-foods` | 全量营养表（热量/蛋白/脂肪/碳水/钠） | A/B 热量匹配（缓存 ≥24h，不重复拉取） |
| `query-meals` | 按门店与餐段取可售菜单（传 `reservationDate`=餐段代表时刻） | B 档位推荐 |
| `query-meal-detail` | 套餐组成明细（`rounds` 即品类，`isDefault=1` 为默认项） | B 组合枚举 |
| `query-store-coupons` | 查询当前门店可用优惠券 | D 下单前（仅标注，不参与排序） |
| `calculate-price` | 对选定组合报价（**金额单位为「分」，展示前 ÷100 转元**） | D 下单（含确认闸门） |
| `create-order` | 创建订单，返回支付链接，由用户自行支付 | D 下单（确认后才调用） |

---

## 3. 调用流程

Skill 把分散的 MCP 能力串成 4 条对话式工作流，本地脚本（`skill/scripts/*.py`）负责计算，MCP 负责实时数据：

### A. 订单热量估算（"这单多少热量？"）
1. `now-time-info` → 判定餐段（用户显式指定优先）。
2. 有 `orderId` → `query-order(orderId)` 取明细；无单号 → `order-list` 引导取单号或直接进入 B。
3. 本地 `mcd_order.py` 将套餐按 `comboItemList` 展开、剥离加料，逐项用 `list-nutrition-foods` 匹配热量。
4. 输出：逐项热量 → 整单合计 → 餐段档位对比结论；匹配不上标「热量未知」，合计写「≥ N kcal」，**绝不按 0 计算**。

### B. 档位推荐（"想吃 300 大卡左右的早餐"）
1. `now-time-info` → 餐段；`query-nearby-stores` / `delivery-query-stores` → 门店。
2. `query-meals(storeCode, orderType, beType, reservationDate=<餐段代表时刻>)` 取该餐段菜单。
3. 对候选套餐 `query-meal-detail` 取组成，本地 `mcd_combo.py` 枚举组合、按档位 ±12% 筛选、四种排序（near/protein/sodium/price）。
4. 输出 Top 3–4 组：热量/蛋白/脂肪/碳水/钠/参考价。

### C. 替换建议（"昨天那单偏高"）
1. 本地 `mcd_replace.py` 结合 `query-order` 明细与 `query-meals` 菜单。
2. 整单高于标准档 → 切标准档，输出替换组合与「少多少 kcal」。

### D. 下单（用户明确要求时）
1. `query-store-coupons` 查券（仅标注）。
2. `calculate-price` 报价（金额÷100 转元），**必须完整展示金额并以明确问句收尾，等待用户确认**。
3. 用户确认后 `create-order`（到店取报价返回 `takeWayList[].code` 作 `takeWayCode`），返回支付链接，用户自付；本 Skill 不代付、不轮询支付状态。

> 下单设不可绕过的「确认闸门」：未经明确确认，绝不调用 `create-order`（详见 `skill/docs/order-flow.md`）。

---

## 4. 业务价值

- **能力闭环**：将营养查询、菜单、订单、报价、下单等原子 MCP 工具，编排成「估算 → 推荐 → 替换 → 下单」一条可用链路，单点工具变成用户场景。
- **计算与数据分离**：实时数据交给官方 MCP 保证准确与合规；热量匹配、组合枚举、档位筛选等计算下沉到本地无依赖脚本，可离线评测（匹配率 ≥90% 验收）。
- **安全与合规内建**：下单强制确认闸门、Token 不落盘、营养失败不凭记忆编造、不使用官方图片商标，契合活动合规要求。
- **低门槛复用**：以 Agent Skill 形态交付，在支持 MCP 的客户端（如 WorkBuddy）配置 Token 后即可对话使用，无需额外部署。
