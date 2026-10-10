# 项目工程档案：热麦卡路里

## 1. 项目概况

- **一句话目标**：麦当劳订单热量估算与餐段档位套餐推荐 Agent Skill（麦当劳程序员节创意开发大赛参赛作品）。
- **当前阶段**：工程周期地图 **④ 评审与重构**。
- **最后更新**：2026-10-10 01:25（北京时间）——CR-001/002/003 修复并验证。
- **交付形态**：`skill/` 目录（Agent Skill）+ 单文件 HTML 演示页 + 参赛文档（README / CONTEST_DECLARATION / MCP_INTEGRATION / workbuddy）。

## 2. 技术栈与版本

| 项 | 内容 | 版本 |
|---|---|---|
| 计算脚本 | Python，无第三方依赖 | 3.10+（实测 3.13.12 通过） |
| 外部能力 | 麦当劳中国官方 MCP `mcd-mcp`（Streamable HTTP） | 端点 `https://mcp.mcd.cn`；协议/工具版本**待核实**（以官方仓库为准） |
| 演示页 | 单文件 HTML + 原生 JS（内联 CSS/JS） | — |
| 版本控制 | Git + GitHub Public `orderye/mcd-calorie-skill` | HEAD `0553224` |
| 运行环境 | macOS；Token 仅配置于 MCP 客户端 | — |

## 3. 架构决策记录（ADR）

| 编号 | 场景 | 决策 | 理由 | 代价 | 状态 |
|---|---|---|---|---|---|
| ADR-001 | 计算与数据的边界 | 三层分离：对话编排（SKILL.md）/ 本地计算（scripts）/ 数据缓存（data+fixtures） | 计算可离线评测（≥90% 验收）；实时数据交 MCP 保证准确合规 | 需维护数据快照 | 生效 |
| ADR-002 | 匹配不上如何处理 | 一律标「热量未知 / 待确认规格」，**绝不按 0 计算** | 诚实与合规（PRD F1/§9） | 覆盖率受限于营养表（单品约 44%） | 生效 |
| ADR-003 | 宵夜餐段 | 「宵夜」**单列档位**（300/450/600），不再并入晚餐 | 2026-10-10 用户拍板；实测门店存在 `00:00至04:45` 宵夜段 | 需处理跨零点 | 生效 |
| ADR-004 | 品类判定 | 三级：菜单分类名映射 → 套餐 rounds 反查 → 关键词兜底 | 单一来源不可靠，多级容错 | 规则需随菜单演进 | 生效 |
| ADR-005 | 演示形态 | 单文件 HTML，数据来自 fixtures 且标注「模拟」 | 无外部依赖、可离线展示；合规（不用官方图/商标） | 演示数据与实时可能漂移 | 生效 |
| ADR-006 | 别名表收录标准 | 仅收录**归一化无法直接命中**的映射（2026-10-10 精简至 2 条） | 品牌前缀/括号/空格由 `normalize_name` 自动剥离走 exact | — | 生效 |
| ADR-007 | 离线营养缺口 | 导出 `nutrition-gaps.json`（未收录单品 37 + 规格歧义 13） | 避免每次重新发现；作为补录/反馈清单 | 需随菜单刷新 | 生效 |

## 4. 模块清单与进度

| 模块 | 状态 | 说明 |
|---|---|---|
| `scripts/mcd_nutrition.py` | 已完成 | 营养表解析 / 归一化 / 四级匹配器（含长度窗口剪枝） |
| `scripts/mcd_daypart.py` | 已完成 | 餐段判定（门店实测 > 固定兜底）+ 档位表（含宵夜跨零点） |
| `scripts/mcd_combo.py` | 已完成 | 品类归类 + 组合枚举（预剪枝）+ ±12% 筛选 + 四种排序 |
| `scripts/mcd_order.py` | 已完成 | 订单展开 + 加料剥离 + 合计与档位对比；餐段来源优先级已修（CR-001） |
| `scripts/mcd_replace.py` | 已完成 | 替换建议；已补 `--time/--user-daypart` 透传（CR-002） |
| `scripts/mcd_history.py` | 已完成 | 历史订单批量复盘 |
| `scripts/mcd_catalog.py` | 已完成 | 全量目录聚合 + 营养缺口导出 |
| `tools/eval_match.py` | 已完成 | 匹配率评测（常见订单集 ≥90%） |
| `data/*` | 已完成 | alias / category-rules / catalog / nutrition-gaps |
| `演示页.html` / `food.html` | 已完成 | 交互演示；正餐组合已纳入甜品，与引擎对齐（CR-003） |
| `docs/*` | 已完成 | nutrition-schema / store-chain / order-flow / e2e-run / catalog-collection |

## 5. 接口约定

**MCP 工具契约（实现阶段必须遵守）：**

- `query-meals`：**无 daypart 字段**，取指定餐段菜单须传 `reservationDate=目标餐段代表时刻`；价格随餐段浮动，**必须用当次返回值**。
- `query-order` 子项名称字段为 `productName`；`order-list` 子项名称字段为 `name`（**字段差异，展开必须兼容**）。
- `calculate-price` 返回金额单位为**分**，展示前 ÷100 转元。
- 到店下单（`orderType=1`）`create-order` **必传 `takeWayCode`**，取自同门店同组合的 `calculate-price` 返回 `data.takeWayList[].code`。
- 下单前必须展示金额并获得用户**明确确认**（确认闸门，不可绕过）。

**脚本 CLI 契约：**

- 所有脚本 `sys.path` 自注入 `scripts/`，可独立运行，无第三方依赖。
- `mcd_order.py --order/--daypart/--tier/--time/--store-options/--user-daypart`
- `mcd_combo.py --menu/--daypart/--tier/--sort/--top`
- `mcd_replace.py --order/--menu/--tier/--sort`（**缺 --daypart/--time，见 CR-002**）

## 6. 已知风险

| 编号 | 级别 | 风险 | 状态 |
|---|---|---|---|
| CR-001 | 🔴 | 订单餐段未从订单自带信息推断，非午餐订单被误判午餐档 | ✅ 已修复（2026-10-10）：`estimate()` 优先级 显式入参 > `_meta.expectedDaypart`/`createTime` > `now_hhmm`；6/6 样本核对通过 |
| CR-002 | 🟠 | `mcd_replace.py` 无 `--daypart/--time`，替换基准恒为午餐 | ✅ 已修复（2026-10-10）：补 `--time/--user-daypart` 并透传；sample-02 现按早餐基准 |
| CR-003 | 🟠 | 演示页正餐组合不含甜品，与引擎口径分叉 | ✅ 已修复（2026-10-10）：两页正餐分支合并 `snacks+desserts` |
| RISK-004 | 🟠 | 营养表对当前在售单品覆盖率约 44%，新品多未收录 | 持续（补录/反馈） |
| RISK-005 | 🟡 | 金额用 float（Python/JS 均然） | 已评估，**接受**：仅展示层四舍五入，无 cents 级累加，改整数分收益低且回归面大，遵循「不过度设计」暂不改 |
| RISK-006 | 🟡 | MCP 账号授权范围（读订单 / 下单）与协议版本未最终确认 | 待确认（须以官方文档核实，不臆断） |
| RISK-007 | 🟡 | 演示数据与实际菜单/价格会漂移，`e2e-run.md` 命中组数随快照变化 | 已在文档标注 |

## 7. 待办

1. ~~修 CR-001~~ ✅ 已完成并验证。
2. ~~修 CR-002~~ ✅ 已完成并验证。
3. ~~修 CR-003~~ ✅ 已完成并验证。
4. RISK-005 已评估接受（见 §6）；RISK-006 保持待确认。
5. 修复后已重跑 `eval_match`（92.3% PASS）与 e2e 场景（827 kcal / 早餐轻量 7 组 / sample-05 替换 191 组），结果不变。
6. **Git 提交**：四轮审校累计 15 项 + 本轮修复 + 本档案，均未提交。

---

> 本档案为锻码师（code-architect-expert）维护的多轮开发记忆载体。ADR 只增不删，废弃方案标状态并保留追溯链。
