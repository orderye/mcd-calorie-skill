#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_meal_details.py — 批量采集套餐组成（query-meal-detail），补全 ROUNDS。

背景：query-meals 只给「卖什么、多少钱」，套餐「由什么组成」必须另取
query-meal-detail（按 code 逐个）。PRD §14 记录采集剩余量：套餐详情 89 个 code 需逐个取。

本脚本直连 mcd-mcp 的 HTTP 端点（streamable http，JSON-RPC 2.0），把每个套餐的
rounds/choices 落成精简 fixture：
    fixtures/meal-detail.<code>.json
裁剪规则（与既有 fixture 一致）：
  · 剔除 image（合规红线：不使用官方图片素材）
  · modification 只保留 hasModification 布尔，不落内部 key 细节
  · 保留 code / name / isDefault / diffPrice / supportModify / minQuantity / maxQuantity

用法（需先导出令牌，见下）：
  export MCD_MCP_TOKEN=<你的 mcd-mcp Bearer Token>
  python3 scripts/fetch_meal_details.py --list          # 只列要采集的 code（不联网）
  python3 scripts/fetch_meal_details.py                 # 采集缺失的套餐详情
  python3 scripts/fetch_meal_details.py --force         # 全部重采
  python3 scripts/fetch_meal_details.py --only 9900016524,9900016144

令牌只从环境变量 MCD_MCP_TOKEN 读取，源码里不留任何凭证。
"""
from __future__ import annotations

import argparse, json, os, sys, time, urllib.request, urllib.error
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
FX = BASE / "fixtures"

URL = "https://mcp.mcd.cn"
# 令牌只从环境变量读取，禁止写进源码（仓库公开）。
#   export MCD_MCP_TOKEN=xxxx
TOKEN = os.environ.get("MCD_MCP_TOKEN", "")
if not TOKEN:
    sys.exit("缺少 MCD_MCP_TOKEN 环境变量：export MCD_MCP_TOKEN=<你的 mcd-mcp Bearer Token>")
HDR = {
    "Authorization": "Bearer " + TOKEN,
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
}
STORE = "3570190"

DP_FILES = {
    "早餐": "meals.3570190.dinein.breakfast.json",
    "午餐": "meals.3570190.dinein.lunch.json",
    "晚餐": "meals.3570190.dinein.dinner.json",
    "宵夜": "meals.3570190.dinein.night.json",
}
DP_TIME = {"早餐": "08:00", "午餐": "12:00", "随便吃吃": "16:00", "晚餐": "19:00", "宵夜": "23:00"}


def rpc(method, params=None, idn=1):
    body = {"jsonrpc": "2.0", "id": idn, "method": method}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=HDR, method="POST")
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode()


def init():
    rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "workbuddy-fetch", "version": "1.0"}})


def call_detail(code, daypart="午餐"):
    txt = rpc("tools/call", {
        "name": "query-meal-detail",
        "arguments": {"storeCode": STORE, "orderType": 1, "beType": 1, "code": code,
                      "reservationDate": "2026-10-10 " + DP_TIME.get(daypart, "12:00")},
    }, 2)
    d = json.loads(txt)
    if d.get("error"):
        raise RuntimeError("rpc error: %s" % d["error"])
    sc = d["result"].get("structuredContent") or {}
    if not sc.get("success"):
        raise RuntimeError("api not success: %s" % sc.get("message"))
    return sc


# ── 套餐识别（与 build_demo_menu.classify 同源规则） ──
COMBO_KW = ["件套", "套餐", "组合", "随心拼", "随心配", "双全盒", "小食盘",
            "分享餐", "乐园餐", "双人餐", "单人餐", "八件套", "拼（", "任选", "随心选"]
NONFOOD_KW = ["蘸酱", "风味酱", "山葵酱", "按摩捶"]
COMBO_CATS = {"500大卡套餐", "开心乐园", "随心配1+1", "精选单人餐", "大堡口福单人餐"}


def is_combo(name, cats):
    if any(k in name for k in NONFOOD_KW):
        return False
    if any(k in name for k in COMBO_KW):
        return True
    return any(c in COMBO_CATS for c in cats)


def combo_codes():
    """返回 {code: (name, 首个有售餐段)}，仅套餐。"""
    reg = {}
    for dp, fn in DP_FILES.items():
        p = FX / fn
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        cat_of = {}
        for c in d["categories"]:
            cat = c["name"].replace("\n", "")
            for item in c["items"]:
                code = item[0] if isinstance(item, list) else item.get("code")
                cat_of.setdefault(code, cat)
        for code, m in d["meals"].items():
            e = reg.setdefault(code, {"name": m["name"], "cats": [], "dp": None})
            e["name"] = m["name"]
            cat = cat_of.get(code)
            if cat and cat not in e["cats"]:
                e["cats"].append(cat)
            if e["dp"] is None:
                e["dp"] = dp
    return {c: (e["name"], e["dp"]) for c, e in reg.items() if is_combo(e["name"], e["cats"])}


def compact(sc, code, daypart):
    """裁剪成与既有 fixture 一致的形态。"""
    data = sc["data"]
    rounds = []
    for r in data.get("rounds", []):
        ch = []
        for c in r.get("choices", []):
            item = {
                "code": c.get("code"),
                "name": c.get("name"),
                "isDefault": c.get("isDefault", 0),
                "diffPrice": c.get("diffPrice", "+ ¥0"),
                "supportModify": bool(c.get("supportModify")),
            }
            if c.get("modification"):
                item["hasModification"] = True
            ch.append(item)
        rd = {
            "id": r.get("id"),
            "name": r.get("name"),
            "quantity": r.get("quantity", 1),
            "minQuantity": r.get("minQuantity", 1),
            "maxQuantity": r.get("maxQuantity", 1),
            "choices": ch,
        }
        if r.get("category"):
            rd["category"] = r["category"]
        rounds.append(rd)
    return {
        "_meta": {
            "storeCode": STORE, "orderType": 1, "beType": 1,
            "daypart": daypart,
            "fetchedAt": sc.get("datetime"),
            "traceId": sc.get("traceId"),
            "source": "query-meal-detail",
            "note": "bulk 采集自 fetch_meal_details.py；剔除 image 与 modification 内部 key，仅保留 hasModification。",
        },
        "code": code,
        "name": data.get("name"),
        "price": data.get("price"),
        "supportModify": bool(data.get("supportModify")),
        "rounds": rounds,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--sleep", type=float, default=0.15)
    a = ap.parse_args()

    codes = combo_codes()
    print("套餐总数: %d" % len(codes))

    if a.only:
        want = [c.strip() for c in a.only.split(",") if c.strip()]
    elif a.force:
        want = sorted(codes)
    else:
        want = sorted(c for c in codes if not (FX / ("meal-detail.%s.json" % c)).exists())

    print("待采集: %d" % len(want))
    if a.list:
        for c in want:
            print("  %s  %s  (%s)" % (c, codes[c][0], codes[c][1]))
        return

    init()
    ok, fail, skip = 0, [], 0
    for i, code in enumerate(want, 1):
        name, dp = codes.get(code, ("?", "午餐"))
        try:
            sc = call_detail(code, dp)
            fx = compact(sc, code, dp)
            if not fx["rounds"]:
                skip += 1
                print("  [%d/%d] %s %s → 无 rounds（非套餐组成？）" % (i, len(want), code, name))
                continue
            (FX / ("meal-detail.%s.json" % code)).write_text(
                json.dumps(fx, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            ok += 1
            print("  [%d/%d] %s %s → %d 轮 / %d 选项" % (
                i, len(want), code, (fx["name"] or name)[:22], len(fx["rounds"]),
                sum(len(r["choices"]) for r in fx["rounds"])))
        except Exception as ex:                     # noqa: BLE001
            fail.append((code, name, str(ex)[:80]))
            print("  [%d/%d] %s %s → 失败 %s" % (i, len(want), code, name, str(ex)[:80]))
        time.sleep(a.sleep)

    print("\n完成：成功 %d / 跳过 %d / 失败 %d" % (ok, skip, len(fail)))
    for c, n, e in fail:
        print("  ✗ %s %s — %s" % (c, n, e))


if __name__ == "__main__":
    main()
