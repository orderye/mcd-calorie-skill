#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd_spec_evidence.py — 从「套餐默认搭配」反推菜单歧义商品的规格证据（T36）。

问题背景
--------
query-meals 的菜单名常缺规格（「薯条」「可乐」「玉米杯」「麦乐鸡」），
营养表却是规格维度（「中薯条」「可乐中杯」「小杯玉米杯」「麦乐鸡5块」），
Matcher 只能判 ambiguous（规格缺失），让用户二选一。

排查结论（2026-10-10 实测，见 PRD §12）
--------------------------------------
- list-nutrition-foods 是官方 MCP 里**唯一**的营养数据源；
- query-meals / query-meal-detail / query-order 的原始响应**均无营养字段**
  （query-meal-detail 最深只到 rounds[].choices[].{code,name,isDefault,diffPrice}）
  → 「从其他接口自采集热量」这条路不通；
- 但 query-meals 与 query-meal-detail **共享 code**：同一 code 指向同一商品，
  套餐里该 code 的具体命名（如 4437「小杯玉米杯」）即为菜单名（4437「玉米杯」）
  缺失的规格证据。这是本次唯一可落地的缺口收敛手段。

证据分级（决定能否自动补录）
---------------------------
  usable           菜单名未命中（ambiguous/unknown）且套餐名是其扩写 → 可补默认
  resolved         菜单名已命中且与套餐名指向同一营养条目 → 无需处理
  conflict-mapping 菜单名已命中，但命中的条目 ≠ 套餐证据 → **疑似错误映射，需人工**
  multivalue       菜单名自带多值标记（「（冰/热）」）或不构成包含关系 → 保持歧义
  conflict         同一 code 在不同套餐里出现多个规格 → 禁止补录

本脚本只做**离线证据挖掘**，不联网。`--apply` 仅写 A 级（usable）进
data/alias.json#defaults，其余一律不碰。

用法：
  python3 scripts/mcd_spec_evidence.py            # 证据报告
  python3 scripts/mcd_spec_evidence.py --json     # 结构化证据
  python3 scripts/mcd_spec_evidence.py --apply    # 把 A 级证据写回 alias.json#defaults
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcd_nutrition import Matcher, normalize_name, normalize_query  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parent.parent
FX = SKILL_ROOT / "fixtures"
ALIAS_FILE = SKILL_ROOT / "data" / "alias.json"

GRADE_ORDER = ("usable", "conflict-mapping", "multivalue", "conflict", "resolved")
GRADE_LABEL = {
    "usable": "A 可补录 · 菜单名未命中",
    "conflict-mapping": "C1 疑似错误映射（现网命中 ≠ 套餐证据）· 需人工",
    "multivalue": "B 保持歧义 · 多值或不可包含",
    "conflict": "C2 证据冲突 · 禁止补录",
    "resolved": "D 已解决 · 无需处理",
}


def _has_multivalue_marker(name: str) -> bool:
    """菜单名是否自带「多值」标记（一个 code 覆盖多规格）。

    实测：「浓浓黑巧（冰/热）」「浓浓燕麦黑巧（冰/热）」——括号内用 / 分隔冰热，
    营养表按冰/热分列；套餐里只出现冰款不足以证明该 code 唯一。
    这类必须保持歧义让用户选（PRD 已记录「浓浓黑巧」误配雪冰的坑）。
    """
    if "/" in name or "／" in name or "、" in name:
        return True
    return bool(re.search(r"任选|自选|可选", name))


def _iceheat_diff(menu_key: str, spec_key: str) -> bool:
    """规格名相对菜单名多出的字符里是否含「冰/热」。

    冰/热是**做法**差异（冰奶铁 148 vs 热奶铁 186，差 38 kcal），
    不是杯型/份数这类纯规格；菜单名省略冰/热时不能替用户锁定，
    必须保持歧义。故含冰/热 → 归 B（multivalue）。
    """
    diff = spec_key.replace(menu_key, "")
    return "冰" in diff or "热" in diff


# ────────────────────────── 证据采集 ──────────────────────────

def menu_names() -> dict[str, str]:
    """code -> 菜单名（所有 meals.*.json#meals；同 code 取首次出现的非空名）。"""
    out: dict[str, str] = {}
    for p in sorted(FX.glob("meals.*.json")):
        raw = json.loads(p.read_text(encoding="utf-8"))
        for code, ent in (raw.get("meals") or {}).items():
            name = (ent.get("name") or "").strip()
            if name and code not in out:
                out[str(code)] = name
    return out


def detail_names() -> dict[str, Counter]:
    """code -> 套餐里该 code 出现过的名称计数（所有 meal-detail.*.json）。"""
    out: dict[str, Counter] = defaultdict(Counter)
    for p in sorted(FX.glob("meal-detail.*.json")):
        raw = json.loads(p.read_text(encoding="utf-8"))
        for r in raw.get("rounds") or []:
            for c in r.get("choices") or []:
                code = str(c.get("code") or "")
                name = (c.get("name") or "").strip()
                if code and name:
                    out[code][name] += 1
    return out


def collect(matcher: Matcher) -> list[dict]:
    menus = menu_names()
    details = detail_names()
    rows: list[dict] = []

    for code, counter in sorted(details.items()):
        menu_name = menus.get(code)
        if not menu_name:
            continue
        menu_res = matcher.match(menu_name)

        variants = [n for n in counter if normalize_name(n) != normalize_name(menu_name)]
        specs: dict[str, dict] = {}          # record.name -> {origin, kcal, count}
        for n in variants:
            r = matcher.match(n)
            if r["status"] != "hit":
                continue
            rn = r["record"]["name"]
            slot = specs.setdefault(rn, {"origin": n, "kcal": r["record"]["kcal"], "count": 0})
            slot["count"] += counter[n]
        if not specs:
            continue

        rec_names = sorted(specs)
        mkey = normalize_name(menu_name)
        substring = [rn for rn in rec_names if mkey and mkey in normalize_name(rn)]

        if len(rec_names) > 1:
            grade = "conflict"
        elif menu_res["status"] == "hit":
            grade = ("resolved" if menu_res["record"]["name"] == rec_names[0]
                     else "conflict-mapping")
        elif (_has_multivalue_marker(menu_name) or not substring
              or _iceheat_diff(mkey, normalize_name(rec_names[0]))):
            grade = "multivalue"
        else:
            grade = "usable"

        rows.append({
            "grade": grade,
            "code": code,
            "menuName": menu_name,
            "menuMatched": menu_res["status"],
            "menuHit": menu_res["record"]["name"] if menu_res["status"] == "hit" else None,
            "specs": {rn: specs[rn] for rn in rec_names},
            "inDefaults": normalize_query(menu_name) in matcher.defaults,
        })

    return sorted(rows, key=lambda r: (GRADE_ORDER.index(r["grade"]), r["menuName"]))


# ────────────────────────── 报告 / 落库 ──────────────────────────

def report(rows: list[dict]) -> None:
    print("=" * 72)
    print("套餐默认搭配 → 菜单规格证据（code 级）")
    print("=" * 72)
    for grade in GRADE_ORDER:
        group = [r for r in rows if r["grade"] == grade]
        if not group:
            continue
        print(f"\n【{GRADE_LABEL[grade]}】{len(group)} 条")
        for r in group:
            rn, slot = next(iter(r["specs"].items()))
            extra = " [已在 defaults]" if r["inDefaults"] else ""
            if grade == "conflict-mapping":
                print(f"  ⚠ {r['menuName']:<12} code={r['code']:<11}"
                      f" 现网命中「{r['menuHit']}」≠ 套餐证据「{rn}」"
                      f"（{slot['kcal']:.0f} kcal, ×{slot['count']}）")
            elif grade == "conflict":
                print(f"  ✗ {r['menuName']:<12} code={r['code']:<11}"
                      f" → {list(r['specs'])}")
            else:
                print(f"  {'✓' if grade == 'usable' else '·'} {r['menuName']:<12}"
                      f" code={r['code']:<11} → {rn:<14}"
                      f" {slot['kcal']:>4.0f} kcal  ×{slot['count']} 引用{extra}")


def apply_defaults(rows: list[dict]) -> list[str]:
    """仅把 A 级（usable）写进 alias.json#defaults。键 = 菜单名归一化。

    纪律：不改 mappings；conflict-mapping / multivalue / conflict 一律不碰，
    保持歧义让用户选择（PRD §7 / alias.json 既有约定）。
    """
    data = json.loads(ALIAS_FILE.read_text(encoding="utf-8"))
    defaults: dict[str, str] = data.setdefault("defaults", {})

    added: list[str] = []
    for r in rows:
        if r["grade"] != "usable":
            continue
        key = normalize_query(r["menuName"])
        val = next(iter(r["specs"]))
        if key in defaults:
            continue
        defaults[key] = val
        added.append(f"{r['menuName']} → {val}")

    data["_defaults_note"] = (
        "defaults 仅在有实测证据时写入：query-meal-detail 套餐默认项 isDefault=1，"
        "或 scripts/mcd_spec_evidence.py 从「同一 code 在套餐里的具体命名」反推（A 级）。"
        "仅订单/套餐上下文启用；无证据或多值（冰/热）的歧义一律保持 ambiguous，禁止猜测。"
    )
    ALIAS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    return added


def main() -> None:
    ap = argparse.ArgumentParser(description="套餐默认搭配 → 菜单规格证据挖掘")
    ap.add_argument("--json", action="store_true", help="输出结构化证据")
    ap.add_argument("--apply", action="store_true", help="把 A 级证据写回 alias.json#defaults")
    a = ap.parse_args()

    matcher = Matcher()
    rows = collect(matcher)

    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    report(rows)

    if a.apply:
        added = apply_defaults(rows)
        print(f"\n已写入 alias.json#defaults: {len(added)} 条")
        for x in added:
            print(f"  + {x}")


if __name__ == "__main__":
    main()
