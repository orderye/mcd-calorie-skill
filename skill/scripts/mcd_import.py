#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd_import.py — 一键导入历史订单并分析热量（T36）

把「历史订单复盘」从"需要人工先脱敏"升级为"一键导入"：
  原始 order-list 响应（含 orderId / storeCode / storeName / beCode 等敏感字段）
  → 自动脱敏（去敏感字段，门店代称化）→ 落盘为本地脱敏样本
  → 逐单展开套餐 → 匹配营养表 → 计算热量 → 餐段判定 → 档位对比
  → 汇总报告（排行 / 超档 / 平均热量 / 未知项占比，可 --json 导出）。

数据源：order-list（官方历史订单查询，1.0.6/2026-07-16 起可用）。
其 orderProductList[].comboItemList[] 与 query-order 结构一致，
展开 / 归一 / 匹配逻辑收敛在 mcd_review（复用 mcd_order.expand_order）。

纪律（与 mcd_history.py 一致，不可放松）：
- 未知项一律标注「热量未知」，绝不按 0 计算（PRD F1 / §9）。
- 加料段剥离、热量不计入（PRD F1）。
- 脱敏是硬红线：orderId / storeCode / storeName / beCode 一律去除，
  门店以「门店A/B/C」代称；原始响应（含敏感字段）绝不落盘。

用法：
  python3 scripts/mcd_import.py --raw <原始 order-list 响应.json>
  python3 scripts/mcd_import.py --raw in.json --out data/history-orders.json
  python3 scripts/mcd_import.py --raw in.json --json        # 输出 JSON 报告
  python3 scripts/mcd_import.py --raw in.json --no-deidentify  # 已脱敏样本直接复盘（只分析不脱敏）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcd_nutrition import Matcher, load_nutrition   # noqa: E402
from mcd_review import review_order                 # noqa: E402  # 逐单复盘唯一实现

SKILL_ROOT = Path(__file__).resolve().parent.parent
OUT_DEFAULT = SKILL_ROOT / "data" / "history-orders.json"

# 脱敏：这些字段含个人 / 门店定位信息，一律去除
_SENSITIVE_KEYS = ("orderId", "storeCode", "storeName", "beCode", "memberId",
                   "phone", "mobile", "address", "payNo", "tradeNo", "token")
# 门店代称：按首次出现顺序分配「门店A / 门店B / …」
_STORE_ALIAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


# ────────────────────────── 脱敏 ──────────────────────────

def _strip_sensitive(obj):
    """递归去除敏感字段，返回新对象（不修改原对象）。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _SENSITIVE_KEYS:
                continue
            out[k] = _strip_sensitive(v)
        return out
    if isinstance(obj, list):
        return [_strip_sensitive(x) for x in obj]
    return obj


def deidentify(raw: dict) -> dict:
    """把原始 order-list 响应脱敏为可落盘样本。

    保留：createTime（餐段判定必需）、商品与组成（热量估算必需）、
          realTotalAmount（复算价格差必需）、orderType / beType / orderStatus。
    去除：orderId / storeCode / storeName / beCode 等敏感字段，
          门店以「门店A/B/C」代称。
    """
    orders = []
    store_map: dict[str, str] = {}
    for o in (raw.get("list") or raw.get("data") or []):
        cleaned = _strip_sensitive(o)
        # 门店代称化：无论原始字段叫 store / storeName，统一按出现顺序映射
        store_name = o.get("store") or o.get("storeName") or ""
        if store_name:
            alias = store_map.setdefault(
                str(store_name), f"门店{_STORE_ALIAS[len(store_map)]}")
            cleaned["store"] = alias
        orders.append(cleaned)

    # 元信息：标明脱敏来源，且绝不携带 traceId 等可追溯标识
    meta = {
        "source": "order-list（官方历史订单查询）· 已自动脱敏",
        "deidentifiedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "deidentified": "★ 已脱敏：去除 orderId / storeCode / storeName / beCode，"
                        "门店以「门店A/B/C」代称；保留 createTime、商品与组成、"
                        "实付金额。原始响应（含敏感字段）不落盘。",
        "orderCount": len(orders),
    }
    # 原始响应若带时间跨度，尽力保留（不复制 traceId 等敏感键）
    for k in ("span", "fetchedAt"):
        if raw.get(k) is not None and k != "traceId":
            meta[k] = raw[k]
    return {"_meta": meta, "list": orders}


# ────────────────────────── 汇总报告 ──────────────────────────

def summarize(reviews: list[dict], deidentify_meta: dict | None) -> dict:
    """把逐单结果汇总为结构化报告（可 --json 导出）。"""
    if not reviews:
        return {"_meta": deidentify_meta or {}, "orders": [], "summary": {
            "orderCount": 0, "avgKcal": 0, "overStandard": 0,
            "maxKcal": 0, "maxKcalTime": None, "itemCount": 0,
            "unknownCount": 0, "unknownRate": 0, "ambiguousCount": 0}}

    over = [r for r in reviews if r["diff"] > r["standard"] * 0.12]
    avg = sum(r["kcal"] for r in reviews) / len(reviews)
    unknown = sum(len(r["unknown"]) for r in reviews)
    ambiguous = sum(len(r["ambiguous"]) for r in reviews)
    items = sum(r["itemCount"] for r in reviews)
    top = max(reviews, key=lambda r: r["kcal"])

    # 未匹配商品去重清单
    seen_unknown: list[str] = []
    for r in reviews:
        for n in r["unknown"]:
            if n not in seen_unknown:
                seen_unknown.append(n)

    return {
        "_meta": deidentify_meta or {},
        "orders": reviews,
        "summary": {
            "orderCount": len(reviews),
            "avgKcal": round(avg, 1),
            "overStandard": len(over),
            "maxKcal": top["kcal"],
            "maxKcalTime": top["createTime"],
            "itemCount": items,
            "unknownCount": unknown,
            "unknownRate": round(unknown / items * 100, 1) if items else 0,
            "ambiguousCount": ambiguous,
            "unknownNames": seen_unknown,
        },
    }


def print_report(summary: dict) -> None:
    """人类可读的汇总报告。"""
    s = summary["summary"]
    reviews = summary["orders"]
    print("=" * 74)
    print("历史订单一键导入 · 热量分析报告")
    print("=" * 74)
    if summary["_meta"].get("deidentifiedAt"):
        print(f"  脱敏落盘于 {summary['_meta']['deidentifiedAt']}"
              f"（{s['orderCount']} 单，敏感字段已去除）")
    print(f"{'下单时间':<20}{'餐段':<8}{'项数':>4}{'热量':>7}{'标准档':>8}  {'结论'}")
    print("-" * 74)
    for r in sorted(reviews, key=lambda r: r["kcal"], reverse=True):
        print(f"{r['createTime']:<20}{r['daypart']:<8}{r['itemCount']:>4}"
              f"{r['kcal']:>7.0f}{r['standard']:>8}  {r['verdict']}")
    print("-" * 74)
    print(f"订单数 {s['orderCount']}｜平均 {s['avgKcal']} 千卡｜超标准档 {s['overStandard']} 单"
          f"｜最重 {s['maxKcal']} 千卡（{s['maxKcalTime']}）")
    print(f"商品项 {s['itemCount']}｜热量未知 {s['unknownCount']} 项"
          f"（{s['unknownRate']}%）｜歧义待选 {s['ambiguousCount']} 项")

    over = [r for r in reviews if r["diff"] > r["standard"] * 0.12]
    if over:
        print("\n超标准档的订单（可交给 mcd_replace 生成更轻方案）：")
        for r in over:
            print(f"  - {r['createTime']} {r['daypart']} {r['kcal']} 千卡"
                  f"（{r['verdict']}）金额 ¥{r['amount']}")
    if s["unknownNames"]:
        print("\n未匹配到营养表的商品（应标注「热量未知」，不得按 0 计算）：")
        print("  " + "、".join(s["unknownNames"][:20]))


# ────────────────────────── 入口 ──────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="一键导入历史订单并分析热量")
    ap.add_argument("--raw", required=True, help="原始 order-list 响应（含敏感字段）JSON 路径")
    ap.add_argument("--out", default=str(OUT_DEFAULT), help="脱敏后落盘路径（默认 data/history-orders.json）")
    ap.add_argument("--no-deidentify", action="store_true",
                    help="输入已是脱敏样本（list 结构），跳过脱敏直接复盘")
    ap.add_argument("--daypart", default=None, help="强制指定餐段（默认按 createTime 推断）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 报告（便于二次处理）")
    ap.add_argument("--top", type=int, default=10, help="明细展示条数（文本模式）")
    a = ap.parse_args()

    raw_path = Path(a.raw)
    if not raw_path.exists():
        raise SystemExit(f"输入文件不存在：{raw_path}")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))

    # 1) 脱敏（可跳过）
    if a.no_deidentify:
        orders = raw.get("list") or []
        deidentify_meta = raw.get("_meta") or {}
        out_path = None
    else:
        deidentified = deidentify(raw)
        orders = deidentified["list"]
        deidentify_meta = deidentified["_meta"]
        out_path = Path(a.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(deidentified, ensure_ascii=False, indent=1),
                            encoding="utf-8")

    if not orders:
        raise SystemExit("响应里没有订单（list/data 均为空）")

    # 2) 逐单分析
    matcher = Matcher(load_nutrition())
    reviews = [review_order(o, matcher, a.daypart) for o in orders]

    # 3) 汇总
    summary = summarize(reviews, deidentify_meta)

    if a.json:
        if out_path:
            summary["_meta"]["deidentifiedPath"] = str(out_path)
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return

    if out_path:
        print(f"✓ 已脱敏落盘：{out_path}（{len(orders)} 单，敏感字段已去除）\n")
    print_report(summary)


if __name__ == "__main__":
    main()
