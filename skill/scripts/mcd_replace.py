#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd_replace.py — 替换建议（T23/T24，PRD F4）

规则：本单高于所处餐段「标准」档 → 自动切到标准档出替换方案；
否则用与整单最接近的档位。输出：替换组合 + 少多少 kcal + 价格差。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcd_daypart as dp                       # noqa: E402
from mcd_nutrition import Matcher, load_nutrition   # noqa: E402
from mcd_order import estimate                      # noqa: E402
from mcd_combo import build_pools, recommend        # noqa: E402


def suggest(order_path: Path, menu_path: Path,
            tier: str = "标准", sort_by: str = "near", top: int = 3,
            now_hhmm: str = "12:00", user_daypart: Optional[str] = None) -> dict:
    est = estimate(order_path, tier=tier, now_hhmm=now_hhmm, user_daypart=user_daypart)
    matcher_pools = build_pools(menu_path, Matcher(load_nutrition()))

    order_kcal = est["totals"]["kcal"]
    order_price = None  # 订单样本未含金额；真实订单接入 query-order 后回填
    std_target = dp.tier_target(est["daypart"], "标准")

    # T23 触发规则：超过标准档 → 切标准档；否则取最接近整单热量的档位
    if est["daypart"] == "随便吃吃":
        tier_for_replace = tier
    elif order_kcal > std_target * 1.12:
        tier_for_replace = "标准"
    else:
        tier_for_replace = min(
            dp.TIERS[est["daypart"]], key=lambda t: abs(dp.TIERS[est["daypart"]][t] - order_kcal)
        )

    rec = recommend(matcher_pools["pools"], est["daypart"], tier_for_replace, sort_by, top)
    return {"estimate": est, "replace_tier": tier_for_replace, "recommendation": rec,
            "order_kcal": order_kcal, "order_price": order_price}


def print_suggest(res: dict) -> None:
    est = res["estimate"]
    rec = res["recommendation"]
    print(f"\n替换建议 · 订单 {est['orderId'] or est['sample']}（{est['daypart']}，"
          f"整单 {res['order_kcal']:.0f} kcal）")
    print("─" * 72)
    if est["totals"]["unknown_items"]:
        print(f"  ⚠ 本单含 {est['totals']['unknown_items']} 项热量未知，"
              f"对比基准为「≥ {res['order_kcal']:.0f} kcal」")
    print(f"  触发档位：{res['replace_tier']}（目标 {rec['target']} kcal，"
          f"区间 {rec['range'][0]}–{rec['range'][1]}，命中 {rec['count']} 组）")
    if not rec["results"]:
        print("  档位内没有合适组合 → 建议换一个档位")
        return
    for i, r in enumerate(rec["results"], 1):
        names = " + ".join(x["name"] for x in r["items"])
        t = r["totals"]
        saved = res["order_kcal"] - t["kcal"]
        diff_txt = f"少 {saved:.0f} kcal" if saved > 0 else f"多 {-saved:.0f} kcal"
        price_txt = f"，价格差需按实付口径计算" if res["order_price"] is None else ""
        print(f"  {i}. {names}")
        print(f"     {t['kcal']:.0f} kcal（{diff_txt}）｜钠 {t['sodium_mg']:.0f}mg｜"
              f"参考价 ≈¥{t['price']:.1f}{price_txt}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="订单替换建议（F4）")
    ap.add_argument("--order", required=True)
    ap.add_argument("--menu", required=True)
    ap.add_argument("--tier", default="标准")
    ap.add_argument("--sort", default="near", choices=["near", "protein", "sodium", "price"])
    ap.add_argument("--time", default="12:00", help="HH:MM，订单未自带餐段时用于判定")
    ap.add_argument("--user-daypart", dest="user_daypart", choices=list(dp.TIERS),
                    help="显式指定餐段（最优先）")
    a = ap.parse_args()
    print_suggest(suggest(Path(a.order), Path(a.menu), a.tier, a.sort,
                          now_hhmm=a.time, user_daypart=a.user_daypart))
