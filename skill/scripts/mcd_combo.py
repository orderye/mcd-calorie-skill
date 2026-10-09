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


_NONFOOD_PATTERNS = tuple(RULES.get("excludeNonFoodPatterns") or ())
_FOOD_HINTS = tuple(RULES.get("foodHintKeywords") or ())


def _excluded(name: str) -> Optional[str]:
    """返回命中的排除词；无则 None。

    两类排除词区别对待（v0.8）：
    - **组合品词**（套餐/件套/随心选…）：无条件排除——组合品不得进单品候选位（PRD D4）。
    - **非食品词**（蘸酱/风味酱/山葵酱…）：仅当**不与食物词共存**时才排除。
      「蘸酱炸鸡」「蘸酱麦麦脆汁鸡」「5块心形薯饼+韩式辣椒黄油风味酱」是含酱的**食物**，
      名字里有「鸡/薯/块」→ 不排除；否则会把一顿正餐挡在候选外（与
      build_demo_menu.is_zero 的判据一致）。
    """
    for p in RULES["excludeNamePatterns"]:
        if p in name:
            return p
    for p in _NONFOOD_PATTERNS:
        if p in name and not any(k in name for k in _FOOD_HINTS):
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

# 基础排序器 + 场景评分器。统一签名 (totals, ctx)，ctx 至少含 target。
BASE_SORTERS = {
    "near":    lambda t, ctx: (abs(t["kcal"] - ctx["target"]), t["kcal"]),
    "protein": lambda t, ctx: (-t["protein"], abs(t["kcal"] - ctx["target"])),
    "sodium":  lambda t, ctx: (t["sodium_mg"], abs(t["kcal"] - ctx["target"])),
    "price":   lambda t, ctx: (t["price"], abs(t["kcal"] - ctx["target"])),
}
# 合并场景评分器（cut/bulk/post/cheat/low-sodium/... 见 mcd_goal.GOAL_SCORERS）
SORTERS = {**BASE_SORTERS, **goalmod.GOAL_SCORERS}


def _agg(items: list[dict]) -> dict:
    keys = ("kcal", "protein", "fat", "carb", "sodium_mg", "price")
    return {k: round(sum(i[k] for i in items), 1) for k in keys}


def recommend(pools: dict, daypart: str, tier: str,
              sort_by: str = "near", top: int = 4,
              tolerance: float = 0.12,
              goal: str = None,
              params: Optional[dict] = None) -> dict:
    """推荐主入口。

    goal 指定目标场景；params 提供场景入参（budget / sodium_max / carb_max /
    fat_max / price_max / allergens / max_items）。未指定 goal 时走纯档位模式。
    """
    params = dict(params or {})
    if tolerance != 0.12:
        params.setdefault("tolerance", tolerance)
    plan = goalmod.resolve_plan(daypart, tier, goal, params)

    target, lo, hi = plan["target"], plan["lo"], plan["hi"]
    # 场景化候选池过滤（素食/过敏原关键词排除、减脂/低钠等剔除甜品）
    pools = goalmod.filter_pools(pools, plan)

    # R4 剪枝：热量均非负，单项 > hi 的商品不可能出现在任何档内组合中；
    # 0 kcal 条目（无糖饮料等）合法保留。枚举前先剪，避免先爆炸后筛选。
    staples = [x for x in pools["主食"] if x["kcal"] <= hi]
    snacks = [x for x in pools["小食"] if x["kcal"] <= hi]
    drinks = [x for x in pools["饮品"] if x["kcal"] <= hi]

    # 组合结构规则：练后餐必含主食；小食数量受场景 max_snacks 约束。
    require_staple = plan["require_staple"]
    max_snacks = plan["max_snacks"]
    allow_snack_combo = plan["allow_snack_combo"]

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
            # 增重/放纵等放开小食的场景：主食 + 2 小食（无饮品）
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
            # 素食等"无主食可拼"场景：放开 2~3 件小食/甜品达档
            if allow_snack_combo and max_snacks >= 2:
                for i, s1 in enumerate(snacks):
                    for s2 in snacks[i + 1:]:
                        combos.append([s1, s2])
                        for d in drinks:
                            combos.append([s1, s2, d])
                if max_snacks >= 3:
                    for i, s1 in enumerate(snacks):
                        for j, s2 in enumerate(snacks[i + 1:], i + 1):
                            for s3 in snacks[j + 1:]:
                                combos.append([s1, s2, s3])
                                for d in drinks:
                                    combos.append([s1, s2, s3, d])

    # 去重（同名组合）+ 档位筛选（不放宽）+ 组合级/整组级硬约束
    seen: set[tuple] = set()
    in_range = []
    for c in combos:
        if not goalmod.combo_allowed(c, plan):
            continue
        key = tuple(sorted(x["name"] for x in c))
        if key in seen:
            continue
        seen.add(key)
        t = _agg(c)
        if lo <= t["kcal"] <= hi and goalmod.totals_allowed(t, plan):
            in_range.append({"items": c, "totals": t})

    ctx = {"target": target, **plan}
    scorer = SORTERS.get(sort_by) or BASE_SORTERS["near"]
    in_range.sort(key=lambda r: scorer(r["totals"], ctx))
    return {"target": target, "range": [lo, hi],
            "count": len(in_range), "results": in_range[:top],
            "tier_used": plan["tier_used"], "goal": goal, "plan": plan}


def print_recommendation(res: dict, daypart: str, tier: str, sort_by: str) -> None:
    plan = res.get("plan") or {}
    goal_txt = f" · {plan.get('label')}" if res.get("goal") else ""
    # 场景会自动切换推荐档位（如减脂→轻量档），标题显示实际生效档位而非入参 tier。
    shown_tier = res.get("tier_used") or tier
    print(f"\n推荐 · {daypart} · {shown_tier} 档{goal_txt}（目标 {res['target']} kcal，"
          f"区间 {res['range'][0]}–{res['range'][1]}，命中 {res['count']} 组，排序 {sort_by}）")
    if res.get("goal"):
        print(f"  场景策略：{goalmod.describe_goal(res['goal'])}")
        lim = goalmod.format_limits(plan)
        if lim:
            print(f"  生效约束：{lim}")
        if plan.get("warning"):
            print(f"  ⚠ {plan['warning']}")
    print("─" * 72)
    if not res["results"]:
        print("  该条件下没有合适组合 → 建议放宽上限、换档位或换场景（不放宽热量筛选范围）")
        return
    for i, r in enumerate(res["results"], 1):
        names = " + ".join(x["name"] for x in r["items"])
        t = r["totals"]
        print(f"  {i}. {names}")
        print(f"     {t['kcal']:.0f} kcal｜蛋白 {t['protein']:.0f}g｜脂肪 {t['fat']:.0f}g｜"
              f"碳水 {t['carb']:.0f}g｜钠 {t['sodium_mg']:.0f}mg｜≈¥{t['price']:.1f}")


def _parse_allergens(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [s.strip() for s in raw.replace("，", ",").split(",") if s.strip()]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="档位套餐推荐（基于菜单 fixture）")
    ap.add_argument("--menu", required=True, help="菜单 fixture 路径")
    ap.add_argument("--daypart", required=True, choices=list(dp.TIERS))
    ap.add_argument("--tier", default="标准", choices=["轻量", "标准", "吃饱"])
    ap.add_argument("--goal", default=None, choices=goalmod.GOAL_ORDER,
                    help="目标场景（减脂/增重/练后餐/放纵餐/低钠控盐/高蛋白增肌/"
                         "低糖低碳水/低脂清淡/素食蛋奶素/儿童小份量/热量预算日控/"
                         "过敏原规避/性价比省钱）")
    ap.add_argument("--sort", default="near", choices=list(SORTERS))
    ap.add_argument("--top", type=int, default=4)
    # 场景入参（0 = 关闭该上限）
    ap.add_argument("--sodium-max", dest="sodium_max", type=float, default=None,
                    help="整组钠上限 mg（覆盖低钠控盐默认值；0=关闭）")
    ap.add_argument("--carb-max", dest="carb_max", type=float, default=None,
                    help="整组碳水上限 g（覆盖低糖低碳水默认值；0=关闭）")
    ap.add_argument("--fat-max", dest="fat_max", type=float, default=None,
                    help="整组脂肪上限 g（覆盖低脂清淡默认值；0=关闭）")
    ap.add_argument("--price-max", dest="price_max", type=float, default=None,
                    help="整组价格上限 元（性价比/省钱）")
    ap.add_argument("--budget", type=float, default=None,
                    help="当日剩余热量预算 kcal（热量预算日控）")
    ap.add_argument("--allergens", default=None,
                    help="过敏原，逗号分隔，如 花生,乳制品,蛋（过敏原规避）")
    ap.add_argument("--max-items", dest="max_items", type=int, default=None,
                    help="组合总件数上限")
    a = ap.parse_args()

    matcher = Matcher(load_nutrition())
    built = build_pools(Path(a.menu), matcher)
    print(f"候选池：主食 {len(built['pools']['主食'])}｜小食 {len(built['pools']['小食'])}｜"
          f"饮品 {len(built['pools']['饮品'])}")
    print(f"剔除：组合/非食品 {len(built['dropped']['非食品/组合品'])} 项，"
          f"营养未知 {len(built['dropped']['营养未知'])} 项")

    params = {
        "sodium_max": a.sodium_max, "carb_max": a.carb_max, "fat_max": a.fat_max,
        "price_max": a.price_max, "budget": a.budget, "max_items": a.max_items,
        "allergens": _parse_allergens(a.allergens),
    }
    # 场景默认排序器（若未显式指定 --sort）
    sort_by = a.sort
    if a.goal and a.sort == "near":
        sort_by = goalmod.get_goal(a.goal)["sort"]
    res = recommend(built["pools"], a.daypart, a.tier, sort_by, a.top,
                    goal=a.goal, params=params)
    print_recommendation(res, a.daypart, a.tier, sort_by)
