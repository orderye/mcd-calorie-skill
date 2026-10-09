#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd_combo.py — 品类归类与推荐引擎（T18/T19/T20/T21/T22）

数据流：菜单 fixture（query-meals 精简版）→ 过滤 → 品类归类 → 营养匹配 →
组合枚举 → ±12% 档位筛选 → 四选一排序 → Top 3–4。

硬约束（PRD §6/§9）：
- 候选 100% 来自 query-meals 当前可售结果；
- 营养表无记录的商品不进入候选；
- 档位内无解 → 提示换档位，不放宽筛选范围。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcd_nutrition import Matcher, load_nutrition, normalize_name          # noqa: E402
import mcd_daypart as dp                                                    # noqa: E402
import mcd_goal as goalmod                                                 # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parent.parent
RULES = json.loads((SKILL_ROOT / "data" / "category-rules.json").read_text(encoding="utf-8"))

# 菜单分类名 → 品类（第一级，权威来源之一）
_MENU_CAT = []
for cat, names in RULES["menuCategoryMap"].items():
    _MENU_CAT.extend((n, cat) for n in names)


def _category_from_menu_name(menu_category: str) -> Optional[str]:
    low = menu_category.replace("\n", "")
    for frag, cat in _MENU_CAT:
        if frag in low:
            return cat
    return None


def _excluded(name: str) -> Optional[str]:
    for p in RULES["excludeNamePatterns"]:
        if p in name:
            return p
    return None


def _keyword_category(name: str) -> Optional[str]:
    """第三级兜底。顺序：甜品/冰淇淋 → 饮品 → 主食 → 小食。"""
    for kw in RULES["dessertKeywords"]:
        if kw in name:
            return "小食"
    for kw in RULES["drinkKeywords"]:
        if kw in name:
            return "饮品"
    for kw in RULES["stapleKeywords"]:
        if kw in name:
            return "主食"
    for kw in RULES["snackKeywords"]:
        if kw in name:
            return "小食"
    return None


def load_menu(path: Path) -> tuple[dict, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cat_of: dict[str, str] = {}
    for c in data["categories"]:
        for code, _tags in c["items"]:
            cat = _category_from_menu_name(c["name"])
            if cat and code not in cat_of:
                cat_of[code] = cat
    return data, {"category": cat_of}


def build_pools(menu_path: Path, matcher: Matcher) -> dict:
    """过滤 + 匹配，产出主食/小食/饮品三个候选池及淘汰清单。"""
    data, aux = load_menu(menu_path)
    pools = {"主食": [], "小食": [], "饮品": []}
    dropped = {"非食品/组合品": [], "营养未知": []}

    for code, meal in data["meals"].items():
        name = meal["name"]
        reason = _excluded(name)
        if reason:
            dropped["非食品/组合品"].append(f"{name}（含“{reason}”）")
            continue
        cat = aux["category"].get(code) or _keyword_category(name)
        if cat is None:
            dropped["非食品/组合品"].append(f"{name}（品类无法判定）")
            continue
        rec = matcher.match(name)
        if rec["status"] != "hit":
            dropped["营养未知"].append(name)
            continue
        r = rec["record"]
        pools[cat].append({
            "code": code, "name": name, "category": cat,
            "price": float(meal.get("price") or 0),
            "kcal": r["kcal"], "protein": r["protein"], "fat": r["fat"],
            "carb": r["carb"], "sodium_mg": r["sodium_mg"],
        })

    for pool in pools.values():
        pool.sort(key=lambda x: x["kcal"])
    return {"pools": pools, "dropped": dropped, "menu": data}


# ────────────────────────── 组合枚举与推荐 ──────────────────────────

SORTERS = {
    "near":    lambda t, target: (abs(t["kcal"] - target), t["kcal"]),
    "protein": lambda t, target: (-t["protein"], abs(t["kcal"] - target)),
    "sodium":  lambda t, target: (t["sodium_mg"], abs(t["kcal"] - target)),
    "price":   lambda t, target: (t["price"], abs(t["kcal"] - target)),
    # 场景排序器（G1）：接收完整 totals，按场景营养策略评分。见 mcd_goal.GOAL_SCORERS。
    "cut":     goalmod._cut_score,
    "bulk":    goalmod._bulk_score,
    "post":    goalmod._post_score,
    "cheat":   goalmod._cheat_score,
}


def _agg(items: list[dict]) -> dict:
    keys = ("kcal", "protein", "fat", "carb", "sodium_mg", "price")
    return {k: round(sum(i[k] for i in items), 1) for k in keys}


def recommend(pools: dict, daypart: str, tier: str,
              sort_by: str = "near", top: int = 4,
              tolerance: float = 0.12,
              goal: str = None) -> dict:
    # 场景策略：目标热量（场景有自己的推荐档位）与容差。
    target = dp.tier_target(daypart, tier)
    tier_used = tier
    if goal:
        target, tier_used = goalmod.goal_target(daypart, tier, goal)
        tolerance = goalmod.goal_tolerance(goal)

    lo, hi = target * (1 - tolerance), target * (1 + tolerance)
    # 场景化候选池过滤（减脂/练后餐剔除甜品等）
    pools = goalmod.apply_goal_filters(pools, goal)

    # R4 剪枝：热量均非负，单项 > hi 的商品不可能出现在任何档内组合中；
    # 0 kcal 条目（无糖饮料等）合法保留。枚举前先剪，避免先爆炸后筛选。
    staples = [x for x in pools["主食"] if x["kcal"] <= hi]
    snacks = [x for x in pools["小食"] if x["kcal"] <= hi]
    drinks = [x for x in pools["饮品"] if x["kcal"] <= hi]

    # 场景组合规则（G1）：
    # - 练后餐要求必须含主食（碳水回补），去掉"纯小食/纯饮品"组合；
    # - 场景限制小食数量（减脂 0~1、增重/放纵 0~2）。
    require_staple = bool(goal and goalmod.get_goal(goal).get("require_staple"))
    max_snacks = goalmod.get_goal(goal)["max_snacks"] if goal else 2

    combos: list[list[dict]] = []
    if daypart == "随便吃吃":
        # 1–3 件小食/甜品/饮品，饮品 ≤1，无主食
        for s in snacks:
            combos.append([s])
            for d in drinks:
                combos.append([s, d])
        for d in drinks:
            combos.append([d])
        for i, s1 in enumerate(snacks):
            for s2 in snacks[i + 1:]:
                combos.append([s1, s2])
                for d in drinks:
                    combos.append([s1, s2, d])
    else:
        # 1 主食 + 0~N 小食 + 0~1 饮品（小食数量受场景 max_snacks 约束）
        for st in staples:
            base = [[st]]                                   # 仅主食
            for s in snacks:
                base.append([st, s])                        # 主食 + 1 小食
            for d in drinks:
                base.append([st, d])                        # 主食 + 1 饮品
            for s in snacks:
                for d in drinks:
                    base.append([st, s, d])                 # 主食 + 小食 + 饮品
            # 增重/放纵餐：主食 + 2 小食（无饮品）
            if max_snacks >= 2:
                for i, s1 in enumerate(snacks):
                    for s2 in snacks[i + 1:]:
                        base.append([st, s1, s2])
            combos.extend(base)

        # 非练后场景才允许"纯小食/纯饮品"（无主食）组合
        if not require_staple and max_snacks >= 1:
            for s in snacks:
                combos.append([s])
                for d in drinks:
                    combos.append([s, d])
            for d in drinks:
                combos.append([d])

    # 去重（同名组合）+ 档位筛选（不放宽）
    seen: set[tuple] = set()
    in_range = []
    for c in combos:
        key = tuple(sorted(x["name"] for x in c))
        if key in seen:
            continue
        seen.add(key)
        t = _agg(c)
        if lo <= t["kcal"] <= hi:
            # 场景软目标：蛋白下限（不硬筛，仅排序时由 scorer 体现；这里做轻量标记）
            in_range.append({"items": c, "totals": t})

    in_range.sort(key=lambda t: SORTERS.get(sort_by, SORTERS["near"])(t["totals"], target))
    return {"target": target, "range": [round(lo), round(hi)],
            "count": len(in_range), "results": in_range[:top],
            "tier_used": tier_used, "goal": goal}


def print_recommendation(res: dict, daypart: str, tier: str, sort_by: str) -> None:
    goal_txt = f" · {goalmod.get_goal(res['goal'])['label']}" if res.get("goal") else ""
    # 场景会自动切换推荐档位（如减脂→轻量档），标题显示实际生效档位而非入参 tier。
    shown_tier = res.get("tier_used") or tier
    print(f"\n推荐 · {daypart} · {shown_tier} 档{goal_txt}（目标 {res['target']} kcal，"
          f"区间 {res['range'][0]}–{res['range'][1]}，命中 {res['count']} 组，排序 {sort_by}）")
    if res.get("goal"):
        print(f"  场景策略：{goalmod.describe_goal(res['goal'])}")
    print("─" * 72)
    if not res["results"]:
        print("  档位内没有合适组合 → 建议换一个档位（不放宽筛选范围）")
        return
    for i, r in enumerate(res["results"], 1):
        names = " + ".join(x["name"] for x in r["items"])
        t = r["totals"]
        print(f"  {i}. {names}")
        print(f"     {t['kcal']:.0f} kcal｜蛋白 {t['protein']:.0f}g｜脂肪 {t['fat']:.0f}g｜"
              f"碳水 {t['carb']:.0f}g｜钠 {t['sodium_mg']:.0f}mg｜≈¥{t['price']:.1f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="档位套餐推荐（基于菜单 fixture）")
    ap.add_argument("--menu", required=True, help="菜单 fixture 路径")
    ap.add_argument("--daypart", required=True, choices=list(dp.TIERS))
    ap.add_argument("--tier", default="标准", choices=["轻量", "标准", "吃饱"])
    ap.add_argument("--goal", default=None, choices=[None, "cut", "bulk", "post", "cheat"],
                    help="目标场景：cut 减脂 / bulk 增重 / post 练后餐 / cheat 放纵餐")
    ap.add_argument("--sort", default="near", choices=list(SORTERS))
    ap.add_argument("--top", type=int, default=4)
    a = ap.parse_args()

    matcher = Matcher(load_nutrition())
    built = build_pools(Path(a.menu), matcher)
    print(f"候选池：主食 {len(built['pools']['主食'])}｜小食 {len(built['pools']['小食'])}｜"
          f"饮品 {len(built['pools']['饮品'])}")
    print(f"剔除：组合/非食品 {len(built['dropped']['非食品/组合品'])} 项，"
          f"营养未知 {len(built['dropped']['营养未知'])} 项")
    # 场景默认排序器（若未显式指定 --sort）
    sort_by = a.sort
    if a.goal and a.sort == "near":
        sort_by = goalmod.get_goal(a.goal)["sort"]
    res = recommend(built["pools"], a.daypart, a.tier, sort_by, a.top, goal=a.goal)
    print_recommendation(res, a.daypart, a.tier, sort_by)
