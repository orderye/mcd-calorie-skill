#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd_order.py — 订单热量估算与档位对比（T11/T12/T13/T14）

输入：订单 fixture（query-order 精简结构）+ 餐段/档位。
纪律：
- 套餐按 comboItemList 展开，无组成项按商品本身（PRD F1）；
- 加料段（"加…(加)"）剥离，热量不计入并告知（PRD F1 / D7 区分减料换料）；
- 匹配不上 → 热量未知，合计文案切换为「≥ N kcal」，绝不按 0 计算。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcd_nutrition import Matcher, _ADDON_RE, load_nutrition   # noqa: E402
import mcd_daypart as dp                                       # noqa: E402
from mcd_combo import _keyword_category                        # noqa: E402


def _is_addon(name: str) -> bool:
    return bool(_ADDON_RE.search(name))


def expand_order(order: dict) -> tuple[list[str], list[str]]:
    """展开套餐 → (单品名列表, 加料项列表)。

    comboItemList 展开为组成单品；无组成项按商品本身。
    未命中/歧义项由调用方按匹配结果标注（UNKNOWN 保护）。
    """
    items = []
    for p in order.get("orderProductList", []):
        qty = int(p.get("quantity") or 1)
        combo = p.get("comboItemList")
        if combo:
            for c in combo:
                cq = int(c.get("quantity") or 1)
                # ★ 字段差异：query-order 的子项用 productName，order-list 的子项用 name。
                #   实测 2026-10-10：order-list 返回 {"productCode","name","quantity"}，
                #   只认 productName 会把全部套餐子项读成空串（92% 误判为热量未知）。
                cname = c.get("productName") or c.get("name") or ""
                items.extend([cname] * cq)
            # 套餐壳本身不计数
        else:
            items.extend([p.get("productName") or p.get("name") or ""] * qty)
    addons = [it for it in items if _is_addon(it)]
    items = [it for it in items if not _is_addon(it)]
    return items, addons


def estimate(order_path: Path,
             daypart: Optional[str] = None,
             tier: str = "标准",
             store_options: Optional[str] = None,
             now_hhmm: str = "12:00",
             user_daypart: Optional[str] = None) -> dict:
    order = json.loads(order_path.read_text(encoding="utf-8"))
    matcher = Matcher(load_nutrition())
    items, addons = expand_order(order)

    # 餐段来源优先级：显式入参 > 订单自带（_meta.expectedDaypart / createTime）> now_hhmm 兜底。
    # 订单是历史事实，其餐段不应由"查看时刻"决定（否则早餐单在中午被按午餐档判定）。
    if not daypart and not user_daypart:
        meta = order.get("_meta") or {}
        exp = meta.get("expectedDaypart")
        if exp in dp.TIERS:                      # 样本/接口自带的餐段声明
            user_daypart = exp
        else:                                    # 真实订单：用下单时间推断
            parts = (order.get("createTime") or "").split()
            if len(parts) > 1 and len(parts[1]) >= 5:
                now_hhmm = parts[1][:5]

    dp_final = daypart or dp.resolve_daypart(now_hhmm, store_options, user_daypart)
    target = dp.tier_target(dp_final, tier)

    rows, unknown, ambiguous = [], [], []
    for raw in items:
        res = matcher.match(raw, allow_defaults=True)
        row = {"name": raw, "category": _keyword_category(raw)}
        if res["status"] == "hit":
            r = res["record"]
            row.update({"status": "hit", "method": res["method"], "matched": r["name"],
                        "kcal": r["kcal"], "protein": r["protein"], "fat": r["fat"],
                        "carb": r["carb"], "sodium_mg": r["sodium_mg"]})
        elif res["status"] == "ambiguous":
            row.update({"status": "ambiguous", "candidates": res["candidates"][:6]})
            ambiguous.append(row)
        else:
            row.update({"status": "unknown"})
            unknown.append(row)
        rows.append(row)

    known = [r for r in rows if r.get("status") == "hit"]
    total_kcal = sum(r["kcal"] for r in known)
    total_protein = sum(r["protein"] for r in known)
    total_sodium = sum(r["sodium_mg"] for r in known)
    has_unknown = bool(unknown)

    diff = total_kcal - target
    if abs(diff) <= target * 0.12:
        verdict = "落在本餐段标准档范围内，合适"
    elif diff > 0:
        verdict = f"偏高约 {diff:.0f} kcal，建议参考标准档替换方案"
    else:
        verdict = f"偏低约 {-diff:.0f} kcal，距离标准档还有空间"

    return {
        "orderId": order.get("orderId"),
        "sample": order.get("_meta", {}).get("sampleId"),
        "daypart": dp_final, "tier": tier, "target_kcal": target,
        "items": rows, "addons": addons,
        "ambiguous": ambiguous, "unknown": unknown,
        "totals": {"kcal": total_kcal, "protein": total_protein,
                   "sodium_mg": total_sodium,
                   "known_items": len(known), "unknown_items": len(unknown)},
        "verdict": verdict,
        "summary_text": (f"≥ {total_kcal:.0f} kcal（{len(unknown)} 项热量未知，实际会更高）"
                         if has_unknown else f"{total_kcal:.0f} kcal"),
    }


def print_report(res: dict) -> None:
    print(f"\n订单 {res['orderId'] or res['sample']} · 餐段 {res['daypart']} · "
          f"档位 {res['tier']}（目标 {res['target_kcal']} kcal）")
    print("─" * 72)
    for r in res["items"]:
        if r["status"] == "hit":
            kcal_txt = f"{r['kcal']:.0f} kcal"
            if r["kcal"] == 0:  # 合法 0（无糖饮料/纯水），与「热量未知」严格区分
                kcal_txt += "（确为无热量）"
            print(f"  ✓ {r['name']:<20} → {r['matched']:<12} [{r['method']}] "
                  f"{kcal_txt}｜钠 {r['sodium_mg']:.0f}mg")
        elif r["status"] == "ambiguous":
            print(f"  ? {r['name']:<20} → 需确认规格：{' / '.join(r['candidates'])}")
        else:
            print(f"  ✗ {r['name']:<20} → 热量未知（营养表无此商品）")
    if res["addons"]:
        print(f"  + 加料（热量不计入）：{'、'.join(res['addons'])}")
    print("─" * 72)
    print(f"  整单：{res['summary_text']}")
    print(f"  结论：{res['verdict']}")
    if res["ambiguous"]:
        print("  ⚠ 含待确认规格项，确认后合计会变化")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="订单热量估算")
    ap.add_argument("--order", required=True)
    ap.add_argument("--daypart", choices=list(dp.TIERS))
    ap.add_argument("--user-daypart", dest="user_daypart", choices=list(dp.TIERS))
    ap.add_argument("--tier", default="标准", choices=["轻量", "标准", "吃饱"])
    ap.add_argument("--time", default="12:00", help="HH:MM，用于餐段判定")
    ap.add_argument("--store-options", dest="store_options", help="门店 reservationTimeOptions 文本")
    a = ap.parse_args()
    res = estimate(Path(a.order), a.daypart, a.tier, a.store_options, a.time, a.user_daypart)
    print_report(res)
