# WorkBuddy 开发对话上下文导出（workbuddy.md）

> 本文件用于核验本项目是否符合「麦当劳程序员节创意开发大赛」WorkBuddy 联动活动奖励条件。
> 导出方式：在 WorkBuddy 中将本项目开发过程中的对话上下文整理导出。
> 结论：本项目**全程使用 WorkBuddy（官方合作伙伴）进行对话式开发**，从初始化、功能迭代、代码审校到文档与资产产出均在 WorkBuddy 中完成，开发工具与流程符合联动活动要求。

---

## 1. 开发环境与工具

| 项 | 内容 |
|---|---|
| 开发助手 | WorkBuddy（AI 编程/对话助手，官方合作伙伴） |
| 接入的 MCP | 麦当劳中国官方 MCP `mcd-mcp`（`https://mcp.mcd.cn`，Streamable HTTP，Bearer Token 鉴权） |
| 运行环境 | macOS；本地计算脚本为 Python 3.10+，无第三方依赖 |
| 版本控制 | Git + GitHub（Public 仓库 `orderye/mcd-calorie-skill`） |
| 交付形态 | Agent Skill（`skill/`，v0.8.0）+ 单文件 HTML（`food.html` 仪表/像素双风格 + `food-pixel.html` 独立像素版）+ 参赛文档 + `cover/`·`assets/` 品牌资产 |

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

### 节点 5 — food.html（仿客户端点餐流程）
- **User**：做一个仿麦当劳点餐流程的页面。
- **WorkBuddy**：新建 `food.html`（手机外框 + 右侧热量/日志面板）：门店与取餐方式 → 分类商品卡 → 规格弹层 → 吸底购物车 → 结算页 → 提交二次确认 → 支付链接；热量随加购即时刷新、超标准档 12% 弹出替换建议、下单二次确认。后以 impeccable skill 重构为「热感仪表」视觉（热量即色彩，由热量÷标准档驱动连续色阶），含抛物线飞入、数字滚动、原生 `<dialog>` 焦点陷阱等交互；jsdom 全流程断言全绿。

### 节点 6 — GitHub 推送与仓库重建
- **User**：推送本项目至 GitHub；随后反馈仓库被删、要求重新新建并推送。
- **WorkBuddy**：通过 `gh` / GitHub REST API 重建同名 Public 仓库 `orderye/mcd-calorie-skill`，修正可见性，重新 `git push` 恢复全部提交历史。

### 节点 7 — 参赛仓库规范化
- **User**：按比赛要求，仓库应包含 README / CONTEST_DECLARATION / MCP_INTEGRATION / 源代码 / workbuddy 五类内容。
- **WorkBuddy**：原样落地官方 `CONTEST_DECLARATION.md`（内容不可改）；重写 `README.md` 补齐「目标用户 / 安装方法 / 使用示例」；新建 `MCP_INTEGRATION.md`；导出本 `workbuddy.md`；并通过 Issue 按【参赛申请】格式报名（Issue #158）。

### 节点 8 — 全量产品与套餐目录采集（catalog）
- **User**：补齐全量产品与套餐内容。
- **WorkBuddy**：新增 `mcd_catalog.py` 离线聚合多份 `query-meals` 快照 + `meal-detail`，产出 `data/catalog.json`（179 商品 / 89 套餐 / 90 单品，按餐段价格），落盘剔除 image 字段；发现价格随餐段浮动、营养表覆盖约 44%、query-meals 分类含 menu 没有的 code 需 UNKNOWN 兜底；与 PRD 差异回写。

### 节点 9 — 官方产品图合规核查
- **User**：确认官方产品图来源与授权（PRD §12 待确认）。
- **WorkBuddy**：核查 MCP 响应确含 image 字段（已剔除）、媒体中心图库仅授权新闻/学术、MCP 条款不授权商标；结论继续用自绘/AI 生成无品牌图，如需真实图须书面授权。

### 节点 10 — 历史订单能力复核（order-list 实测）
- **User**：追问 mcd-mcp 能否获取历史订单。
- **WorkBuddy**：实测 `order-list` 返回 8 条真实订单；字段套餐子项 `name` vs `query-order` `productName`；与脱敏 fixture 逐条对得上；`mcd_history.py` 复盘跑通（均 1059 kcal、5 单超标准档）；边界：餐饮订单走 order-list/query-order，商城订单走 mall-*，不可混用。

### 节点 11 — 多轮代码审校与优化（含 CR 修复）
- **User**：多次「审校项目 / 优化代码质量 / 缩减代码 / 继续审校 / 重新审校」。
- **WorkBuddy**：累计 4 轮清理（消除动态导入反模式、O(n²) 改线性、删死代码、alias 精简、docs 时效性、HTML 深度逻辑与跨零点修复）；第 5 轮以「锻码师」专家视角全量评审，发现并修复 3 项真实问题——CR-001（餐段忽略 `expectedDaypart` 致历史单误判午餐）、CR-002（replace 不透传 daypart 致替换基准恒为午餐）、CR-003（演示页漏甜品致与引擎口径分叉）；回归 `eval_match` 常见订单集 **92.3% PASS**。

### 节点 12 — Logo 资产生成（AI 生成，assets/）
- **User**：生成项目 Logo；后要求换成金色拱门款。
- **WorkBuddy**：用 ImageGen 生成麦穗火焰版 4 张 + 金色拱门版 3 张（后者合规风险已提示）；采用「AI 出主体 + PIL 矢量绘制几何点缀（档位柱）」混合路线，规避 AI 对几何元素定位不准的问题。

### 节点 13 — 营养缺口补齐 + 数量后缀 bug 修复
- **User**：把历史订单未匹配项补进 `data/nutrition-gaps.json`。
- **WorkBuddy**：在 `mcd_catalog.collect_history_gaps()` 自动从脱敏订单展开 unknown（避免手改被覆盖）；修复 `normalize_query` 剥「N块」后缀导致「麦乐鸡5块」漏计的真 bug（加 `exact-qty` 1.5 级匹配），历史复盘 715→928 kcal；gaps 现状 unknown 40 / ambiguous 13。

### 节点 14 — 工程档案与全量推送
- **User**：生成项目工程档案；推送更新。
- **WorkBuddy**：新建 `project-engineering-file.md`（概况/技术栈/ADR×7/模块清单/接口约定/已知风险/待办）；多轮 `git` 提交推送（重建仓库、规范化、catalog、全量更新），含品牌资产 7 张图；提交前对暂存 diff 做凭证扫描（gho_/Bearer/sk-/JWT），均无真实凭证。

### 节点 15 — 套餐可选项全量补全（换品/特调数据）
- **User**：补全套餐的可选项数据（换品轮次、特调）。
- **WorkBuddy**：批量补采 `query-meal-detail` 快照（`fixtures/` meal-detail 达 90 份），新增 `scripts/fetch_meal_details.py` 采集脚本；`query-meal-detail` 口径补全——`rounds[].category` 优先、缺失按名称反查；换品差价 `diffPrice`、特调传参 `selectedKey`/`unselectedKey` 双 key 透传至报价与下单。

### 节点 16 — 目标场景策略层（mcd_goal，13 场景）+ D2 复盘入口
- **User**：想要「减脂吃什么 / 想控盐 / 今天还剩 600 卡」这类场景化推荐。
- **WorkBuddy**：新增 `scripts/mcd_goal.py` 目标场景策略层（13 场景：减脂/增重/练后餐/放纵餐/低钠控盐/高蛋白增肌/低糖低碳水/低脂清淡/素食蛋奶素/儿童小份量/热量预算日控/过敏原规避/性价比省钱），各自定义推荐档位、评分器、硬上限与关键词排除；`mcd_combo.py --goal` 接入；历史订单脱敏样本扩至 8 单（跨 2025-10 ~ 2026-03）；工作流编号定为 A–G + D2 并与 `SKILL.md`、README 对齐。

### 节点 17 — 公众号推文交付包
- **User**：产出可直接发布的公众号推文。
- **WorkBuddy**：新建 `公众号推文/`（推文成品.md + 推文交付包.html），随目标场景能力同步迭代。

### 节点 18 — README v0.7.0 重构与封面
- **User**：按 v0.7.0 重新整理 README；配官方风格封面。
- **WorkBuddy**：README 重构为 14 个固定分区（30 秒看懂 / 快速开始 / 核心能力 / 13 场景预设表 / 工作流 / 档位口径 / 对话示例 / 离线自测 / 项目结构 / 架构拓扑 / 已知限制 / 边界合规 / FAQ / 参赛信息），工作流编号与 `SKILL.md` 锁定一致；新增 `cover/` 红底官方金拱门封面并同步架构拓扑文档。

### 节点 19 — 演示/点餐页迭代 + 脱敏口径收紧
- **User**：点餐页切换真实菜单数据、双主题；持续审校。
- **WorkBuddy**：新增 `scripts/build_demo_menu.py` 由 fixtures 生成点餐页真实菜单数据，点餐页支持双主题与对比度优化；合规收紧——脱敏样本与复盘输出剔除 `orderId`/`traceId`（`mcd_history.py`、`order-list.sample.json` 同步）；别名表补「牛奶→纯牛奶（盒装）」；重跑 `eval_match` 验收 PASS（≥90%）。

### 节点 20 — v0.8 营养缺口攻坚：规格证据挖掘与餐品数据实时更新
- **User**：营养表覆盖不全、菜单名常缺规格（「薯条」「可乐」），能不能让 Skill 自己消化实时菜单的变化，而不是手工改数据？
- **WorkBuddy**：实测确认 `list-nutrition-foods` 是官方 MCP 唯一营养数据源（`query-meals` / `query-meal-detail` / `query-order` 均无营养字段）；利用「同一 code 在 `query-meals` 与 `query-meal-detail` 中指向同一商品」，新增 `scripts/mcd_spec_evidence.py` 用套餐具体命名反推菜单缺失规格，按 A（可补录）/ B（多值保持歧义）/ C1（疑似错误映射）/ C2（证据冲突）/ D（已解决）五级分级，`--apply` 仅写 A 级进 `alias.json#defaults`。实测补录 5 条默认规格（优品豆浆→小杯、怡泉+C→中杯、玉米杯→小杯、鲜萃咖啡→小杯、麦乐鸡→5块）、修正 2 条错误映射（牛奶→热牛奶中杯、麦咖啡™奶铁→冰奶铁中杯，修正前后均跑回归）；`category-rules.json` 拆分 `excludeNamePatterns` / `excludeNonFoodPatterns`，修复「蘸酱炸鸡」等含酱食物被误挡在候选外的隐患；Skill 版本升至 **v0.8.0**，常见订单集匹配率 92.3% → **13/13 = 100%**（歧义 0 / 未知 0）。Skill 由此具备「餐品数据实时更新」能力：推荐候选 100% 取当次 `query-meals` 实时可售（上新/下架/调价即时生效），本地快照持续沉淀为规格证据，别名表只在有实测证据时更新。

### 节点 21 — 演示页更名双风格合并 + 脚本架构分层与缓存/测试落地
- **User**：演示页更名并合并像素风；持续工程化。
- **WorkBuddy**：`点餐页.html` 更名 **`food.html`**（页头新增「仪表风 / 像素风」切换器，`localStorage` 记忆选择，样式表加载前先落 `data-skin` 避免首屏闪风格；像素风以 `html[data-skin="pixel"]` 前缀追加为第二皮肤，数据块零改动），独立像素版更名 **`food-pixel.html`**（数据冻结）；同步 `index.html` 跳转与各文档引用。随后脚本架构分层：新增 `mcd_taxonomy.py`（品类归类与排除规则**唯一加载点**）、`mcd_review.py`（复盘管线**唯一实现**，import/history 薄壳共用）、`mcd_cache.py`（带 TTL 缓存：营养 24h / 菜单 10min / 429 退避，CLI list/show/clear）；新增 `tests/test_engine.py` 引擎回归套件（47 断言：nutrition 矩阵 / daypart 21:59→22:00 边界 / goal 硬上限与 ±12% 不放宽 / taxonomy / cache），全绿；基线验证 worktree 输出与改动前逐字节一致 + `inject` 幂等。

---

## 3. 与麦当劳 MCP 的联动证据

- `skill/SKILL.md`「工具链（MCP）」与「工作流 A–G（含 D2）」明确列出实际调用的 `mcd-mcp` 工具（`now-time-info` / `query-nearby-stores` / `delivery-query-*` / `order-list` / `query-order` / `list-nutrition-foods` / `query-meals` / `query-meal-detail` / `query-store-coupons` / `calculate-price` / `create-order`）。
- `MCP_INTEGRATION.md` 完整记录了 Server 接入方式、11 个 Tool 清单（含关键字段/口径）、八条调用流程（A–G + D2，另含餐品数据实时更新链路）与实测结论。
- 实时数据源可核验：`data/catalog.json`（多份 `query-meals` 聚合）、`fixtures/`（营养表 / 四餐段菜单 / 套餐详情×90 / 订单样本 / 脱敏历史订单）均为 `mcd-mcp` 实测响应落盘（已剔除 image 字段）。
- 所有 Token 仅配置在 MCP 客户端，代码中以 `YOUR_MCP_TOKEN` 占位，符合信息安全声明。

---

## 4. 核验声明

本人确认：本项目基于 WorkBuddy 完成创意构思、编码、调试、代码审校（含专家评审与真实 bug 修复）、资产生成与文档产出，底层实时数据通过麦当劳官方 `mcd-mcp` 提供；项目为参赛者独立开发的参赛作品，非麦当劳官方产品。本文件如实导出覆盖「初始化 → 功能迭代 → 审校优化 → 资产与工程档案 → 目标场景收敛 → v0.8 营养缺口攻坚 → 双风格合并与脚本架构分层」共 21 个节点的开发对话上下文，用于核验是否符合 WorkBuddy 联动活动奖励条件。
