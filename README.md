# 热麦卡路里

> 麦当劳订单热量估算与餐段档位套餐推荐 · Agent Skill · 麦当劳程序员节创意开发大赛参赛作品

「热麦卡路里」是一套以对话方式运行的 **Agent Skill**：读取一笔麦当劳订单，估算整单热量，对照所处餐段的热量档位给出结论，并按餐段与档位推荐门店当前可售的套餐，最后给出更合适的替换方案。热量仅作为估算参考，不提供医学、减重或疾病相关的饮食建议。

底层能力来自麦当劳中国官方 MCP 服务 [`M-China/mcd-mcp-server`](https://github.com/M-China/mcd-mcp-server)（营养表、订单查询、门店菜单、优惠券、下单工具），本 Skill 负责把这些接口串成一条可用的闭环流程。

---

## 🎯 目标用户

- **关注热量/体重管理的普通消费者**：想快速知道「这单吃了多少热量」，避免无意间超标。
- **有减脂/控卡需求的轻健身人群**：需要在正餐之外快速找到「300 大卡左右的轻食组合」。
- **精打细算型食客**：希望在不超预算、不超热量的前提下，拿到门店当前可售的最优套餐组合与替换建议。
- **开发者 / 参赛者**：想参考如何把麦当劳 MCP 的原子能力（营养、菜单、订单、报价、下单）编排成一个可对话、可复用的 Skill。

> 本项目为参赛作品形态，**非麦当劳官方产品**；餐品信息、价格及供应状态以麦当劳官方渠道实时结果为准。

---

## ✨ 它能做什么

- **订单热量估算** — 用户提供订单号，`query-order` 读取后逐项匹配营养表，给出整单合计与餐段档位对比；匹配不上的项标注「热量未知」，绝不按 0 计算。
- **餐段识别** — 默认按当前时间判定（早餐 / 午餐 / 下午茶·随便吃吃 / 晚餐 / 宵夜），也支持用户显式指定。
- **档位推荐** — 按餐段 + 档位（轻量 / 标准 / 吃饱）枚举门店当前餐段菜单里的可行组合，支持四种排序：最接近档位、蛋白质更高、钠更低、价格更低。
- **替换建议** — 当整单高于该餐段标准档时，给出更轻的替换组合与「少多少 kcal」的对比。
- **安全下单** — 查券 → 报价 → **必须展示金额并获得用户确认** → 创建订单，返回支付链接由用户自付；本 Skill 不代付。

---

## 📦 安装方法

### 前置条件

- 已申请到 **麦当劳中国 MCP Token**（[申请指引](https://github.com/M-China/mcd-mcp-server)）。
- 一个支持 MCP 的客户端，本作品推荐使用官方合作伙伴 **WorkBuddy**（[官网](https://www.workbuddy.cn/)）。

### 步骤 1：接入麦当劳 MCP

在 WorkBuddy 左侧【专家·技能·连接器】→【连接器】→【自定义连接器】→【配置 MCP】，填入：

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

> ⚠️ 将 `YOUR_MCP_TOKEN` 替换为你的真实 Token，保存并**启用** `mcd-mcp`。

### 步骤 2：加载本 Skill

将本仓库的 `skill/` 目录作为 Skill 加载（或在对话中携带 `skill/SKILL.md` 的指引）。`skill/scripts/` 下的本地计算脚本为纯 Python 3.10+，无第三方依赖，可单独运行做离线评测。

### 步骤 3：开始对话

用下方任一触发语即可，例如：「这单多少热量？订单号是 xxx」或「想吃 300 大卡左右的早餐」。

---

## 🧪 使用示例

**示例 1 — 订单热量估算**
```
用户：这单多少热量？订单号 9900004064
WorkBuddy：
  【订单估算】
   ✓ 板烧鸡腿堡      391 kcal｜钠 1041mg
   ✓ 中薯条          289 kcal｜钠 165mg
   ✓ 可乐中杯        147 kcal｜钠 0mg
   整单：827 kcal（午餐·标准档 750 kcal → 略超，建议替换）
```

**示例 2 — 餐段档位推荐**
```
用户：想吃 300 大卡左右的早餐
WorkBuddy：
  【推荐 · 早餐 · 轻量】目标 300 kcal
   1. 猪柳麦满分      308 kcal｜蛋白 16g｜钠 781mg｜≈¥14.0
   2. 吉士蛋麦满分    290 kcal｜蛋白 13g｜钠 650mg｜≈¥13.0
   …（按最接近档位排序，支持 protein/sodium/price 切换）
```

**示例 3 — 替换建议**
```
用户：昨天那单偏高，今天来点轻的
WorkBuddy：基于你的午餐标准档 750 kcal，替换组合：
   鲜煮咖啡 + 那么大鸡排（轻） → 约 520 kcal，较原单少 ~307 kcal
```

**示例 4 — 安全下单**
```
用户：就按推荐第 1 组帮我下单（到店）
WorkBuddy：报价 ¥14.0（原价 ¥14.0 / 优惠 ¥0.0 / 应付 ¥14.0），到店取餐。确认按此下单吗？
用户：确认
WorkBuddy：已创建订单，支付链接：https://…（请自行支付，本助手不代付）
```

本地脚本也可独立运行：
```bash
# 估算一笔订单的热量合计
python skill/scripts/mcd_order.py --order skill/fixtures/order.sample-01-lunch-combo.json

# 推荐某餐段某档位的组合（按最接近档位排序）
python skill/scripts/mcd_combo.py \
  --menu skill/fixtures/meals.3570190.dinein.breakfast.json \
  --daypart 早餐 --tier 轻量 --sort near
```

---

## 🔁 工作流程

| 阶段 | 触发语 | 说明 |
|---|---|---|
| A. 订单热量估算 | "这单多少热量？" | 订单号 → 展开套餐 → 逐项匹配营养表 → 整单合计 + 档位对比 |
| B. 档位推荐 | "想吃 300 大卡左右的早餐" | 取该餐段菜单 → 枚举组合 → 按档位 ±12% 筛选 → 展示 Top 3–4 |
| C. 替换建议 | "昨天那单偏高" | 高于标准档则切标准档，输出替换组合 + 少多少 kcal |
| D. 下单 | 用户明确要求 | 查券（仅标注）→ 报价 → 确认闸门 → 创建订单 |

> 下单流程设有不可绕过的「确认闸门」：报价展示后必须以明确问句收尾，只有收到肯定答复才调用 `create-order`。详见 [`skill/docs/order-flow.md`](skill/docs/order-flow.md) 与 [`MCP_INTEGRATION.md`](MCP_INTEGRATION.md)。

---

## 📂 项目结构

```
热麦卡路里/
├── skill/                          # Agent Skill 源码（交付物）
│   ├── SKILL.md                    # Skill 定义：触发词 / 工具链 / 工作流 / 边界
│   ├── data/                       # alias.json（别名+默认规格）、category-rules.json（品类兜底）
│   ├── docs/                       # nutrition-schema / store-chain / order-flow / e2e-run
│   ├── fixtures/                   # 实测快照（营养表、菜单×2餐段、套餐详情、订单样本）
│   ├── scripts/                    # 本地计算脚本（Python 3.10+，无第三方依赖）
│   └── tools/eval_match.py         # 匹配率评测（常见订单集 ≥90% 验收）
├── README.md                       # 项目介绍、安装、示例、目标用户
├── CONTEST_DECLARATION.md          # 参赛声明（原创性/合规性/敏感信息）
├── MCP_INTEGRATION.md              # 实际使用的 MCP Server / Tool / 流程 / 价值
├── workbuddy.md                    # WorkBuddy 开发对话上下文导出
├── 订单热量与套餐推荐 Skill PRD.md  # 产品需求文档
├── 实施计划.html / 演示页.html / 点餐页.html  # 演示材料（标注"模拟"）
└── README.md
```

## 🛠 本地脚本（`skill/scripts/`，无第三方依赖，Python 3.10+）

| 脚本 | 职责 |
|---|---|
| `mcd_nutrition.py` | 营养表解析 / 名称归一化 / 四级匹配器（UNKNOWN 保护） |
| `mcd_daypart.py` | 餐段时段解析（门店实测优先）+ 档位表 |
| `mcd_combo.py` | 品类三级归类 + 组合枚举 + ±12% 筛选 + 四种排序 |
| `mcd_order.py` | 订单展开 + 加料剥离 + 合计与档位对比 |
| `mcd_replace.py` | 替换建议（标准档触发规则） |

---

## ⚠️ 边界与合规

- 热量为**估算参考**，不提供医学 / 减重 / 疾病饮食建议，不给「你应该吃多少」的处方。
- 营养表调用失败或为空 → 仅提示稍后重试，**不凭记忆给热量数字**。
- 不使用官方商品图片与商标素材；演示材料均标注「模拟」。
- Token 只在 MCP 客户端配置，不写入对话、日志或演示页。
- 限流 600 次/分钟：营养表缓存 ≥24h，菜单按「店 + 餐段」缓存 10min；429 退避重试。

---

## 🖥 演示

演示材料（实施计划、演示页、点餐页）均为本地单文件 HTML，数据来自 `skill/fixtures` 样本并标注「模拟」，用于展示交互形态，不涉及真实凭证。

---

## 🏆 参赛信息

- 本作品参加 **麦当劳程序员节创意开发大赛**（[活动仓库](https://github.com/M-China/mcd-developer-innovation-challenge)）。
- 开发工具：**WorkBuddy**（官方合作伙伴），开发对话上下文见 [`workbuddy.md`](workbuddy.md)。
- 底层能力：麦当劳中国官方 MCP [`M-China/mcd-mcp-server`](https://github.com/M-China/mcd-mcp-server)。
- 当前版本：**v0.1**。

---

*本项目为 Agent Skill 参赛作品形态，核心交付物为 `skill/` 目录，配套 PRD、演示页与参赛声明文档。*
