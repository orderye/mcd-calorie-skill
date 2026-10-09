#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd_goal.py — 目标场景策略层（G1，PRD F8）

在「餐段 × 档位」之上叠加一个「目标场景（goal）」维度。每个场景是一套营养策略
描述符，决定：推荐档位 / 目标热量 / 容差 / 硬上限 / 关键词排除 / 组合结构 / 排序评分。

场景不是医学建议——仍是热量/宏量的估算参考，不做"你应该吃多少"的处方
（PRD §8 红线不变）。

场景清单（13 个）：
【热量与体型】
- cut           减脂          热量偏低、蛋白密度高、钠偏低、少小食
- bulk          增重          热量盈余、蛋白与碳水双高、可加小食
- post          练后餐        蛋白优先、必含主食回补碳水
- cheat         放纵餐        热量上浮、允许甜品、性价比排序
【单一营养素管控】
- low-sodium    低钠控盐      钠硬上限 + 钠升序
- high-protein  高蛋白增肌    蛋白密度优先 + 蛋白总量（日常版）
- low-carb      低糖低碳水    碳水硬上限 + 碳水升序
- low-fat       低脂清淡      脂肪硬上限 + 脂肪升序
【结构 / 人群 / 场景】
- vegetarian    素食/蛋奶素   关键词排除肉类（蛋奶保留）
- kids          儿童/小份量   热量下浮 + 单品数 ≤2
- daily-budget  热量预算日控  以当日剩余预算为目标，不超预算
- allergen      过敏原规避    按过敏原展开关键词排除（粗筛，见告警）
- value         性价比/省钱   价格硬上限 + 价格升序

设计约束（沿用 PRD §6/§9 硬约束，不因场景而放宽）：
- 候选 100% 来自 query-meals 当前可售结果；
- 营养表无记录的商品不进入候选；
- 档位内无解 → 提示换档位，不放宽筛选范围。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

SKILL_ROOT = Path(__file__).resolve().parent.parent

# ────────────────────────── 关键词表 ──────────────────────────

# 蛋奶素排除：肉类/水产/肉制品。刻意避开"牛奶/燕麦奶"（蛋奶素可食），
# 故牛肉用「牛堡/双牛/安格斯」而非单字「牛」。
# 「汉堡」单列：麦当劳无素汉堡（吉士汉堡/双层吉士汉堡均为牛肉，菜名不含"牛"字）。
MEAT_KEYWORDS = [
    "鸡", "牛堡", "双牛", "安格斯", "巨无霸", "猪", "鱼", "鳕", "肉",
    "虾", "蟹", "培根", "火腿", "翅", "板烧", "麦辣", "脆汁",
    "不素之霸", "深海", "肠", "烟肉", "汉堡",
]

# 过敏原 → 关键词展开。菜单无配料/过敏原表，此处为**关键词粗筛**，
# 命中即排除；不保证覆盖全部隐性过敏原（输出带告警）。
ALLERGEN_KEYWORDS = {
    "花生": ["花生"],
    "坚果": ["花生", "坚果", "杏仁", "榛"],
    "乳制品": ["奶", "芝士", "吉士", "冰淇淋", "新地", "麦旋风", "圆筒",
               "阿芙佳朵", "卡布奇诺", "拿铁", "拉丝"],
    "奶": ["奶", "芝士", "吉士", "冰淇淋", "新地", "麦旋风", "圆筒",
           "阿芙佳朵", "卡布奇诺", "拉丝"],
    "蛋": ["蛋"],
    "麸质": ["堡", "麦满分", "卷", "派", "油条", "松饼", "华夫"],
    "小麦": ["堡", "麦满分", "卷", "派", "油条", "松饼", "华夫"],
    "大豆": ["豆浆", "豆腐", "毛豆"],
    "鱼": ["鱼", "鳕"],
    "甲壳类": ["虾", "蟹"],
    "海鲜": ["鱼", "鳕", "虾", "蟹"],
}

# ────────────────────────── 场景定义 ──────────────────────────
# 字段说明：
#   prefer_tier      推荐档位（轻量/标准/吃饱）
#   tolerance        筛选容差（默认 ±12%）
#   range_from/to    可选，直接指定区间系数（覆盖 tolerance）
#   max_snacks       组合中小食上限
#   allow_dessert    是否允许甜品进入候选池
#   require_staple   是否必须含主食
#   max_items        组合总件数上限（None=不限）
#   target_scale     目标热量缩放（儿童小份量用）
#   target_from_param 目标热量取自入参（如 budget）
#   limits           硬上限：sodium_mg / carb / fat / price
#   exclude_keywords 候选池关键词排除（素食）
#   param_exclude    从入参取排除关键词（allergens）
#   min_protein_g    软目标：仅用于话术，不硬筛
#   sort             默认排序器键

GOALS: dict[str, dict] = {
    # ── 热量与体型（原有 4 个）──
    "cut": {
        "label": "减脂", "prefer_tier": "轻量", "tolerance": 0.12,
        "max_snacks": 1, "allow_dessert": False, "min_protein_g": 15, "sort": "cut",
    },
    "bulk": {
        "label": "增重", "prefer_tier": "吃饱", "tolerance": 0.12,
        "max_snacks": 2, "allow_dessert": True, "min_protein_g": 20, "sort": "bulk",
    },
    "post": {
        "label": "练后餐", "prefer_tier": "标准", "tolerance": 0.12,
        "max_snacks": 1, "allow_dessert": False, "min_protein_g": 20,
        "require_staple": True, "sort": "post",
    },
    "cheat": {
        "label": "放纵餐", "prefer_tier": "吃饱", "tolerance": 0.15,
        "max_snacks": 2, "allow_dessert": True, "min_protein_g": 0, "sort": "cheat",
    },
    # ── 单一营养素管控 ──
    "low-sodium": {
        "label": "低钠控盐", "prefer_tier": "轻量", "tolerance": 0.12,
        "max_snacks": 1, "allow_dessert": False, "sort": "low-sodium",
        "limits": {"sodium_mg": 1000},   # 默认硬上限，--sodium-max 可覆盖（0=关闭）
    },
    "high-protein": {
        "label": "高蛋白增肌", "prefer_tier": "标准", "tolerance": 0.12,
        "max_snacks": 1, "allow_dessert": False, "min_protein_g": 25, "sort": "high-protein",
    },
    "low-carb": {
        "label": "低糖低碳水", "prefer_tier": "轻量", "tolerance": 0.12,
        "max_snacks": 1, "allow_dessert": False, "sort": "low-carb",
        "limits": {"carb": 60},          # 默认碳水上限(g)，--carb-max 可覆盖
    },
    "low-fat": {
        "label": "低脂清淡", "prefer_tier": "轻量", "tolerance": 0.12,
        "max_snacks": 1, "allow_dessert": False, "sort": "low-fat",
        "limits": {"fat": 30},           # 默认脂肪上限(g)，--fat-max 可覆盖
    },
    # ── 结构 / 人群 / 场景 ──
    "vegetarian": {
        # 门店午餐几乎无素食主食（实测候选池主食 0 项），故降到轻量档并以
        # 拼小食/甜品/饮品达档；早餐有蛋麦满分等可选。
        "label": "素食/蛋奶素", "prefer_tier": "轻量", "tolerance": 0.12,
        "max_snacks": 3, "allow_dessert": True, "sort": "near",
        "exclude_keywords": MEAT_KEYWORDS,
        "allow_snack_combo": True,   # 无主食 → 允许纯小食拼组达档
    },
    "kids": {
        "label": "儿童/小份量", "prefer_tier": "轻量", "tolerance": 0.15,
        "max_snacks": 1, "allow_dessert": True, "max_items": 2,
        "target_scale": 0.85, "sort": "small",
    },
    "daily-budget": {
        "label": "热量预算日控", "prefer_tier": "标准",
        "range_from": 0.70, "range_to": 1.00,   # 用满预算但不超
        "max_snacks": 2, "allow_dessert": True, "sort": "budget",
        "target_from_param": "budget",
    },
    "allergen": {
        "label": "过敏原规避", "prefer_tier": "标准", "tolerance": 0.12,
        "max_snacks": 2, "allow_dessert": True, "sort": "near",
        "param_exclude": "allergens",
    },
    "value": {
        "label": "性价比/省钱", "prefer_tier": "标准", "tolerance": 0.12,
        "max_snacks": 1, "allow_dessert": True, "sort": "value",
        "limits": {"price": None},       # 由 --price-max 决定（未给则只做价格升序）
    },
}

GOAL_ORDER = list(GOALS)

# ────────────────────────── 评分器 ──────────────────────────
# 统一签名：(totals, ctx) -> 可比较元组（越小越优先）。
# ctx = {"target": int, ...}。totals 字段：kcal/protein/fat/carb/sodium_mg/price。

Scorer = Callable[[dict, dict], tuple]


def _protein_density(t: dict) -> float:
    """蛋白密度：每 100 kcal 的蛋白克数，避免只堆高热量高蛋白。"""
    return t["protein"] / max(t["kcal"], 1) * 100


def _gap(t: dict, ctx: dict) -> float:
    return abs(t["kcal"] - ctx["target"])


def _cut_score(t: dict, ctx: dict) -> tuple:
    """减脂：蛋白密度优先（高蛋白低热量=饱腹感强）> 热量贴近 > 钠低。"""
    over = max(0, t["kcal"] - ctx["target"])
    return (-_protein_density(t), _gap(t, ctx) + over * 2, t["sodium_mg"])


def _bulk_score(t: dict, ctx: dict) -> tuple:
    """增重：热量贴近（宁高勿低）> 蛋白+碳水高 > 价格低。"""
    under = max(0, ctx["target"] - t["kcal"])
    return (_gap(t, ctx) + under * 2, -(t["protein"] + t["carb"] * 0.5), t["price"])


def _post_score(t: dict, ctx: dict) -> tuple:
    """练后餐：蛋白总量优先 > 热量贴近 > 碳水回补。"""
    return (-t["protein"], _gap(t, ctx), -t["carb"])


def _cheat_score(t: dict, ctx: dict) -> tuple:
    """放纵餐：满足感优先——热量贴近 > 价格低。"""
    return (_gap(t, ctx), t["price"])


def _low_sodium_score(t: dict, ctx: dict) -> tuple:
    """低钠控盐：钠最低优先 > 热量贴近。"""
    return (t["sodium_mg"], _gap(t, ctx))


def _high_protein_score(t: dict, ctx: dict) -> tuple:
    """高蛋白增肌：蛋白密度优先 > 蛋白总量 > 热量贴近。"""
    return (-_protein_density(t), -t["protein"], _gap(t, ctx))


def _low_carb_score(t: dict, ctx: dict) -> tuple:
    """低糖低碳水：碳水最低优先 > 热量贴近。"""
    return (t["carb"], _gap(t, ctx))


def _low_fat_score(t: dict, ctx: dict) -> tuple:
    """低脂清淡：脂肪最低优先 > 热量贴近。"""
    return (t["fat"], _gap(t, ctx))


def _small_score(t: dict, ctx: dict) -> tuple:
    """儿童/小份量：区间内热量越低越好（小份），再比价格。"""
    return (t["kcal"], t["price"])


def _budget_score(t: dict, ctx: dict) -> tuple:
    """热量预算日控：用满预算但不超（越接近预算越好）> 蛋白高。"""
    return (_gap(t, ctx), -t["protein"])


def _value_score(t: dict, ctx: dict) -> tuple:
    """性价比/省钱：价格最低优先 > 热量贴近。"""
    return (t["price"], _gap(t, ctx))


GOAL_SCORERS: dict[str, Scorer] = {
    "cut": _cut_score,
    "bulk": _bulk_score,
    "post": _post_score,
    "cheat": _cheat_score,
    "low-sodium": _low_sodium_score,
    "high-protein": _high_protein_score,
    "low-carb": _low_carb_score,
    "low-fat": _low_fat_score,
    "small": _small_score,
    "budget": _budget_score,
    "value": _value_score,
}

GOAL_DESCRIPTIONS = {
    "cut":   "目标：热量偏低 + 蛋白相对高 + 钠偏低，控制小食与甜品",
    "bulk":  "目标：热量盈余 + 蛋白与碳水双高，可加小食与饮品",
    "post":  "目标：蛋白优先 + 必含主食回补碳水，练后尽快补充",
    "cheat": "目标：热量上浮、允许甜品，偶尔放松一次",
    "low-sodium":   "目标：整组钠不超上限，钠越低越靠前",
    "high-protein": "目标：蛋白密度优先（日常增肌版），兼顾蛋白总量",
    "low-carb":     "目标：整组碳水不超上限，碳水越低越靠前",
    "low-fat":      "目标：整组脂肪不超上限，脂肪越低越靠前",
    "vegetarian":   "目标：排除肉类/水产（蛋奶可食），关键词粗筛",
    "kids":         "目标：热量下浮、份量小，单组最多 2 件",
    "daily-budget": "目标：按当日剩余预算配餐，用满但不超预算",
    "allergen":     "目标：按过敏原关键词排除，粗筛仅作提示",
    "value":        "目标：价格优先（省钱），兼顾热量贴近",
}


# ────────────────────────── 公共接口 ──────────────────────────

def get_goal(goal: Optional[str]) -> Optional[dict]:
    """取场景定义；None（未指定）→ 回退到纯档位模式。"""
    if not goal:
        return None
    return GOALS.get(goal)


def _load_category_rules() -> dict:
    return json.loads((SKILL_ROOT / "data" / "category-rules.json").read_text(encoding="utf-8"))


def resolve_plan(daypart: str, tier: str, goal: Optional[str],
                 params: Optional[dict] = None) -> dict:
    """把「餐段 × 档位 × 场景 × 入参」解析成一份可执行的推荐计划。

    返回 dict：goal/label/tier_used/target/lo/hi/exclude_keywords/limits/
    max_items/allow_dessert/max_snacks/require_staple/sort/warning。
    """
    import mcd_daypart as dp  # 延迟导入避免循环
    params = params or {}
    g = get_goal(goal)

    # ── 无场景：纯档位模式 ──
    if not g:
        target = dp.tier_target(daypart, tier)
        tol = params.get("tolerance") or 0.12
        return {
            "goal": None, "label": None, "tier_used": tier, "target": target,
            "lo": round(target * (1 - tol)), "hi": round(target * (1 + tol)),
            "exclude_keywords": [], "limits": {}, "max_items": None,
            "allow_dessert": True, "max_snacks": 2, "require_staple": False,
            "allow_snack_combo": False,
            "sort": None, "warning": None,
        }

    # ── 目标档位与目标热量 ──
    tier_used = g["prefer_tier"]
    target = dp.tier_target(daypart, tier_used)
    target = int(round(target * g.get("target_scale", 1.0)))
    if g.get("target_from_param"):
        v = params.get(g["target_from_param"])
        if v:
            target = int(v)

    # ── 区间 ──
    if "range_from" in g or "range_to" in g:
        lo = target * g.get("range_from", 0.88)
        hi = target * g.get("range_to", 1.12)
    else:
        tol = g.get("tolerance", 0.12)
        lo, hi = target * (1 - tol), target * (1 + tol)

    # ── 硬上限（场景默认 + 入参覆盖；0 或负数 = 关闭）──
    limits = dict(g.get("limits") or {})
    if params.get("sodium_max") is not None:
        limits["sodium_mg"] = params["sodium_max"]
    if params.get("carb_max") is not None:
        limits["carb"] = params["carb_max"]
    if params.get("fat_max") is not None:
        limits["fat"] = params["fat_max"]
    if params.get("price_max") is not None:
        limits["price"] = params["price_max"]
    if params.get("budget") is not None:
        limits["kcal_max"] = params["budget"]
    limits = {k: float(v) for k, v in limits.items() if v and v > 0}

    # 预算场景：上界收紧到预算（不超），并保底下界
    if limits.get("kcal_max"):
        hi = min(hi, limits["kcal_max"])
        lo = min(lo, hi * 0.95)

    # ── 关键词排除（素食 + 过敏原）──
    exclude = list(g.get("exclude_keywords") or [])
    warning = None
    if g.get("param_exclude") == "allergens":
        names = params.get("allergens") or []
        for a in names:
            exclude.extend(ALLERGEN_KEYWORDS.get(a, [a]))
        if names:
            warning = ("过敏原为关键词粗筛（菜单无配料/过敏原表），结果不完整，"
                       "务必以门店配料与员工确认为准")
    if g.get("exclude_keywords"):
        warning = "素食为关键词粗筛（菜单无配料表），可能遗漏隐性动物成分，请自行确认"

    # ── 上限关闭时告知 ──
    target_scale = g.get("target_scale")

    return {
        "goal": goal, "label": g["label"], "tier_used": tier_used, "target": target,
        "lo": round(lo), "hi": round(hi),
        "exclude_keywords": sorted(set(exclude)),
        "limits": limits,
        "max_items": params.get("max_items") if params.get("max_items") is not None
        else g.get("max_items"),
        "allow_dessert": g["allow_dessert"],
        "max_snacks": g["max_snacks"],
        "require_staple": bool(g.get("require_staple")),
        "allow_snack_combo": bool(g.get("allow_snack_combo")),
        "sort": g["sort"],
        "min_protein_g": g.get("min_protein_g", 0),
        "warning": warning,
    }


def filter_pools(pools: dict, plan: dict) -> dict:
    """按计划过滤候选池（不改原池，返回过滤副本）。

    - exclude_keywords：素食/过敏原的池级排除（该商品在任何组合中都不出现）；
    - !allow_dessert：按 dessertKeywords 剔除甜品（本 skill 甜品归入「小食」池）。
    """
    filtered = {k: list(v) for k, v in pools.items()}
    kw = plan.get("exclude_keywords") or []
    if kw:
        for k in filtered:
            filtered[k] = [it for it in filtered[k]
                           if not any(w in it["name"] for w in kw)]
    if not plan.get("allow_dessert", True):
        dessert_kw = _load_category_rules().get("dessertKeywords", [])
        filtered["小食"] = [it for it in filtered["小食"]
                            if not any(w in it["name"] for w in dessert_kw)]
    return filtered


def combo_allowed(c: list[dict], plan: dict) -> bool:
    """组合级硬约束（件数 / 各类上限）。返回 False 则该组合被剔除。"""
    max_items = plan.get("max_items")
    if max_items and len(c) > max_items:
        return False
    return True


def totals_allowed(t: dict, plan: dict) -> bool:
    """整组硬上限校验（钠/碳水/脂肪/价格/预算）。返回 False 则剔除。"""
    lim = plan.get("limits") or {}
    if lim.get("sodium_mg") and t["sodium_mg"] > lim["sodium_mg"]:
        return False
    if lim.get("carb") and t["carb"] > lim["carb"]:
        return False
    if lim.get("fat") and t["fat"] > lim["fat"]:
        return False
    if lim.get("price") and t["price"] > lim["price"]:
        return False
    if lim.get("kcal_max") and t["kcal"] > lim["kcal_max"]:
        return False
    return True


def describe_goal(goal: Optional[str]) -> str:
    """场景说明话术（用于输出头部与 SKILL.md 引用）。"""
    if not goal:
        return ""
    return GOAL_DESCRIPTIONS.get(goal, "")


def format_limits(plan: dict) -> str:
    """把生效的硬上限/排除条件渲染成一行提示。"""
    lim = plan.get("limits") or {}
    parts = []
    if lim.get("sodium_mg"):
        parts.append(f"钠≤{lim['sodium_mg']:.0f}mg")
    if lim.get("carb"):
        parts.append(f"碳水≤{lim['carb']:.0f}g")
    if lim.get("fat"):
        parts.append(f"脂肪≤{lim['fat']:.0f}g")
    if lim.get("price"):
        parts.append(f"价格≤¥{lim['price']:.1f}")
    if lim.get("kcal_max"):
        parts.append(f"热量≤{lim['kcal_max']:.0f}kcal")
    if plan.get("max_items"):
        parts.append(f"≤{plan['max_items']}件")
    if plan.get("exclude_keywords"):
        parts.append(f"排除 {len(plan['exclude_keywords'])} 个关键词")
    return "；".join(parts)


if __name__ == "__main__":
    print("=== 场景清单 ===")
    for g in GOAL_ORDER:
        d = GOALS[g]
        print(f"  {g:<13} {d['label']:<8} 档位={d['prefer_tier']:<4} "
              f"排序={d['sort']:<12} {describe_goal(g)}")
    print("\n=== 计划解析示例（午餐·标准档）===")
    demos = [
        (None, {}),
        ("cut", {}),
        ("low-sodium", {}),
        ("low-sodium", {"sodium_max": 800}),
        ("daily-budget", {"budget": 600}),
        ("kids", {}),
        ("allergen", {"allergens": ["花生", "乳制品"]}),
        ("value", {"price_max": 30}),
    ]
    for g, p in demos:
        plan = resolve_plan("午餐", "标准", g, p)
        print(f"  goal={str(g):<13} → 档位={plan['tier_used']:<4} "
              f"目标={plan['target']:>4} 区间={plan['lo']}-{plan['hi']} "
              f"| {format_limits(plan)}")
