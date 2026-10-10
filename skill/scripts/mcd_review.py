#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd_review.py — 历史订单逐单复盘管线（单一实现）

之前 mcd_import.py 与 mcd_history.py 各持一份逐字节相同的 review_order/_hhmm
（口径漂移即违反引擎一致性红线），v0.9 起收敛到本模块：
- expand_order（mcd_order）展开套餐 → 匹配营养表 → 合计热量；
- createTime 推断餐段 → 与该餐段标准档对比 → 出结论。

纪律不变：
- 未知项一律标注「热量未知」，绝不按 0 计算（PRD F1 / §9）；
- 加料段剥离、热量不计入（PRD F1）；
- 只处理**脱敏**样本；原始响应（含 orderId / 门店）不入库。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcd_nutrition import Matcher          # noqa: E402
import mcd_daypart as dp                   # noqa: E402
from mcd_order import expand_order         # noqa: E402


def _hhmm(create_time: str) -> str:
    """'2026-03-20 18:32:42' → '18:32'"""
    try:
        return create_time.split()[1][:5]
    except Exception:
        return "12:00"


def review_order(order: dict, matcher: Matcher, user_daypart: str | None = None) -> dict:
    """复算单笔订单热量（mcd_import / mcd_history 同口径，本模块为唯一实现）。"""
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
            rows.append({"name": raw, "status": "ambiguous",
                         "candidates": res["candidates"][:4]})
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
