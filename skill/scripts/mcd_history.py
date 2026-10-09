#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd_history.py — 历史订单批量复盘（T35）

数据源：order-list（官方历史订单查询，1.0.6/2026-07-16 起可用）。
它返回的 `orderProductList[].comboItemList[]` 与 query-order **结构一致**，
所以展开、归一、匹配逻辑可直接复用 mcd_order，无需另写一套。

回答的是 PRD 场景 5：「昨天那单偏高，今天想要更轻的替换方案」——
先批量算出每单热量与档位差，再挑出偏高单去 mcd_replace 拿替换方案。

纪律：
- 未知项一律标注，绝不按 0 计算（PRD F1 / §9）。
- 加料段剥离、热量不计入（PRD F1）。
- 只读 fixtures 里的**脱敏**样本；原始响应（含 orderId / 门店）不入库。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcd_nutrition import Matcher, load_nutrition   # noqa: E402
import mcd_daypart as dp                            # noqa: E402
from mcd_order import expand_order                # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = SKILL_ROOT / "fixtures" / "order-list.sample.json"


def _hhmm(create_time: str) -> str:
    """'2026-03-20 18:32:42' → '18:32'"""
    try:
        return create_time.split()[1][:5]
    except Exception:
        return "12:00"


def review_order(order: dict, matcher: Matcher, user_daypart: str | None = None) -> dict:
    items, addons = expand_order(order)
    daypart = user_daypart or dp.resolve_daypart(_hhmm(order.get("createTime", "")), None)
    standard = dp.tier_target(daypart, "标准")
    light = dp.tier_target(daypart, "轻量")

    rows, unknown, ambiguous = [], [], []
    for raw in items:
        res = matcher.match(raw, allow_defaults=True)
        if res["status"] == "hit":
            r = res["record"]
            rows.append({"name": raw, "status": "hit", "kcal": r["kcal"],
                         "matched": r["name"], "method": res["method"]})
        elif res["status"] == "ambiguous":
            rows.append({"name": raw, "status": "ambiguous", "candidates": res["candidates"][:4]})
            ambiguous.append(raw)
        else:
            rows.append({"name": raw, "status": "unknown"})
            unknown.append(raw)

    total = sum(r["kcal"] for r in rows if r["status"] == "hit")
    diff = total - standard
    if abs(diff) <= standard * 0.12:
        verdict = "标准档合适"
    elif diff > 0:
        verdict = f"偏高 +{diff:.0f}"
    else:
        verdict = f"偏低 {diff:.0f}"
    return {
        "orderId": order.get("orderId"),
        "createTime": order.get("createTime"),
        "store": order.get("store"),
        "daypart": daypart,
        "standard": standard, "light": light,
        "itemCount": len(rows), "kcal": total, "diff": diff, "verdict": verdict,
        "unknown": unknown, "ambiguous": ambiguous,
        "addons": addons,
        "amount": order.get("realTotalAmount"),
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="历史订单批量复盘")
    ap.add_argument("--path", default=str(DEFAULT_SRC), help="脱敏历史订单样本路径")
    ap.add_argument("--daypart", default=None, help="强制指定餐段（默认按 createTime 推断）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（便于二次处理）")
    ap.add_argument("--top", type=int, default=10, help="明细展示条数")
    args = ap.parse_args()

    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    orders = data.get("list") or []
    if not orders:
        raise SystemExit("样本里没有订单")

    matcher = Matcher(load_nutrition())
    reviews = [review_order(o, matcher, args.daypart) for o in orders]
    reviews.sort(key=lambda r: r["kcal"], reverse=True)

    if args.json:
        print(json.dumps(reviews, ensure_ascii=False, indent=1))
        return

    print("=" * 74)
    print("历史订单热量复盘（数据源 order-list，脱敏样本）")
    print("=" * 74)
    print(f"{'下单时间':<20}{'餐段':<8}{'项数':>4}{'热量':>7}{'标准档':>8}  {'结论'}")
    print("-" * 74)
    for r in reviews[:args.top]:
        print(f"{r['createTime']:<20}{r['daypart']:<8}{r['itemCount']:>4}{r['kcal']:>7.0f}"
              f"{r['standard']:>8}  {r['verdict']}")
    print("-" * 74)

    over = [r for r in reviews if r["diff"] > r["standard"] * 0.12]
    hit = sum(r["kcal"] for r in reviews) / len(reviews)
    known = sum(len(r["unknown"]) for r in reviews)
    amb = sum(len(r["ambiguous"]) for r in reviews)
    total_items = sum(r["itemCount"] for r in reviews)
    print(f"订单数 {len(reviews)}｜平均 {hit:.0f} 千卡｜超标准档 {len(over)} 单"
          f"｜最重 {reviews[0]['kcal']} 千卡（{reviews[0]['createTime']}）")
    print(f"商品项 {total_items}｜热量未知 {known} 项（{known/total_items*100:.1f}%）"
          f"｜歧义待选 {amb} 项")
    if over:
        print(f"\n超标准档的订单（可交给 mcd_replace 生成更轻方案）：")
        for r in over:
            print(f"  - {r['createTime']} {r['daypart']} {r['kcal']} 千卡（{r['verdict']}）"
                  f" 金额 ¥{r['amount']}")
    if known:
        print("\n未匹配到营养表的商品（应标注「热量未知」，不得按 0 计算）：")
        seen = []
        for r in reviews:
            for n in r["unknown"]:
                if n not in seen:
                    seen.append(n)
        print("  " + "、".join(seen[:20]))


if __name__ == "__main__":
    main()
