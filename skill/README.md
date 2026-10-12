# 热麦卡路里 · Agent Skill (mcd-calorie-combo)

> 麦当劳订单热量估算与餐段档位套餐推荐 · 纯 Python 零依赖 Agent Skill  
> 麦当劳程序员节创意开发大赛参赛作品

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-streamable--http-4B8BBE)](https://github.com/M-China/mcd-mcp-server)
[![Skill](https://img.shields.io/badge/Skill-v0.9.0-FFC72C)](SKILL.md)
[![Zero-Dependencies](https://img.shields.io/badge/Dependencies-0%20External-brightgreen)](#)
[![Tests](https://img.shields.io/badge/Tests-47%20Passed-success)](tests/)

---

## 📖 项目简介

**「热麦卡路里 · Agent Skill」** 是一套专为 AI Agent（如 WorkBuddy、Antigravity、Cursor、Claude Desktop 等）设计的麦当劳热量估算与智能点餐推荐技能。

底层能力无缝对接麦当劳中国官方 MCP 规范接口（营养表、订单查询、门店实时菜单、优惠券、报价下单）。本 Skill 在本地以**纯 Python（标准库，零第三方依赖）**实现了高内聚的业务编排层：
把 **「订单热量展开估算 → 餐段档位科学对比 → 13 种目标场景可售推荐 → 更轻组合替换 → 报价与防误触安全下单」** 串联为完整的交互闭环。

> ⚠️ **免责声明**：本项目为参赛作品，**非麦当劳官方产品**；餐品信息、价格及供应状态以麦当劳官方渠道实时结果为准。热量为估算参考，不构成医学、减重或疾病饮食建议。

---

## 🌟 核心特性

### 1. 纯 Python 零依赖算法引擎
* 全套脚本基于 Python 3.10+ 标准库开发（`pathlib`、`json`、`argparse`、`unittest` 等），无需 `pip install` 任何第三方依赖，开箱即用。
* 独立轻量缓存与退避机制（`mcd_cache.py`），支持中文 Key 隔离、TTL 过期自动清理与 429 频控退避。

### 2. 红线锁死，杜绝「幻觉热量」
* **不猜数据**：营养库未匹配单品明确标记为「未知」，整单合计严格输出为「≥ N kcal（实际会更高）」，严禁隐式算作 0 kcal。
* **不猜规格**：对无证据可乐、薯条、派等模糊单品强制提示确认规格或选用中包标准参考，不作无依据推断。
* **加料剥离**：识别「加…(加)」等改配项，将其从基础品剥离并明确向用户声明。

### 3. 13 个目标场景精准推荐（`mcd_goal.py`）
内置完备的多目标规划与关键词过滤策略：
* **形体管理**：减脂（低脂优先）、增重（热量达标 + 高性价比）、练后餐（高碳高蛋白快速充糖）
* **健康与慢病考量**：低钠控盐（硬上限拦截）、低糖低碳水、低脂清淡、素食/蛋奶素
* **特定人群与日常**：高蛋白增肌、儿童/小份量（自动缩放 0.85）、热量预算日控（指定剩余卡路里）、过敏原规避（花生/坚果/乳糖/海鲜）、性价比/省钱（元/大卡排序）

### 4. 全餐段自适应与科学档位
* 自动或按指定判定 5 大餐段：**早餐**（06:00–10:30）、**午餐**（10:30–14:00）、**下午茶**（14:00–17:00）、**晚餐**（17:00–22:00）、**宵夜**（22:00–06:00）。
* 细分「轻量档 / 标准档 / 丰盛档」，采用科学的 `±12%` 容差区间，智能给出同餐段更轻替换组合（少吃多少 kcal）。

### 5. 历史订单一键导入与脱敏（`mcd_import.py`）
* 支持将官方 `order-list` 原始数据一键导入，敏感字段（手机号、地址、完整单号）哈希/掩码脱敏后落盘。
* 提供历史饮食复盘，输出热量排行榜与餐段偏好分析。

### 6. 安全防误触下单闸门
* 严格遵循「报价核验 → 用户确认金额 → 触发创单」安全准则，避免 AI 自主越权产生实际交易。

---

## 📂 仓库目录架构

```text
.
├── SKILL.md                 # Agent Skill 核心规范与多轮对话工作流指令
├── README.md                # 仓库说明文档（本文件）
├── scripts/                 # 本地核心算法与策略层（零外部依赖）
│   ├── mcd_order.py         # 订单解析与热量估算
│   ├── mcd_combo.py         # 实时菜单组合与档位推荐引擎
│   ├── mcd_goal.py          # 13 种目标场景策略层
│   ├── mcd_replace.py       # 智能健康替换建议
│   ├── mcd_taxonomy.py      # 餐品分类、主副食判断与品类兜底
│   ├── mcd_spec_evidence.py # 五级规格证据挖掘与别名提取
│   ├── mcd_review.py        # 订单/组合营养三色健康审校
│   ├── mcd_cache.py         # 中文 Key 缓存管理与 429 退避
│   ├── mcd_daypart.py       # 餐段划分与代表时刻判定
│   ├── mcd_nutrition.py     # 营养表精确/模糊匹配器
│   ├── mcd_history.py       # 历史订单统计与复盘
│   ├── mcd_import.py        # 历史订单导入与脱敏
│   └── mcd_catalog.py       # 离线菜品目录聚合
├── data/                    # 规则表与离线对照数据
│   ├── alias.json           # 别名映射与默认规格表
│   ├── category-rules.json  # 品类分类与主副食判定规则
│   ├── catalog.json         # 全时段菜品目录聚合
│   ├── history-orders.json  # 脱敏历史订单样本库
│   └── nutrition-gaps.json  # 营养表覆盖缺口对照清单
├── docs/                    # 详细技术设计与接入文档
│   ├── order-flow.md        # 完整下单与工具调用时序
│   ├── store-chain.md       # 门店链路与餐段推导
│   ├── e2e-run.md           # 端到端运行指引与场景实测
│   ├── nutrition-schema.md  # 营养数据结构规范
│   └── catalog-collection.md# 目录收集与规格证据挖掘方案
├── fixtures/                # 官方 MCP 真实接口脱敏快照（多门店/多餐段/订单）
├── tests/                   # 自动化回归测试套件
│   ├── run_tests.py         # 一键测试运行器（带 CANARY 防伪造金丝雀）
│   ├── test_engine.py       # 核心引擎 47 项断言矩阵
│   └── final_checks.py      # 规范与红线校验
└── tools/                   # 评估工具
    └── eval_match.py        # 匹配准确率评估脚本
```

---

## 🛠️ 快速上手与本地测试

### 1. 运行自动化测试套件
本项目配备了完备的断言套件，验证匹配矩阵、时段边界、容差公式与缓存机制：

```bash
# 运行金丝雀校验套件（输出 CANARY 防伪码）
python3 tests/run_tests.py

# 或使用标准 unittest 收集运行
python3 -m unittest discover -s tests -v
```

### 2. 命令行脚本调用示例

#### A. 估算订单热量
```bash
python3 scripts/mcd_order.py --order fixtures/order.sample-01-lunch-combo.json
```

#### B. 按餐段与档位推荐可售组合
```bash
python3 scripts/mcd_combo.py \
  --menu fixtures/meals.3570190.dinein.lunch.json \
  --daypart 午餐 \
  --tier 标准档 \
  --sort balanced
```

#### C. 目标场景组合推荐（以高蛋白增肌为例）
```bash
python3 scripts/mcd_combo.py \
  --menu fixtures/meals.3570190.dinein.lunch.json \
  --daypart 午餐 \
  --goal high_protein \
  --top 3
```

#### D. 历史订单一键脱敏与分析
```bash
python3 scripts/mcd_import.py \
  --input fixtures/order-list.sample.json \
  --output data/my-history.json
```

---

## 🤖 在 AI Agent 中接入使用

### 1. 接入 WorkBuddy / Antigravity / Claude
1. **配置 MCP 服务**：在 Agent 的 MCP 配置中接入官方麦当劳服务：
   ```json
   {
     "mcpServers": {
       "mcd-mcp": {
         "url": "https://mcp.mcd.cn",
         "headers": {
           "Authorization": "Bearer YOUR_MCD_TOKEN"
         }
       }
     }
   }
   ```
2. **加载本 Skill**：将本仓库作为 Skill 目录挂载，Agent 会自动读取 [`SKILL.md`](SKILL.md) 中定义的上下文与触发词。
3. **日常对话触发**：
   * *“这单多少热量？订单号 20261010xxxx”*
   * *“早餐想吃个 300 大卡左右的轻食，帮我挑下”*
   * *“今天健身练完腿，来份高蛋白晚餐”*
   * *“导入我的历史订单分析热量”*

---

## 🔗 相关链接

* **在线演示页面（GitHub Pages）**：[https://orderye.github.io/mcd-calorie-skill/](https://orderye.github.io/mcd-calorie-skill/)
* **GitHub 项目主仓库**：[orderye/mcd-calorie-skill](https://github.com/orderye/mcd-calorie-skill)
* **CNB 代码仓库**：[toroyxxx/mcd-calorie-skill](https://cnb.cool/toroyxxx/mcd-calorie-skill)
