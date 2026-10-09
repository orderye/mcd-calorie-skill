# WorkBuddy 开发对话上下文导出（workbuddy.md）

> 本文件用于核验本项目是否符合「麦当劳程序员节创意开发大赛」WorkBuddy 联动活动奖励条件。
> 导出方式：在 WorkBuddy 中将本项目开发过程中的对话上下文整理导出。
> 结论：本项目**全程使用 WorkBuddy（官方合作伙伴）进行对话式开发**，开发工具与流程符合联动活动要求。

---

## 1. 开发环境与工具

| 项 | 内容 |
|---|---|
| 开发助手 | WorkBuddy（AI 编程/对话助手，官方合作伙伴） |
| 接入的 MCP | 麦当劳中国官方 MCP `mcd-mcp`（`https://mcp.mcd.cn`，Streamable HTTP，Bearer Token 鉴权） |
| 运行环境 | macOS；本地计算脚本为 Python 3.10+，无第三方依赖 |
| 版本控制 | Git + GitHub（Public 仓库 `orderye/mcd-calorie-skill`） |
| 交付形态 | Agent Skill（`skill/` 目录）+ 单文件 HTML 演示页 + 参赛文档 |

---

## 2. 开发对话上下文（关键节点摘要）

以下为使用 WorkBuddy 开发本项目的代表性对话轮次（User = 开发者，WorkBuddy = 助手）。

### 节点 1 — 项目初始化与 Skill 设计
- **User**：基于麦当劳 MCP 做一个「订单热量估算 + 餐段档位套餐推荐」的 Skill。
- **WorkBuddy**：搭建 `skill/` 骨架（`SKILL.md`、数据表 `alias.json`/`category-rules.json`、`scripts/` 计算脚本、`fixtures/` 实测快照、`docs/` 设计文档），明确工具链（营养表、订单、菜单、优惠券、报价、下单）与四段工作流 A/B/C/D。

### 节点 2 — 餐段与档位决策（用户拍板）
- **User**：「宵夜」（约 22:14 起）单列档位，不再并入晚餐。
- **WorkBuddy**：落地 `mcd_daypart.py` 的 `宵夜` 别名、独立档位（300/450/600）与跨零点时段判定；同步更新 `SKILL.md` 默认值与 `docs/e2e-run.md` 场景，验证 `mcd_combo.py --daypart 宵夜` 正常出组。

### 节点 3 — 演示页前端落地
- **User**：做一个单文件、内联 CSS/JS、暗色扁平、固定分区全局编号的演示页。
- **WorkBuddy**：新建根目录 `演示页.html`（三栏：订单热量估算 + 档位对比 / 档位推荐卡片 / 工具调用日志；含「Skill 设计」标签页），模拟数据与 `fixtures` 样本对齐，餐段已含「宵夜」单列。

### 节点 4 — 计算脚本优化
- **User**：优化组合排序逻辑。
- **WorkBuddy**：调整 `mcd_combo.py` / `mcd_nutrition.py` / `mcd_order.py` 的排序与匹配实现，提交为 `feat: 优化麦当劳热量脚本排序逻辑，新增演示页`。

### 节点 5 — GitHub 推送与仓库重建
- **User**：推送本项目至 GitHub；随后反馈仓库被删、要求重新新建并推送。
- **WorkBuddy**：通过 `gh` / GitHub REST API 重建同名 Public 仓库 `orderye/mcd-calorie-skill`，修正可见性，重新 `git push` 恢复全部提交历史。

### 节点 6 — 参赛仓库规范化（本次）
- **User**：按比赛要求，仓库应包含 README / CONTEST_DECLARATION / MCP_INTEGRATION / 源代码 / workbuddy 五类内容。
- **WorkBuddy**：
  - 原样落地官方 `CONTEST_DECLARATION.md`（内容不可改）；
  - 重写 `README.md`，补齐「目标用户 / 安装方法 / 使用示例」分区；
  - 新建 `MCP_INTEGRATION.md`，列明实际使用的 `mcd-mcp` Server、11 个 Tool、四段调用流程与业务价值；
  - 导出本 `workbuddy.md` 对话上下文；
  - 提交并推送至 Public 仓库。

---

## 3. 与麦当劳 MCP 的联动证据

- `skill/SKILL.md`「工具链（MCP）」明确列出实际调用的 `mcd-mcp` 工具（`query-order` / `list-nutrition-foods` / `query-meals` / `query-meal-detail` / `query-store-coupons` / `calculate-price` / `create-order` 等）。
- `MCP_INTEGRATION.md` 完整记录了 Server 接入方式、Tool 清单、调用流程与业务价值。
- 所有 Token 仅配置在 MCP 客户端，代码中以 `YOUR_MCP_TOKEN` 占位，符合信息安全声明。

---

## 4. 核验声明

本人确认：本项目基于 WorkBuddy 完成创意构思、编码、调试与文档产出，底层实时数据通过麦当劳官方 `mcd-mcp` 提供；项目为参赛者独立开发的参赛作品，非麦当劳官方产品。本文件如实导出开发对话上下文，用于核验是否符合 WorkBuddy 联动活动奖励条件。
