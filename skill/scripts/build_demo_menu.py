#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_demo_menu.py —— 用真实采集快照生成「点餐页.html」的产品数据块。

数据来源（全部来自 mcd-mcp 实测，非编造）：
  fixtures/meals.3570190.dinein.breakfast.json   早餐 92 项 (reservationDate=08:00)
  fixtures/meals.3570190.dinein.lunch.json      午餐 108 项 (12:00)
  fixtures/meals.3570190.dinein.dinner.json     晚餐 110 项 (19:00)  ← 本次补齐
  fixtures/meals.3570190.dinein.night.json      宵夜 110 项 (23:36 实测)
  fixtures/meals.*.afternoon.diff.json          下午茶 ≡ 午餐（实测逐条一致）→ 复用午餐
  fixtures/nutrition.raw.txt                    官方营养表 160 项
  fixtures/meal-detail.990000{4064,5466,3458}.json  套餐组成（真实 rounds + diffPrice）

合规：不使用官方图片（image 字段一律剔除）；不使用商标 Logo。
输出：把生成的 NUTRI / MENU / ROUNDS / MODS 四段 JS 打印出来，供写入演示页。
"""
import json, os, re, sys
from collections import OrderedDict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FX = os.path.join(BASE, "fixtures")

DP_FILES = {
    "早餐": "meals.3570190.dinein.breakfast.json",
    "午餐": "meals.3570190.dinein.lunch.json",
    "晚餐": "meals.3570190.dinein.dinner.json",
    "宵夜": "meals.3570190.dinein.night.json",
}
# 下午茶（随便吃吃）实测与午餐逐条一致，复用午餐快照
DP_ALIAS = {"随便吃吃": "午餐"}

# ────────────────────────────── 1. 读快照 ──────────────────────────────
def load_snapshot(fn, dp):
    """只保留 meals 映射里真实存在的条目——categories 里可能含悬空引用（无价格）。"""
    d = json.load(open(os.path.join(FX, fn), encoding="utf-8"))
    cat_of, tags_of = {}, {}
    for c in d["categories"]:
        cat = c["name"].replace("\n", "")
        for item in c["items"]:
            code, tags = (item[0], item[1]) if isinstance(item, list) else (item.get("code"), item.get("tags", []))
            cat_of.setdefault(code, cat)
            for t in (tags or []):
                tags_of.setdefault(code, [])
                if t not in tags_of[code]:
                    tags_of[code].append(t)
    out = {}
    for code, m in d["meals"].items():
        out[code] = {
            "cat": cat_of.get(code, ""),
            "tags": tags_of.get(code, []),
            "name": m["name"],
            "price": {dp: float(m["price"])},
            "orig": {dp: float(m.get("originalPrice") or m["price"])},
        }
    return out

registry = {}
for DP, fn in DP_FILES.items():
    snap = load_snapshot(fn, DP)
    for code, e in snap.items():
        tgt = registry.setdefault(code, {"name": e["name"], "tags": [], "cats": {}, "price": {}, "orig": {}})
        tgt["name"] = e["name"]
        tgt["cats"][DP] = e["cat"]
        tgt["price"][DP] = e["price"][DP]
        tgt["orig"][DP] = e["orig"][DP]
        for t in e["tags"]:
            if t not in tgt["tags"]:
                tgt["tags"].append(t)
# 下午茶复用午餐
for code, e in list(registry.items()):
    if "午餐" in e["cats"]:
        e["cats"]["随便吃吃"] = e["cats"]["午餐"]
        e["price"]["随便吃吃"] = e["price"]["午餐"]
        e["orig"]["随便吃吃"] = e["orig"]["午餐"]

# ────────────────────────────── 2. 营养表 ──────────────────────────────
NUTRI_SRC = OrderedDict()
for line in open(os.path.join(FX, "nutrition.raw.txt"), encoding="utf-8"):
    line = line.strip()
    m = re.match(r"^(\S+?),null,(\d+),(\d+),([\d.]+),([\d.]+),([\d.]+),(\d+),([\d.]+)$", line)
    if m:
        n, kj, kcal, p, f, c, na, ca = m.groups()
        NUTRI_SRC[n] = dict(kcal=int(kcal), p=float(p), f=float(f), c=float(c), na=int(na))

ALIAS = json.load(open(os.path.join(BASE, "data", "alias.json"), encoding="utf-8"))
ALIAS_MAP = ALIAS.get("mappings", {})
ALIAS_DEF = ALIAS.get("defaults", {})

def resolve_nutri(name):
    if name in NUTRI_SRC:
        return name
    if name in ALIAS_MAP and ALIAS_MAP[name] in NUTRI_SRC:
        return ALIAS_MAP[name]
    if name in ALIAS_DEF and ALIAS_DEF[name] in NUTRI_SRC:
        return ALIAS_DEF[name]
    return None

# ────────────────────────────── 3. 角色分类 ──────────────────────────────
COMBO_KW = ["件套", "套餐", "组合", "随心拼", "随心配", "双全盒", "小食盘",
            "分享餐", "乐园餐", "双人餐", "单人餐", "八件套", "拼（", "任选", "随心选"]
NONFOOD_KW = ["蘸酱", "风味酱", "山葵酱", "按摩捶"]
DRINK_KW = ["咖啡", "奶铁", "美式", "可乐", "雪碧", "红茶", "果汁", "苹果汁", "牛奶", "豆浆",
            "燕麦奶", "阿芙佳朵", "黑巧", "怡泉", "鲜萃", "柠柠", "橙橙", "冰咖", "奶"]
DESSERT_KW = ["圆筒", "麦旋风", "新地", "派", "冰淇淋"]
SNACK_KW = ["薯条", "薯饼", "鸡块", "鸡翅", "玉米杯", "苹果片", "油条", "香肠", "鸡排",
            "芝士条", "扭扭薯", "V翅", "脆汁鸡", "炸鸡", "鸡"]
MAIN_KW = ["堡", "汉堡", "麦满分", "卷"]

DRINK_CATS = {"饮品", "麦咖啡™", "一早现磨"}
COMBO_CATS = {"500大卡套餐", "开心乐园", "随心配1+1", "精选单人餐", "大堡口福单人餐"}

def classify(name, cats, tags):
    if any(k in name for k in NONFOOD_KW):
        return "非食品"
    if any(k in name for k in COMBO_KW):
        return "套餐"
    if any(c in COMBO_CATS for c in cats.values()):
        return "套餐"
    if any(c in DRINK_CATS for c in cats.values()):
        return "饮品"
    if any(k in name for k in DESSERT_KW):
        return "甜品"
    if any(k in name for k in DRINK_KW):
        return "饮品"
    if any(k in name for k in MAIN_KW):
        return "主食"
    if any(k in name for k in SNACK_KW):
        return "小食"
    # 分类兜底
    joined = " ".join(cats.values())
    if any(k in joined for k in ["小食", "甜品"]):
        return "小食"
    if "汉堡" in joined or "堡" in joined:
        return "主食"
    return "其他"

# ────────────────────────────── 4. 套餐组成（ROUNDS） ──────────────────────────────
ROUNDS = {}
for fn in ["meal-detail.9900004064.json", "meal-detail.9900005466.json", "meal-detail.9900003458.json"]:
    p = os.path.join(FX, fn)
    if not os.path.exists(p):
        continue
    d = json.load(open(p, encoding="utf-8"))
    name = d.get("name") or d.get("_meta", {}).get("name")
    rounds = []
    for r in d.get("rounds", []):
        ch = []
        for c in r.get("choices", []):
            if isinstance(c, list):          # 精简格式 [名称, 差价, 是否默认]
                ch.append([c[0], float(c[1]), bool(c[2])])
                continue
            dp = c.get("diffPrice", "+ ¥0") or "+ ¥0"
            m = re.search(r"([+-])\s*¥\s*([\d.]+)", dp)
            val = float(m.group(2)) * (-1 if m.group(1) == "-" else 1)
            ch.append([c["name"], val, bool(c.get("isDefault"))])
        # 一个轮次只保留第一个 isDefault（接口可能给多个）
        seen = False
        for c in ch:
            if c[2]:
                if seen:
                    c[2] = False
                seen = True
        rounds.append({"name": r.get("name"), "min": r.get("minQuantity", 1),
                       "max": r.get("maxQuantity", 1), "choices": ch})
    if rounds:
        ROUNDS[name] = rounds

# ────────────────────────────── 5. 特调（MODS）──────────────────────────────
# 依据真实响应里的 modification 组生成：冰量(必选其一)、加料(可多选)、配料(取消即不要)
ICE_ITEMS = ["可乐", "雪碧", "怡泉", "红茶", "柠柠", "橙橙", "冰咖", "冰美式", "冰奶铁",
             "冰燕麦", "冰浓浓", "无糖可口可乐"]
def build_mods(name, role):
    if role == "非食品":
        return None
    out = []
    if role == "饮品" and any(k in name for k in ICE_ITEMS):
        out.append({"g": "冰量", "min": 1, "max": 1,
                    "values": [["标准", 0, True], ["去冰", 0, False], ["多冰", 0, False], ["少冰", 0, False]]})
    if role == "饮品" and any(k in name for k in ["黑巧", "奶铁", "拿铁", "燕麦"]):
        out.append({"g": "可选加料", "min": 0, "max": 1,
                    "values": [["换燕麦奶", 2, False]]})
    if role == "主食" and any(k in name for k in ["堡", "汉堡", "麦满分"]):
        out.append({"g": "配料", "min": 0, "max": 3, "values": [["吉士", 0, True], ["生菜", 0, True]]})
    return out or None

# ────────────────────────────── 6. 组装 MENU ──────────────────────────────
CAT_ORDER = {}
for DP in DP_FILES:
    snap = json.load(open(os.path.join(FX, DP_FILES[DP]), encoding="utf-8"))
    CAT_ORDER[DP] = [c["name"].replace("\n", "") for c in snap["categories"]]
CAT_ORDER["随便吃吃"] = CAT_ORDER["午餐"]

menu = []
nutri_used = OrderedDict()
unknown = []
for code, e in registry.items():
    name = e["name"]
    if not name:
        continue
    role = classify(name, e["cats"], e["tags"])
    if role in ("非食品",):
        continue
    dps = [d for d in ["早餐", "午餐", "随便吃吃", "晚餐", "宵夜"] if d in e["cats"]]
    if not dps:
        continue
    rn = resolve_nutri(name)
    if rn:
        n = NUTRI_SRC[rn]
        nutri_used[rn] = n
    else:
        unknown.append(name)
    price = {d: round(e["price"][d], 2) for d in dps}
    orig = {d: round(e["orig"][d], 2) for d in dps if e["orig"][d] > e["price"][d]}
    # 展示分类：取该商品在最多餐段里出现的分类
    cat = e["cats"][dps[0]]
    item = {"n": name, "role": role, "cat": cat, "dp": dps, "p": price}
    if orig:
        item["o"] = orig
    if e["tags"]:
        item["t"] = e["tags"]
    if role == "套餐" and name in ROUNDS:
        item["combo"] = True
        defaults = [ (r["choices"][[c[2] for c in r["choices"]].index(True)][0]
                      if True in [c[2] for c in r["choices"]] else r["choices"][0][0])
                     for r in ROUNDS[name] ]
        item["def"] = defaults
    menu.append(item)

# 排序：按餐段分类顺序 + 分类内原序
def sort_key(it):
    dps = it["dp"]
    primary = "午餐" if "午餐" in dps else dps[0]
    try:
        ci = CAT_ORDER[primary].index(it["cat"])
    except ValueError:
        ci = 99
    return (list(["早餐", "午餐", "随便吃吃", "晚餐", "宵夜"]).index(primary), ci, it["n"])
menu.sort(key=sort_key)

# ────────────────────────────── 7. 输出 JS ──────────────────────────────
def js_num(v):
    return str(int(v)) if float(v).is_integer() else str(round(float(v), 2))

def js_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

def emit_nutri():
    lines = ["const NUTRI = {"]
    body = []
    for k, v in nutri_used.items():
        body.append('  %s:{kcal:%d,p:%s,f:%s,c:%s,na:%d}' % (
            js_str(k), v["kcal"], js_num(v["p"]), js_num(v["f"]), js_num(v["c"]), v["na"]))
    lines.append(",\n".join(body))
    lines.append("};")
    return "\n".join(lines)

def emit_menu():
    out = ["const MENU = ["]
    rows = []
    for it in menu:
        f = ["n:" + js_str(it["n"]), "role:" + js_str(it["role"]), "cat:" + js_str(it["cat"]),
             "dp:[" + ",".join(js_str(d) for d in it["dp"]) + "]",
             "p:{" + ",".join('%s:%s' % (js_str(d), js_num(v)) for d, v in it["p"].items()) + "}"]
        if it.get("o"):
            f.append("o:{" + ",".join('%s:%s' % (js_str(d), js_num(v)) for d, v in it["o"].items()) + "}")
        if it.get("t"):
            f.append("t:[" + ",".join(js_str(t) for t in it["t"]) + "]")
        if it.get("combo"):
            f.append("combo:1")
            f.append("def:[" + ",".join(js_str(x) for x in it["def"]) + "]")
        rows.append("  {" + ",".join(f) + "}")
    out.append(",\n".join(rows))
    out.append("];")
    return "\n".join(out)

def emit_rounds():
    out = ["const ROUNDS = {"]
    blocks = []
    for name, rounds in ROUNDS.items():
        rs = []
        for r in rounds:
            ch = ",".join("[%s,%s,%s]" % (js_str(c[0]), js_num(c[1]), "true" if c[2] else "false")
                          for c in r["choices"])
            rs.append('    {name:%s,min:%d,max:%d,choices:[%s]}' % (js_str(r["name"]), r["min"], r["max"], ch))
        blocks.append("  %s:[\n%s\n  ]" % (js_str(name), ",\n".join(rs)))
    out.append(",\n".join(blocks))
    out.append("};")
    return "\n".join(out)

def emit_mods():
    out = ["const MODS = {"]
    blocks = []
    for it in menu:
        m = build_mods(it["n"], it["role"])
        if not m:
            continue
        gs = []
        for g in m:
            vs = ",".join("[%s,%s,%s]" % (js_str(v[0]), js_num(v[1]), "true" if v[2] else "false")
                          for v in g["values"])
            gs.append('{g:%s,min:%d,max:%d,values:[%s]}' % (js_str(g["g"]), g["min"], g["max"], vs))
        blocks.append("  %s:[%s]" % (js_str(it["n"]), ",".join(gs)))
    out.append(",\n".join(blocks))
    out.append("};")
    return "\n".join(out)

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if mode == "stats":
        from collections import Counter
        print("快照商品总数（去重）:", len(registry))
        print("进入页面的商品数:", len(menu))
        print("角色分布:", Counter(i["role"] for i in menu))
        print("营养命中:", len(nutri_used), " 未命中:", len(unknown))
        print("有 ROUNDS 的套餐:", list(ROUNDS))
        print("有 MODS 的商品数:", sum(1 for i in menu if build_mods(i["n"], i["role"])))
        print("\n未命中营养表（前 40）:")
        for u in unknown[:40]:
            print("  -", u)
        print("\n各餐段商品数:")
        for d in ["早餐", "午餐", "随便吃吃", "晚餐", "宵夜"]:
            print("  %s: %d" % (d, sum(1 for i in menu if d in i["dp"])))
        print("\n各餐段分类:", {d: CAT_ORDER[d] for d in CAT_ORDER})
    else:
        key = {"nutri": emit_nutri, "menu": emit_menu, "rounds": emit_rounds, "mods": emit_mods}[mode]
        print(key())
