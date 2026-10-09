#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd_catalog.py — 全量餐品 / 套餐目录聚合（T34）

「全量」在官方接口里不是一次调用能拿到的：query-meals 的维度是
  门店(storeCode) × 渠道(orderType/beType) × 餐段(reservationDate)，
每次返回「该店该餐段的可售菜单」。因此全量 = 多份快照的聚合去重。
套餐内容另有来源：query-meal-detail 的 rounds/choices（按 code 逐个取）。

本脚本只做**离线聚合与归一**，不发起网络请求：
- 输入：fixtures/meals.*.json（菜单快照，各种精简形态均可）
        fixtures/meal-detail.*.json（套餐组成）
- 输出：data/catalog.json（products / combos / stores / stats）

纪律：
- 图片字段一律不落盘（image / 别名键都不写入），只记 hasImage 布尔。
  合规：不使用官方商品图片素材（PRD §8 / SKILL.md 红线）。
- 目录用于「匹配、兜底、离线演示」；正式推荐候选仍必须取自
  当次 query-meals 的实时返回，不得用目录替代（PRD F3 / §9）。

用法：
  python3 scripts/mcd_catalog.py                 # 聚合 + 报告
  python3 scripts/mcd_catalog.py --calls         # 打印采集矩阵（要跑哪些调用）
  python3 scripts/mcd_catalog.py --out X.json    # 指定输出路径
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcd_nutrition import Matcher          # noqa: E402
import mcd_daypart as dp                   # noqa: E402
from mcd_order import expand_order         # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = SKILL_ROOT / "fixtures"
OUT_DEFAULT = SKILL_ROOT / "data" / "catalog.json"
HISTORY_ORDERS = FIXTURES / "order-list.sample.json"   # 脱敏历史订单（order-list）

# 名称里出现这些词 → 视为套餐/组合（统一维护在 data/category-rules.json#comboHints）
_RULES = json.loads((SKILL_ROOT / "data" / "category-rules.json").read_text(encoding="utf-8"))
COMBO_HINTS = tuple(_RULES["comboHints"])

IMAGE_KEYS = ("image", "img", "imageUrl", "picUrl", "cover")


# ────────────────────────── 快照解析 ──────────────────────────

def _norm_categories(cats: list) -> list[tuple[str, list[tuple[str, list[str]]]]]:
    """兼容两种分类形态：
      原始    : [{name, meals:[{code, tags}]}]
      精简样本: [{name, items:[[code, [tags]]]}]
    """
    out = []
    for c in cats or []:
        name = (c.get("name") or "").strip()
        entries: list[tuple[str, list[str]]] = []
        if c.get("meals"):
            for m in c["meals"]:
                entries.append((str(m.get("code")), list(m.get("tags") or [])))
        else:
            for it in c.get("items") or []:
                if isinstance(it, (list, tuple)) and it:
                    code = str(it[0])
                    tags = list(it[1]) if len(it) > 1 and isinstance(it[1], (list, tuple)) else []
                    entries.append((code, tags))
                else:
                    entries.append((str(it), []))
        out.append((name, entries))
    return out


def _norm_entity(e: dict) -> dict:
    """兼容 currentPrice（原始）/ price（精简样本）。"""
    price = e.get("currentPrice", e.get("price"))
    return {
        "name": (e.get("name") or "").strip(),
        "price": None if price is None else str(price),
        "originalPrice": None if e.get("originalPrice") is None else str(e.get("originalPrice")),
        "discountType": e.get("discountType"),
        "canWithOrder": bool(e.get("canWithOrder")) if e.get("canWithOrder") is not None else None,
        "hasImage": any(k in e for k in IMAGE_KEYS),
    }


def _daypart_of(meta: dict) -> str:
    """快照所属餐段：优先 reservationDate，其次 serverDaypart，最后「现场」。"""
    rd = meta.get("reservationDate")
    if rd:
        try:
            hhmm = str(rd).split()[1][:5]
            return dp.resolve_daypart(hhmm, None)
        except Exception:
            pass
    sd = meta.get("serverDaypart")
    if sd:
        for seg in ("宵夜", "下午茶", "早餐", "午餐", "夜市"):   # 长名优先，避免「夜」误配
            if seg in sd:
                return dp.SEGMENT_ALIAS.get(seg, seg)
    return "现场"


def load_snapshots() -> list[dict]:
    snaps = []
    for p in sorted(FIXTURES.glob("meals.*.json")):
        raw = json.loads(p.read_text(encoding="utf-8"))
        meta = raw.get("_meta") or {}
        # kind=diff 的差异记录不是完整菜单，跳过（否则会把 2 个差异项当成一份菜单）
        if meta.get("kind") == "diff":
            continue
        snaps.append({
            "file": p.name,
            "storeCode": str(meta.get("storeCode") or "?"),
            "storeName": meta.get("storeName"),
            "orderType": meta.get("orderType"),
            "beType": meta.get("beType"),
            "fetchedAt": meta.get("fetchedAt"),
            "daypart": _daypart_of(meta),
            "categories": _norm_categories(raw.get("categories")),
            "meals": {str(k): _norm_entity(v) for k, v in (raw.get("meals") or {}).items()},
        })
    return snaps


def load_combo_details() -> dict[str, dict]:
    combos = {}
    for p in sorted(FIXTURES.glob("meal-detail.*.json")):
        raw = json.loads(p.read_text(encoding="utf-8"))
        code = str(raw.get("code") or p.stem.split(".")[-1])
        rounds = []
        for r in raw.get("rounds") or []:
            rounds.append({
                "name": r.get("name"),
                "category": r.get("category"),
                "quantity": r.get("quantity"),
                "choices": [{
                    "code": str(c.get("code")),
                    "name": c.get("name"),
                    "isDefault": c.get("isDefault"),
                    "diffPrice": c.get("diffPrice"),
                    "supportModify": c.get("supportModify"),
                } for c in (r.get("choices") or [])],
            })
        combos[code] = {
            "name": raw.get("name"),
            "price": raw.get("price"),
            "supportModify": raw.get("supportModify"),
            "rounds": rounds,
            "source": p.name,
        }
    return combos


# ────────────────────────── 聚合 ──────────────────────────

def build_catalog() -> tuple[dict, dict]:
    snaps = load_snapshots()
    if not snaps:
        raise SystemExit("fixtures/ 下没有 meals.*.json 快照，先按 --calls 拉取")

    products: dict[str, dict] = {}
    stores: dict[str, dict] = {}
    dangling: list[dict] = []
    daypart_menus: dict[str, list[str]] = {}

    for s in snaps:
        daypart = s["daypart"]
        st = stores.setdefault(s["storeCode"], {
            "storeName": s["storeName"], "dayparts": [], "orderType": s["orderType"],
            "beType": s["beType"], "categoryNames": [],
        })
        if daypart not in st["dayparts"]:
            st["dayparts"].append(daypart)
        menus = daypart_menus.setdefault(daypart, [])
        menus.append(s["file"])

        for cname, entries in s["categories"]:
            if cname not in st["categoryNames"]:
                st["categoryNames"].append(cname)
            for code, tags in entries:
                ent = s["meals"].get(code)
                if ent is None:
                    dangling.append({"file": s["file"], "code": code, "category": cname})
                    continue
                p = products.setdefault(code, {
                    "name": ent["name"], "dayparts": [], "categories": [], "tags": [],
                    "stores": [], "prices": {}, "isCombo": any(h in ent["name"] for h in COMBO_HINTS),
                    "hasImage": False,
                })
                if not p["name"] and ent["name"]:
                    p["name"] = ent["name"]
                if daypart not in p["dayparts"]:
                    p["dayparts"].append(daypart)
                if cname not in p["categories"]:
                    p["categories"].append(cname)
                for t in tags:
                    if t not in p["tags"]:
                        p["tags"].append(t)
                if s["storeCode"] not in p["stores"]:
                    p["stores"].append(s["storeCode"])
                p["prices"][daypart] = {
                    "price": ent["price"], "originalPrice": ent["originalPrice"],
                    "discountType": ent["discountType"], "file": s["file"],
                }
                p["hasImage"] = p["hasImage"] or ent["hasImage"]

    # 只被分类引用、但没在任何 meals 映射里出现的 code（悬空引用）
    details = load_combo_details()
    for code, d in details.items():
        p = products.setdefault(code, {
            "name": d["name"], "dayparts": [], "categories": [], "tags": [],
            "stores": [], "prices": {}, "isCombo": True, "hasImage": False,
        })
        if d["name"] and not p["name"]:
            p["name"] = d["name"]

    # 跨餐段价格差异（同 code 不同价）
    price_diffs = []
    for code, p in products.items():
        vals = {(v["price"]) for v in p["prices"].values() if v["price"] is not None}
        if len(vals) > 1:
            price_diffs.append({
                "code": code, "name": p["name"],
                "prices": {k: v["price"] for k, v in p["prices"].items()},
            })

    # 营养表覆盖：分「单品 / 套餐」统计（营养表是单品维度，套餐名本来就不该命中）
    matcher = Matcher()
    coverage = {"hit": [], "ambiguous": [], "unknown": []}
    cov_by_kind = {"单品": {"hit": 0, "ambiguous": 0, "unknown": 0},
                   "套餐": {"hit": 0, "ambiguous": 0, "unknown": 0}}
    for code, p in sorted(products.items(), key=lambda kv: kv[1]["name"] or ""):
        if not p["name"]:
            continue
        r = matcher.match(p["name"])
        kind = "套餐" if p["isCombo"] else "单品"
        cov_by_kind[kind][r["status"]] += 1
        coverage[r["status"]].append({"code": code, "name": p["name"], "kind": kind,
                                     "method": r["method"],
                                     "candidates": r["candidates"][:3]})

    combos = {code: p for code, p in products.items() if p["isCombo"]}
    singles = {code: p for code, p in products.items() if not p["isCombo"]}

    return {
        "_meta": {            "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sources": [s["file"] for s in snaps] + [d["source"] for d in details.values()],
            "note": "图片字段不落盘（合规）。本目录用于离线匹配与兜底；推荐候选必须取自当次 query-meals 实时结果。",
            "daypartMenus": daypart_menus,
        },
        "stores": stores,
        "products": products,
        "comboDetails": details,
        "stats": {
            "snapshotCount": len(snaps),
            "productCount": len(products),
            "comboCount": len(combos),
            "singleCount": len(singles),
            "dayparts": sorted({s["daypart"] for s in snaps}),
            "categoryCountByStore": {k: len(v["categoryNames"]) for k, v in stores.items()},
            "danglingRefs": dangling,
            "priceDiffs": price_diffs,
            "nutritionCoverage": {k: len(v) for k, v in coverage.items()},
            "nutritionCoverageByKind": cov_by_kind,
            "nutritionMiss": [x["name"] for x in coverage["unknown"] if x["kind"] == "单品"][:40],
            "comboDetailCount": len(details),
        },
    }, coverage


# ────────────────────────── 采集矩阵 ──────────────────────────

def collect_history_gaps(matcher: Matcher, path: Path = HISTORY_ORDERS) -> list[dict]:
    """从脱敏历史订单（order-list）里收集营养表未命中的单品。

    与目录缺口的区别：这些多为**已下架 / 限定品**（如爆脆星星堡系列），
    不在当日在售目录里，因此没有 categories / tags / price 可填。
    但历史复盘必须知道它们「查不到」，否则每次都要重新发现一遍；
    且纪律不变——标「热量未知」，绝不按 0 计算。

    只登记 unknown；历史订单里的 ambiguous 不登记（歧义是规格缺失，
    应让用户选，不是营养表缺口）。
    """
    if not path.exists():
        return []
    orders = json.loads(path.read_text(encoding="utf-8")).get("list") or []

    # 名称 → code（同名多码取首次出现）
    code_of: dict[str, str] = {}
    for o in orders:
        for p in o.get("orderProductList", []):
            combo = p.get("comboItemList")
            if combo:
                for c in combo:
                    n = (c.get("productName") or c.get("name") or "").strip()
                    code_of.setdefault(n, str(c.get("productCode") or ""))
            else:
                n = (p.get("productName") or p.get("name") or "").strip()
                code_of.setdefault(n, str(p.get("productCode") or ""))

    seen: dict[str, dict] = {}
    for o in orders:
        items, _addons = expand_order(o)
        hhmm = (o.get("createTime") or "").split()[1][:5] if " " in (o.get("createTime") or "") else "12:00"
        daypart = dp.resolve_daypart(hhmm, None)
        for raw in items:
            name = (raw or "").strip()
            if not name:
                continue
            res = matcher.match(name, allow_defaults=True)
            if res["status"] != "unknown":
                continue
            g = seen.setdefault(name, {
                "code": code_of.get(name, ""), "name": name,
                "categories": [], "tags": ["历史订单"], "dayparts": [], "price": {},
                "origin": "history-order",
                "note": "已下架/限定品，不在当日在售目录 → 无分类与价格。"
                        "热量未知，合计按「≥ N kcal」计，绝不按 0 计算。",
                "seen": {"times": [], "stores": [], "count": 0},
            })
            g["seen"]["count"] += 1
            t = o.get("createTime") or ""
            if t and t not in g["seen"]["times"]:
                g["seen"]["times"].append(t)
            s = o.get("store") or ""
            if s and s not in g["seen"]["stores"]:
                g["seen"]["stores"].append(s)
            if daypart and daypart not in g["dayparts"]:
                g["dayparts"].append(daypart)

    for g in seen.values():
        g["seen"]["times"].sort()
    return sorted(seen.values(), key=lambda g: (-g["seen"]["count"], g["name"]))


def emit_gaps(cat: dict, unknown_list: list, ambiguous_list: list, out_path: Path,
              matcher: Optional[Matcher] = None) -> dict:
    """导出营养缺口清单：当前在售、但营养表无数据或规格歧义的单品。

    用途：① UNKNOWN 兜底白名单（避免每次重新发现）；② 新品补录与规格确认待办；
    ③ 向官方反馈的清单。营养表是单品维度，套餐名本来就不该命中，故只统计单品。

    另并入**历史订单缺口**（origin=history-order）：已下架/限定品不在在售目录里，
    但复盘时同样查不到营养值，必须一并登记。
    """
    def enrich(entry: dict) -> dict:
        code = entry["code"]
        p = cat["products"].get(code, {})
        out = {
            "code": code, "name": entry["name"],
            "categories": p.get("categories", []), "tags": p.get("tags", []),
            "dayparts": p.get("dayparts", []),
            "price": {k: v["price"] for k, v in (p.get("prices") or {}).items()},
        }
        if entry.get("candidates"):
            out["candidates"] = entry["candidates"]
        return out

    gaps = [enrich(e) for e in unknown_list if e.get("kind") == "单品"]
    ambiguous = [enrich(e) for e in ambiguous_list if e.get("kind") == "单品"]

    # 并入历史订单缺口：按名称去重（在售目录里已登记的以目录条目为准）
    known_names = {g["name"] for g in gaps} | {a["name"] for a in ambiguous}
    if matcher is None:
        matcher = Matcher()
    history = [g for g in collect_history_gaps(matcher) if g["name"] not in known_names]
    gaps.extend(history)
    payload = {
        "_meta": {
            "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": cat["_meta"]["sources"],
            "historySource": HISTORY_ORDERS.name,
            "note": "营养表查不到或规格不唯一的单品。unknown 必须标注「热量未知」，"
                    "绝不按 0 计算；ambiguous 应让用户选择规格，禁止猜测。补录或确认后从此表移除。",
            "originNote": "origin=history-order 的条目来自脱敏历史订单（已下架/限定品，"
                          "不在当日在售目录 → 无分类与价格）。其余为当日在售目录缺口。",
        },
        "unknownCount": len(gaps),
        "historyUnknownCount": len(history),
        "ambiguousCount": len(ambiguous),
        "unknown": gaps,
        "ambiguous": ambiguous,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload


def print_calls() -> None:
    matrix = {
        "_note": "按 (门店 × 渠道 × 餐段) 采集 query-meals；套餐组成再按 code 调 query-meal-detail。"
                 "每个 Token 每分钟 ≤600 次，建议 ≤60 次/分钟并做断点续跑。",
        "query-meals": [
            {"storeCode": "<storeCode>", "orderType": 1, "beType": 1, "reservationDate": f"<今天> {t}",
             "daypart": name}
            for name, t in (("早餐", "08:00"), ("午餐", "12:00"), ("下午茶", "16:00"),
                            ("夜市", "19:00"), ("宵夜", "23:00"))
        ],
        "query-meals-delivery": [{"storeCode": "<storeCode>", "orderType": 2, "beType": 2,
                                  "beCode": "<delivery-query-stores 返回>"}],
        "query-meals-dt": [{"storeCode": "<storeCode>", "orderType": 1, "beType": 5,
                            "beCode": "<query-nearby-stores(beType=5) 返回>"}],
        "query-meal-detail": [{"storeCode": "<storeCode>", "orderType": 1, "beType": 1, "code": "<套餐 code>"}],
        "list-nutrition-foods": [],
        "落盘": "fixtures/meals.<storeCode>.dinein.<daypart>.json，剔除 image 字段后再入库",
    }
    print(json.dumps(matrix, ensure_ascii=False, indent=2))


def print_report(cat: dict) -> None:
    s = cat["stats"]
    print("=" * 58)
    print("全量目录聚合报告")
    print("=" * 58)
    print(f"快照数            : {s['snapshotCount']}  → {', '.join(str(x) for x in cat['_meta']['sources'])}")
    print(f"商品总数（去重）  : {s['productCount']}   其中 套餐 {s['comboCount']} / 单品 {s['singleCount']}")
    print(f"覆盖餐段          : {', '.join(s['dayparts'])}")
    print(f"分类数（按门店）  : {s['categoryCountByStore']}")
    print(f"套餐组成已取详情  : {s['comboDetailCount']}（其余需按 code 补 query-meal-detail）")
    nc = s["nutritionCoverage"]
    total = nc["hit"] + nc["ambiguous"] + nc["unknown"]
    rate = nc["hit"] / total * 100 if total else 0
    print(f"营养表覆盖(全部)  : 命中 {nc['hit']} / 歧义 {nc['ambiguous']} / 未知 {nc['unknown']}"
          f"  → 命中率 {rate:.1f}%")
    for kind in ("单品", "套餐"):
        c = s["nutritionCoverageByKind"][kind]
        t2 = c["hit"] + c["ambiguous"] + c["unknown"]
        if t2:
            print(f"  其中 {kind:<2}        : 命中 {c['hit']} / 歧义 {c['ambiguous']} / 未知 {c['unknown']}"
                  f"  → {c['hit']/t2*100:.1f}%")
    if s["danglingRefs"]:
        print(f"悬空引用          : {len(s['danglingRefs'])} 条（分类引用了 meals 映射里没有的 code）")
        for d in s["danglingRefs"][:5]:
            print(f"    - {d['file']} code={d['code']} 分类={d['category']}")
    if s["priceDiffs"]:
        print(f"跨餐段价格差异    : {len(s['priceDiffs'])} 个商品同 code 不同价")
        for d in s["priceDiffs"][:5]:
            print(f"    - {d['name']} {d['prices']}")
    if s["nutritionMiss"]:
        print(f"未命中营养表（前 10）: {'、'.join(s['nutritionMiss'][:10])}")
    print("-" * 58)
    print("提示：目录用于匹配与兜底；推荐候选仍须取自当次 query-meals 实时结果。")


def main() -> None:
    ap = argparse.ArgumentParser(description="全量餐品/套餐目录聚合")
    ap.add_argument("--out", default=str(OUT_DEFAULT), help="输出路径（默认 data/catalog.json）")
    ap.add_argument("--calls", action="store_true", help="只打印采集矩阵，不聚合")
    ap.add_argument("--quiet", action="store_true", help="只写文件，不打印报告")
    args = ap.parse_args()

    if args.calls:
        print_calls()
        return

    cat, coverage = build_catalog()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    gaps_path = out.parent / "nutrition-gaps.json"
    gaps = emit_gaps(cat, coverage["unknown"], coverage["ambiguous"], gaps_path, matcher=Matcher())
    if not args.quiet:
        print_report(cat)
        print(f"营养缺口        : 未收录单品 {gaps['unknownCount']} 个 / 规格歧义 {gaps['ambiguousCount']} 个"
              f" → {gaps_path.name}")
        if gaps["historyUnknownCount"]:
            print(f"  其中历史订单缺口: {gaps['historyUnknownCount']} 个"
                  f"（{HISTORY_ORDERS.name}，已下架/限定品）")
        print(f"已写入: {out}")


if __name__ == "__main__":
    main()
