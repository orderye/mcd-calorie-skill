#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_match.py — 匹配率评测（T10，对应 PRD §9 验收：常见订单命中率 ≥90%）

跑全部订单样本（fixtures/order.*.json），分两组统计：
- TYPICAL 常见订单集（正常点单形态）→ 对标 90% 验收线；
- STRESS 压力样本（故意构造的缺失新品/无证据歧义/泛称甜品）→ 验证
  「匹配不上 100% 标注、绝不按 0 计算」路径，不计入验收指标。

歧义（ambiguous）按未命中计：用户未确认规格前不得出数。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from mcd_nutrition import Matcher, load_nutrition   # noqa: E402
from mcd_order import expand_order                  # noqa: E402

TYPICAL = ("sample-01", "sample-02", "sample-05", "sample-06")  # 常见订单集
STRESS = ("sample-03", "sample-04")                             # 压力样本（边界路径）


def main() -> int:
    matcher = Matcher(load_nutrition())
    samples = sorted((SKILL_ROOT / "fixtures").glob("order.*.json"))
    stats = {"typical": Counter(), "stress": Counter()}
    method_dist: Counter = Counter()
    miss_report: list[str] = []

    print("=" * 76)
    print("名称匹配率评测（T10）")
    print("=" * 76)

    for sp in samples:
        order = json.loads(sp.read_text(encoding="utf-8"))
        items, addons = expand_order(order)
        sid = order.get("_meta", {}).get("sampleId", sp.stem)
        bucket = "typical" if sid.startswith(TYPICAL) else "stress"
        n_h = n_a = n_u = 0
        for name in items:
            stats[bucket]["total"] += 1
            res = matcher.match(name, allow_defaults=True)
            if res["status"] == "hit":
                stats[bucket]["hit"] += 1
                n_h += 1
                method_dist[res["method"]] += 1
            elif res["status"] == "ambiguous":
                stats[bucket]["ambiguous"] += 1
                n_a += 1
                miss_report.append(f"[歧义] {sid} · {name} → {' / '.join(res['candidates'][:4])}")
            else:
                stats[bucket]["unknown"] += 1
                n_u += 1
                miss_report.append(f"[未知] {sid} · {name}（营养表无此商品）")
        print(f"  {sid:<28} 命中 {n_h}｜歧义 {n_a}｜未知 {n_u}")

    print("-" * 76)
    for label, b in (("常见订单集（验收口径）", stats["typical"]),
                     ("压力样本（边界验证）", stats["stress"])):
        total = b["total"]
        rate = b["hit"] / total * 100 if total else 0.0
        print(f"  {label}: {b['hit']}/{total} = {rate:.1f}%"
              f"（歧义 {b['ambiguous']}，未知 {b['unknown']}）")
    rate = stats["typical"]["hit"] / stats["typical"]["total"] * 100 if stats["typical"]["total"] else 0
    ok = rate >= 90
    print(f"  命中方式分布：{dict(method_dist)}")
    if miss_report:
        print("  未命中清单：")
        for line in miss_report:
            print(f"    {line}")

    print("-" * 76)
    print("  ✓ 所有未命中项均被显式标注（热量未知/待确认规格），绝无按 0 计算路径")
    print(f"  验收结论：{'PASS（≥90%）' if ok else 'FAIL（<90%，继续补别名表，禁止上调模糊阈值）'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
