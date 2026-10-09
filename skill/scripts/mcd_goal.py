#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd_goal.py — 目标场景策略层（G1，PRD F8）

在「餐段 × 档位」之上叠加一个「目标场景（goal）」维度。四个场景各自是一套
营养策略描述符，决定：目标热量系数、宏量营养素排序权重、组合结构规则、输出话术。

场景不是医学建议——仍是热量/宏量的估算参考，不做"你应该吃多少"的处方
（PRD §8 红线不变）。

四个场景：
- 减脂 (cut)     目标：热量偏低、蛋白相对高、钠偏低、少加小食。
- 增重 (bulk)    目标：热量盈余、蛋白与碳水都高、允许加小食与饮品。
- 练后餐 (post)  目标：蛋白优先、必须含主食（碳水回补）、可选加小食。
- 放纵餐 (cheat) 目标：热量上浮、允许甜品、排序偏向"美味/性价比"。

设计约束（沿用 PRD §6/§9 硬约束，不因场景而放宽）：
- 候选 100% 来自 query-meals 当前可售结果；
- 营养表无记录的商品不进入候选；
- 档位内无解 → 提示换档位，不放宽筛选范围。
"""
from __future__ import annotations

from typing import Callable, Optional

# 场景 → 档位目标热量系数（相对「标准」档，kcal 乘法系数）。
# 减脂取「轻量」档（已在 goal_tier 处理），此处系数只用于"标准档"内的微调。
# 更干净的做法：场景直接映射到一个「推荐档位」+ 一个「容差系数」。
GOALS: dict[str, dict] = {
    # 减脂：默认落到「轻量」档，±12% 不变；额外给蛋白/钠加分，小食限 0~1。
    "cut": {
        "label": "减脂",
        "prefer_tier": "轻量",
        "tolerance": 0.12,
        "max_snacks": 1,          # 组合里小食上限（更紧）
        "allow_dessert": False,   # 减脂不放甜品进候选
        "min_protein_g": 15,      # 软目标：整组蛋白 ≥ 此值优先（不硬筛）
        "sort": "cut",            # 默认排序器
    },
    # 增重：落到「吃饱」档，蛋白与碳水双高，小食/饮品都放开。
    "bulk": {
        "label": "增重",
        "prefer_tier": "吃饱",
        "tolerance": 0.12,
        "max_snacks": 2,          # 允许加一个小食 + 一个甜品
        "allow_dessert": True,
        "min_protein_g": 20,
        "sort": "bulk",
    },
    # 练后餐：仍用「标准」档，但蛋白/碳水优先，必须含主食。
    "post": {
        "label": "练后餐",
        "prefer_tier": "标准",
        "tolerance": 0.12,
        "max_snacks": 1,
        "allow_dessert": False,
        "min_protein_g": 20,      # 练后蛋白要求更高
        "sort": "post",
        "require_staple": True,   # 必须有主食（碳水回补）
    },
    # 放纵餐：热量上浮到「吃饱」档，允许甜品，排序偏向性价比/满足感。
    "cheat": {
        "label": "放纵餐",
        "prefer_tier": "吃饱",
        "tolerance": 0.15,        # 放纵餐容差放宽到 ±15%（允许略超）
        "max_snacks": 2,
        "allow_dessert": True,
        "min_protein_g": 0,
        "sort": "cheat",
    },
}

# 场景 → 排序键名。与 mcd_combo.SORTERS 对齐，但场景排序器需要完整 totals（含宏量）。
# 这里定义"评分函数"，返回一个可比较元组（越小越优先）。
# totals 字段：kcal / protein / fat / carb / sodium_mg / price。
Scorer = Callable[[dict, int], tuple]


def _protein_density(t: dict) -> float:
    """蛋白密度：每 100 kcal 的蛋白克数，避免只堆高热量高蛋白。"""
    return t["protein"] / max(t["kcal"], 1) * 100


def _cut_score(t: dict, target: int) -> tuple:
    """减脂：蛋白密度优先（高蛋白低热量=饱腹感强）> 热量贴近目标 > 钠低。

    候选已落在档位 ±12% 区间内（由 recommend 保证），故排序阶段可让蛋白密度
    成为主键，把"吃得饱还低热量"的组合排到最前；热量贴近作为次级键兜底。
    """
    over = max(0, t["kcal"] - target)          # 超标惩罚项
    return (-_protein_density(t),               # 每 100 kcal 蛋白克数，高者优先
            abs(t["kcal"] - target) + over * 2,
            t["sodium_mg"])


def _bulk_score(t: dict, target: int) -> tuple:
    """增重：热量贴近目标（宁高勿低）> 蛋白+碳水高 > 价格低（吃得多还得划算）。"""
    under = max(0, target - t["kcal"])          # 不足惩罚项
    gap = abs(t["kcal"] - target)
    return (gap + under * 2,
            -(t["protein"] + t["carb"] * 0.5),  # 蛋白优先，碳水次之
            t["price"])


def _post_score(t: dict, target: int) -> tuple:
    """练后餐：蛋白总量优先 > 热量贴近目标 > 碳水回补。"""
    return (-t["protein"],
            abs(t["kcal"] - target),
            -t["carb"])


def _cheat_score(t: dict, target: int) -> tuple:
    """放纵餐：满足感优先——热量贴近目标 > 价格低（性价比）。"""
    return (abs(t["kcal"] - target),
            t["price"])


GOAL_SCORERS: dict[str, Scorer] = {
    "cut":   _cut_score,
    "bulk":  _bulk_score,
    "post":  _post_score,
    "cheat": _cheat_score,
}


def get_goal(goal: Optional[str]) -> Optional[dict]:
    """取场景定义；None（未指定）→ 回退到纯档位模式。"""
    if not goal:
        return None
    return GOALS.get(goal)


def goal_target(daypart: str, tier: str, goal: Optional[str]) -> int:
    """场景热量目标：场景有自己的推荐档位，未指定场景时用原档位。

    返回 (target, tier_used)。目标 = 该餐段 × 该档位的标准值。
    """
    import mcd_daypart as dp  # 延迟导入避免循环
    g = get_goal(goal)
    tier_used = g["prefer_tier"] if g else tier
    return dp.tier_target(daypart, tier_used), tier_used


def goal_tolerance(goal: Optional[str]) -> float:
    g = get_goal(goal)
    return g["tolerance"] if g else 0.12


def apply_goal_filters(pools: dict, goal: Optional[str]) -> dict:
    """场景化候选池过滤（不改原池，返回过滤副本）。

    - 减脂 / 练后餐：剔除甜品（按 category 已归为「小食」，需按名称关键词再判）。
      注：本 skill 的品类三级归类把甜品归入「小食」池，故"剔除甜品"通过
      dessert 关键词 + category-rules 的 dessertKeywords 二次过滤实现。
    """
    g = get_goal(goal)
    if not g or g["allow_dessert"]:
        return pools

    # 读取甜品关键词（与 mcd_combo 一致）
    from pathlib import Path
    import json
    root = Path(__file__).resolve().parent.parent
    rules = json.loads((root / "data" / "category-rules.json").read_text(encoding="utf-8"))
    dessert_kw = rules.get("dessertKeywords", [])

    filtered = {k: list(v) for k, v in pools.items()}
    if "小食" in filtered:
        kept = []
        for item in filtered["小食"]:
            if any(kw in item["name"] for kw in dessert_kw):
                continue  # 甜品剔除
            kept.append(item)
        filtered["小食"] = kept
    return filtered


def describe_goal(goal: Optional[str]) -> str:
    """场景说明话术（用于输出头部与 SKILL.md 引用）。"""
    g = get_goal(goal)
    if not g:
        return ""
    return {
        "cut":   "目标：热量偏低 + 蛋白相对高 + 钠偏低，控制小食与甜品",
        "bulk":  "目标：热量盈余 + 蛋白与碳水双高，可加小食与饮品",
        "post":  "目标：蛋白优先 + 必含主食回补碳水，练后尽快补充",
        "cheat": "目标：热量上浮、允许甜品，偶尔放松一次",
    }[goal]


if __name__ == "__main__":
    for g in ("cut", "bulk", "post", "cheat"):
        print(f"{g:>6} → {describe_goal(g)}")
    # 目标热量示例：午餐标准档 750
    for g in (None, "cut", "bulk", "post", "cheat"):
        t, tier = goal_target("午餐", "标准", g)
        print(f"goal={g} → tier={tier}, target={t}, tol={goal_tolerance(g)}")
