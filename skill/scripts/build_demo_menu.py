#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_demo_menu.py —— 用真实采集快照生成「food.html」的产品数据块。

数据来源（全部来自 mcd-mcp 实测，非编造）：
  fixtures/meals.3570190.dinein.breakfast.json    早餐 92 项 (reservationDate=08:00)
  fixtures/meals.3570190.dinein.lunch.json        午餐 108 项 (12:00)
  fixtures/meals.3570190.dinein.dinner.json       晚餐 110 项 (19:00)
  fixtures/meals.3570190.dinein.night.json        宵夜 110 项 (23:36 实测)
  fixtures/meals.*.afternoon.diff.json            下午茶 ≡ 午餐（实测逐条一致）→ 复用午餐
  fixtures/meal-detail.<code>.json                套餐组成（**全部 90 个套餐**，fetch_meal_details.py 批量采集）
  fixtures/nutrition.raw.txt                      官方营养表 157 项
  data/alias.json                                 别名归一 + 零热量（非食品）关键词

合规：不使用官方图片（image 字段一律剔除）；不使用商标 Logo。
输出：CATS / NUTRI / ZERO / TIERS / MENU / ROUNDS / MODS 七段 JS，供写入演示页。

  python3 scripts/build_demo_menu.py stats      # 统计
  python3 scripts/build_demo_menu.py menu       # 打印某一段（cats|nutri|zero|menu|rounds|mods）
"""
import json, os, re, glob, sys
from collections import OrderedDict
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FX = os.path.join(BASE, "fixtures")

DAYPARTS = ["早餐", "午餐", "随便吃吃", "晚餐", "宵夜"]

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
        tgt = registry.setdefault(code, {"name": e["name"], "tags": [], "cats": [], "price": {}, "orig": {}})
        tgt["name"] = e["name"]
        if e["cat"] and e["cat"] not in tgt["cats"]:
            tgt["cats"].append(e["cat"])
        tgt["price"][DP] = e["price"][DP]
        tgt["orig"][DP] = e["orig"][DP]
        for t in e["tags"]:
            if t not in tgt["tags"]:
                tgt["tags"].append(t)
# 下午茶复用午餐（实测逐条一致）
for code, e in list(registry.items()):
    if "午餐" in e["price"]:
        e["price"]["随便吃吃"] = e["price"]["午餐"]
        e["orig"]["随便吃吃"] = e["orig"]["午餐"]

# ────────────────────────────── 2. 营养表 ──────────────────────────────
NUTRI_SRC = OrderedDict()
for line in open(os.path.join(FX, "nutrition.raw.txt"), encoding="utf-8"):
    line = line.strip()
    # 第 2 列是 nutritionDescription：多数为 null，但新版条目会给「能量约鲈鱼1条」这类描述，
    # 所以不能写死 ,null,（否则会漏掉芝士安格斯厚牛堡等条目）
    m = re.match(r"^([^,]+),([^,]*),(\d+),(\d+),([\d.]+),([\d.]+),([\d.]+),(\d+),([\d.]+)$", line)
    if m:
        n, desc, kj, kcal, p, f, c, na, ca = m.groups()
        NUTRI_SRC[n] = dict(kcal=int(kcal), p=float(p), f=float(f), c=float(c), na=int(na),
                            desc=(desc if desc != "null" else None))

ALIAS = json.load(open(os.path.join(BASE, "data", "alias.json"), encoding="utf-8"))
ALIAS_MAP = ALIAS.get("mappings", {})
ALIAS_DEF = ALIAS.get("defaults", {})
ZERO_KW = ALIAS.get("_zeroKcal", {}).get("keywords", [])

# 非食品判定用词（见 is_zero）
TOY_KW = ["玩具", "手办", "贴纸", "盲盒", "按摩捶", "痒痒挠"]
SAUCE_KW = ["风味酱", "蘸酱", "山葵酱", "酱包", "糖醋酱", "酸甜酱"]
FOOD_HINT_KW = ["薯", "鸡", "堡", "块", "球", "条", "片", "腿", "排", "卷", "麦满分", "玉米",
                "咖啡", "茶", "可乐", "雪碧", "奶", "汁", "豆浆", "苹果", "油条", "香肠",
                "芝士", "麦旋风", "圆筒", "派", "冰淇淋", "饭", "蛋", "薯条", "土豆"]

def norm_name(s):
    """归一化：去空格、全角括号转半角、剥离括号内规格说明。"""
    s = s.replace(" ", "").replace("（", "(").replace("）", ")")
    s = re.sub(r"\([^)]*\)", "", s)
    return s

# 归一化索引：仅当归一化后唯一命中才采用，避免把「冰/热」「中/大杯」猜成某一规格
NORM_IDX = {}
for n in NUTRI_SRC:
    NORM_IDX.setdefault(norm_name(n), []).append(n)

def resolve_nutri(name):
    if name in NUTRI_SRC:
        return name
    if name in ALIAS_MAP and ALIAS_MAP[name] in NUTRI_SRC:
        return ALIAS_MAP[name]
    if name in ALIAS_DEF and ALIAS_DEF[name] in NUTRI_SRC:
        return ALIAS_DEF[name]
    # 剥离品牌前缀后重试（如「麦咖啡™热美式中杯」→「热美式中杯」）
    stripped = name.replace("麦咖啡™", "")
    if stripped != name:
        if stripped in NUTRI_SRC:
            return stripped
        if stripped in ALIAS_MAP and ALIAS_MAP[stripped] in NUTRI_SRC:
            return ALIAS_MAP[stripped]
    for cand in (name, stripped):
        key = norm_name(cand)
        if key in ALIAS_MAP and ALIAS_MAP[key] in NUTRI_SRC:
            return ALIAS_MAP[key]
        cands = NORM_IDX.get(key, [])
        if len(cands) == 1:
            return cands[0]
    return None

def is_zero(name):
    """零热量 / 非食品项（玩具、单卖蘸酱）→ 按 0 千卡计，而不是「未知」。

    判据要点：**名字里同时提到食物时不算非食品**——
    「5块心形薯饼+韩式辣椒黄油风味酱」「韩式烟熏芝士风味酱麦麦脆汁鸡-腿」是含酱的食物，
    不能因为含「风味酱」就按 0 计（那会把一顿正餐的热量抹掉）。
    """
    if any(k in name for k in TOY_KW):
        return True
    if any(k in name for k in SAUCE_KW) and not any(k in name for k in FOOD_HINT_KW):
        return True
    return False

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

def kind_of(name):
    """按名称粗判品类（用于 ROUNDS 的轮次标注与兜底）。"""
    if is_zero(name) or any(k in name for k in NONFOOD_KW):
        return "非食品"
    if any(k in name for k in DESSERT_KW):
        return "甜品"
    if any(k in name for k in DRINK_KW):
        return "饮品"
    if any(k in name for k in MAIN_KW):
        return "主食"
    if any(k in name for k in SNACK_KW):
        return "小食"
    return ""

def classify(name, cats, tags):
    if any(k in name for k in NONFOOD_KW):
        return "非食品"
    if any(k in name for k in COMBO_KW):
        return "套餐"
    if any(c in COMBO_CATS for c in cats):
        return "套餐"
    if any(c in DRINK_CATS for c in cats):
        return "饮品"
    k = kind_of(name)
    if k and k != "非食品":
        return k
    # 分类兜底
    joined = " ".join(cats)
    if any(k in joined for k in ["小食", "甜品"]):
        return "小食"
    if "汉堡" in joined or "堡" in joined:
        return "主食"
    return "其他"

# ────────────────────────────── 4. 套餐组成（ROUNDS） ──────────────────────────────
ROUND_CAT_KW = [
    ("饮品", ["饮料", "饮品", "咖啡", "奶茶"]),
    ("小食", ["小食", "薯", "鸡块", "鸡球", "玉米杯", "苹果片"]),
    ("主食", ["主食", "汉堡", "麦满分"]),
    ("非食品", ["玩具"]),
]

# 品类的权威来源：菜单快照里该商品自己的角色（比关键词可靠，
# 例如轮次名「巨无霸」「麦香鱼」不含「堡」字，但它在菜单里就是主食）
ROLE_OF = {}
for e in registry.values():
    ROLE_OF.setdefault(e["name"], classify(e["name"], e["cats"], e["tags"]))

def _choice_name(c):
    """兼容两种 fixture 形态取选项名。"""
    return c[0] if isinstance(c, list) else c.get("name", "")

def round_category(r):
    """轮次品类：优先接口给的 category，其次菜单里的真实角色，再其次关键词。"""
    if r.get("category"):
        return r["category"]
    nm = (r.get("name") or "").strip()
    if nm in ROLE_OF and ROLE_OF[nm] in ("主食", "小食", "甜品", "饮品"):
        return ROLE_OF[nm]
    for cat, kws in ROUND_CAT_KW:
        if any(k in nm for k in kws):
            return cat
    if is_zero(nm) or any(k in nm for k in NONFOOD_KW):
        return "非食品"
    choices = r.get("choices", []) or []
    # 轮次名常就是某个单品名（「新升级巨无霸」「板烧鸡腿堡」）→ 用选项名反推
    for c in choices:
        cn = _choice_name(c)
        if cn in ROLE_OF and ROLE_OF[cn] in ("主食", "小食", "甜品", "饮品"):
            return ROLE_OF[cn]
    for c in choices:
        k = kind_of(_choice_name(c))
        if k:
            return k
    for cat, kws in ROUND_CAT_KW:
        if any(any(k in _choice_name(c) for k in kws) for c in choices):
            return cat
    return ""

def read_detail(fn):
    """兼容两种 fixture 形态：精简数组 [name,diff,isDefault] 与对象形态。"""
    d = json.load(open(fn, encoding="utf-8"))
    name = d.get("name") or d.get("_meta", {}).get("name")
    out = []
    for r in d.get("rounds", []) or []:
        ch = []
        for c in r.get("choices", []):
            if isinstance(c, list):
                ch.append([c[0], float(c[1]), bool(c[2])])
            else:
                dp = c.get("diffPrice", "+ ¥0") or "+ ¥0"
                m = re.search(r"([+-])\s*¥\s*([\d.]+)", dp)
                val = float(m.group(2)) * (-1 if m.group(1) == "-" else 1) if m else 0.0
                ch.append([c["name"], val, bool(c.get("isDefault"))])
        # 一个轮次只保留第一个 isDefault（接口可能给多个）
        seen = False
        for c in ch:
            if c[2]:
                if seen:
                    c[2] = False
                seen = True
        out.append({"name": (r.get("name") or "").strip(), "min": r.get("minQuantity", 1),
                    "max": r.get("maxQuantity", 1), "category": round_category(r), "choices": ch})
    return name, out

DETAIL_BY_CODE = {}          # code → rounds（**以 code 为准**，不用名称匹配）
for fn in sorted(glob.glob(os.path.join(FX, "meal-detail.*.json"))):
    code = re.search(r"meal-detail\.(\d+)\.json$", fn).group(1)
    try:
        name, rounds = read_detail(fn)
    except Exception as ex:                                  # noqa: BLE001
        print("⚠️ 读取失败 %s: %s" % (os.path.basename(fn), ex), file=sys.stderr)
        continue
    if not (name and rounds):
        continue
    if code in DETAIL_BY_CODE:
        old = sum(len(r["choices"]) for r in DETAIL_BY_CODE[code])
        new = sum(len(r["choices"]) for r in rounds)
        if new <= old:
            continue
    DETAIL_BY_CODE[code] = rounds

# ★ 以 code 为键的原因：query-meal-detail 返回的名称常与 query-meals 不同——
#   9900005453 菜单叫「麦香鸡套餐」、详情叫「麦香鸡中套餐」；
#   9900005449 菜单「吉士汉堡包套餐」、详情「吉士汉堡包中套餐」；
#   9900013411 菜单「精选麦满分套餐」、详情「猪柳蛋麦满分套餐」。
#   按名称 join 会漏掉 8 个套餐，按 code 则 100% 命中。
DETAIL_NAMES = {}
for fn in sorted(glob.glob(os.path.join(FX, "meal-detail.*.json"))):
    code = re.search(r"meal-detail\.(\d+)\.json$", fn).group(1)
    try:
        d = json.load(open(fn, encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        continue
    if d.get("name"):
        DETAIL_NAMES[code] = d["name"]

ROUNDS = {}                  # 菜单名 → rounds（页面按名索引，由 code 映射生成）

# ────────────────────────────── 5. 零热量 / 非食品集合 ──────────────────────────────
# 只收集「真正出现在套餐选项里」的非食品名（玩具、单卖蘸酱），不塞进菜单外的东西
ZERO_NAMES = OrderedDict()
for rounds in DETAIL_BY_CODE.values():
    for r in rounds:
        for c in r["choices"]:
            if is_zero(c[0]) and not resolve_nutri(c[0]):
                ZERO_NAMES[c[0]] = True

# ────────────────────────────── 6. 特调（MODS）──────────────────────────────
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

# ────────────────────────────── 7. 组装 MENU ──────────────────────────────
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
    dps = [d for d in DAYPARTS if d in e["price"]]
    if not dps:
        continue
    rn = resolve_nutri(name)
    if rn:
        nutri_used[rn] = NUTRI_SRC[rn]
    elif not is_zero(name):
        unknown.append(name)
    price = {d: round(e["price"][d], 2) for d in dps}
    orig = {d: round(e["orig"][d], 2) for d in dps if e["orig"][d] > e["price"][d]}
    item = {"n": name, "role": role, "c": e["cats"], "dp": dps, "p": price}
    if orig:
        item["o"] = orig
    if e["tags"]:
        item["t"] = e["tags"]
    if role == "套餐" and code in DETAIL_BY_CODE:
        rounds = DETAIL_BY_CODE[code]
        defaults = [(r["choices"][[c[2] for c in r["choices"]].index(True)][0]
                     if True in [c[2] for c in r["choices"]] else r["choices"][0][0])
                    for r in rounds]
        item["combo"] = True
        item["def"] = defaults
        ROUNDS[name] = rounds
    menu.append(item)

# 套餐选项也要能查到热量 —— 把 ROUNDS 里出现的可解析名称补进 NUTRI
for rounds in DETAIL_BY_CODE.values():
    for r in rounds:
        for c in r["choices"]:
            rn = resolve_nutri(c[0])
            if rn:
                nutri_used[rn] = NUTRI_SRC[rn]

# ★ 页面查表用的名字 → 营养数据。以「显示名」为键，别名各写一份，
#   否则 baseKcal("5块麦乐鸡") 查不到 NUTRI["麦乐鸡5块"]，会误报「热量未知」。
nutri_out = OrderedDict()
def add_nutri(name):
    rn = resolve_nutri(name)
    if rn:
        nutri_out[name] = NUTRI_SRC[rn]

for it in menu:
    add_nutri(it["n"])
for rounds in DETAIL_BY_CODE.values():
    for r in rounds:
        for c in r["choices"]:
            add_nutri(c[0])

# 同名合并：实测「脆薯饼」有两个 code（4825 仅早餐 / 521741 午晚，
# 同价同料）——它们是同一商品在餐段间的编码差异，合成一条，否则菜单会出现两张一样的卡。
# 页面全部按名称索引（item / NUTRI / ROUNDS），同名重复必然出问题。
_merged = OrderedDict()
for it in menu:
    cur = _merged.get(it["n"])
    if cur is None:
        _merged[it["n"]] = it
        continue
    for d in it["dp"]:
        if d not in cur["dp"]:
            cur["dp"].append(d)
    for c in it["c"]:
        if c not in cur["c"]:
            cur["c"].append(c)
    for t in it.get("t", []):
        cur.setdefault("t", [])
        if t not in cur["t"]:
            cur["t"].append(t)
    for d, v in it["p"].items():
        cur["p"].setdefault(d, v)
    if it.get("o"):
        cur.setdefault("o", {})
        for d, v in it["o"].items():
            cur["o"].setdefault(d, v)
    if it.get("combo") and not cur.get("combo"):
        cur["combo"] = 1
        cur["def"] = it.get("def")
    # 角色取更具体的那个（非「其他」优先）
    if cur["role"] == "其他" and it["role"] != "其他":
        cur["role"] = it["role"]
menu = list(_merged.values())
for it in menu:
    it["dp"] = [d for d in DAYPARTS if d in it["dp"]]
    if it.get("o"):
        it["o"] = {d: it["o"][d] for d in it["dp"] if d in it["o"]}
        if not it["o"]:
            it.pop("o")

# 排序：按餐段分类顺序 + 分类内原序
def sort_key(it):
    dps = it["dp"]
    primary = "午餐" if "午餐" in dps else dps[0]
    try:
        ci = min(CAT_ORDER[primary].index(c) for c in it["c"] if c in CAT_ORDER[primary])
    except ValueError:
        ci = 99
    return (DAYPARTS.index(primary), ci, it["n"])
menu.sort(key=sort_key)

# ────────────────────────────── 8. 输出 JS ──────────────────────────────
def js_num(v):
    v = float(v)
    return str(int(v)) if v.is_integer() else str(round(v, 2))

def js_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'

def emit_nutri():
    """★ 以**页面实际查表用的名字**为键，而不是营养表里的官方名。

    页面的 baseKcal(n) 是直接 NUTRI[n] 查的，n 是商品/选项的显示名。
    别名（如「5块麦乐鸡」→「麦乐鸡5块」）如果只在构建期做归一会漏掉——
    必须把别名也各写一份，否则这类选项全部显示「热量未知」。
    """
    lines = ["const NUTRI = {"]
    body = []
    for k, v in nutri_out.items():
        body.append('  %s:{kcal:%d,p:%s,f:%s,c:%s,na:%d}' % (
            js_str(k), v["kcal"], js_num(v["p"]), js_num(v["f"]), js_num(v["c"]), v["na"]))
    lines.append(",\n".join(body))
    lines.append("};")
    return "\n".join(lines)

def emit_zero():
    return ("/* 零热量 / 非食品项：按 0 千卡计（玩具、单卖蘸酱），不计入「热量未知」 */\n"
            "const ZERO = new Set([%s]);" % ",".join(js_str(n) for n in ZERO_NAMES))

def emit_menu():
    sc_cat = scene_cats()
    out = ["const MENU = ["]
    rows = []
    for it in menu:
        f = ["n:" + js_str(it["n"]), "role:" + js_str(it["role"]),
             "c:[" + ",".join(js_str(c) for c in it["c"]) + "],"
             "dp:[" + ",".join(js_str(d) for d in it["dp"]) + "]",
             "p:{" + ",".join('%s:%s' % (js_str(d), js_num(v)) for d, v in it["p"].items()) + "}"]
        # sc = 引擎候选池品类（主食/小食/饮品）。缺省 = 引擎不发候选（规格歧义/非食品/组合品/无营养）
        if it["n"] in sc_cat:
            f.append("sc:" + js_str(sc_cat[it["n"]]))
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

def emit_cats():
    out = ["const CATS = {"]
    blocks = []
    for d in DAYPARTS:
        blocks.append("  %s:[%s]" % (js_str(d), ",".join(js_str(c) for c in CAT_ORDER[d])))
    out.append(",\n".join(blocks))
    out.append("};")
    return "\n".join(out)

LISTS = OrderedDict()      # 选项列表指纹 → 索引（269 个轮次里只有 94 个不同的列表，65% 可复用）
LIST_IDX = {}

def list_ref(choices):
    key = json.dumps(choices, ensure_ascii=False)
    if key not in LIST_IDX:
        i = len(LISTS)
        LISTS[i] = choices
        LIST_IDX[key] = i
    return LIST_IDX[key]

def populate_lists():
    """把 ROUNDS 里所有选项列表灌进池子（幂等）。"""
    for rounds in ROUNDS.values():
        for r in rounds:
            list_ref(r["choices"])

def emit_lists():
    populate_lists()
    out = ["/* 选项列表池：套餐轮次里高度重复（269 轮 → 94 个不同列表），抽出来共用 */",
           "const LISTS = {"]
    rows = []
    for i, ch in LISTS.items():
        rows.append("  %d:[%s]" % (i, ",".join("[%s,%s,%s]" % (
            js_str(c[0]), js_num(c[1]), "true" if c[2] else "false") for c in ch)))
    out.append(",\n".join(rows))
    out.append("};")
    return "\n".join(out)

def emit_rounds():
    # 先建索引，保证 emit_lists 能拿到全部列表
    plan = []
    for name, rounds in ROUNDS.items():
        rs = []
        for r in rounds:
            rs.append((r, list_ref(r["choices"])))
        plan.append((name, rs))
    out = ["const ROUNDS = {"]
    blocks = []
    for name, rs in plan:
        body = []
        for r, li in rs:
            body.append("    {name:%s,cat:%s,min:%d,max:%d,l:%d}" % (
                js_str(r["name"]), js_str(r["category"]), r["min"], r["max"], li))
        blocks.append("  %s:[\n%s\n  ]" % (js_str(name), ",\n".join(body)))
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

TIERS_JS = (
    "const TIERS = {\n"
    '  "早餐":{轻量:300,标准:450,吃饱:600},\n'
    '  "午餐":{轻量:500,标准:750,吃饱:1000},\n'
    '  "随便吃吃":{轻量:150,标准:300,吃饱:450},\n'
    '  "晚餐":{轻量:500,标准:750,吃饱:1000},\n'
    '  "宵夜":{轻量:300,标准:450,吃饱:600}\n'
    "};"
)

# ────────────────────────── 9·A 场景候选池品类（引擎判定，非 UI 角色） ──────────────────────────
# 页面菜单里的 role 是 **UI 角色**（按官方菜单分类推出来的展示分组）；
# 而 mcd_combo.build_pools 的候选池用的是 data/category-rules.json 的映射，
# 并且对「规格未写明」的歧义商品（薯条 / 可乐 / 雪碧 / 派 …）一律不发候选
# ——SKILL 明确「无证据的歧义保持歧义让用户选择，禁止猜测」。
# 两者实测不同（午餐：引擎 主/小/饮 = 11/6/6，页面 role = 8/8/7）。
# 页面要做场景推荐就必须用**引擎自己的池**，否则同一场景两边给出不同结果。
# 故直接复用引擎结果，不再另写一套归类。
_SCENE_CATS = None

def scene_cats():
    """{商品名: "主食"|"小食"|"饮品"}；不在任何池里的商品不出现（= 引擎不发候选）。"""
    global _SCENE_CATS
    if _SCENE_CATS is not None:
        return _SCENE_CATS
    sys.path.insert(0, os.path.join(BASE, "scripts"))
    from mcd_nutrition import Matcher, load_nutrition
    import mcd_combo as C
    m = Matcher(load_nutrition())
    out = {}
    for dp in DAYPARTS:
        fx = DP_FILES.get(DP_ALIAS.get(dp, dp))
        built = C.build_pools(Path(FX) / fx, m)
        for cat, pool in built["pools"].items():
            for x in pool:
                if out.setdefault(x["name"], cat) != cat:
                    raise SystemExit("跨餐段品类冲突：%s %s vs %s" % (x["name"], out[x["name"]], cat))
    _SCENE_CATS = out
    return out

def emit_dessert_kw():
    """甜品关键词：!allow_dessert 的场景要从「小食」池里剔掉这些（引擎 filter_pools 同规则）。"""
    rules = json.load(open(os.path.join(BASE, "data", "category-rules.json"), encoding="utf-8"))
    kw = rules.get("dessertKeywords", [])
    return ("/* 甜品关键词（category-rules.json）—— 不允许甜品的场景按此从「小食」池剔除 */\n"
            "const DESSERT_KW = [%s];" % ",".join(js_str(x) for x in kw))

# ────────────────────────── 9. 目标场景预设（13 个，与 mcd_goal.py 同源） ──────────────────────────
# 场景定义唯一来源是 scripts/mcd_goal.py；这里只做「搬运 + 压成页面紧凑格式」，
# 不在构建脚本里另写一份场景逻辑，否则两边会漂移。
GOAL_GROUPS = [
    ("热量与体型", ["cut", "bulk", "post", "cheat"]),
    ("单一营养素管控", ["low-sodium", "high-protein", "low-carb", "low-fat"]),
    ("结构 / 人群 / 场景", ["vegetarian", "kids", "daily-budget", "allergen", "value"]),
]
# 策略要点短句：与 SKILL.md 工作流 G 表格「策略要点」列一致（展示用文案）
GOAL_SHORT = {
    "cut":           "蛋白密度优先 · 剔甜品 · 小食≤1",
    "bulk":          "热量盈余 · 蛋白碳水双高 · 小食≤2",
    "post":          "蛋白总量优先 · 必含主食回补碳水",
    "cheat":         "热量上浮 · 允许甜品 · 性价比排序",
    "low-sodium":    "钠硬上限（默认≤1000mg）· 钠升序",
    "high-protein":  "蛋白密度优先 · 兼顾蛋白总量",
    "low-carb":      "碳水硬上限（默认≤60g）· 碳水升序",
    "low-fat":       "脂肪硬上限（默认≤30g）· 脂肪升序",
    "vegetarian":    "关键词排除肉类/水产（蛋奶可食）",
    "kids":          "热量下浮 ×0.85 · 单组≤2 件",
    "daily-budget":  "按当日剩余预算 · 用满不超",
    "allergen":      "按过敏原展开关键词排除（粗筛）",
    "value":         "价格硬上限 · 价格升序",
}

def emit_goals():
    """把 mcd_goal.GOALS 压成页面用的紧凑结构。

    可选入参（页面上让用户填）：
      sodium_max / carb_max / fat_max / price_max / budget / max_items / allergens
    """
    sys.path.insert(0, os.path.join(BASE, "scripts"))
    import mcd_goal as G

    order, group_of = [], {}
    for gname, keys in GOAL_GROUPS:
        for k in keys:
            order.append(k)
            group_of[k] = gname
    # 与 mcd_goal.GOALS 对账：数量与键必须完全一致，防止只改了单边
    assert len(order) == len(G.GOALS) == 13, (len(order), len(G.GOALS))
    assert set(order) == set(G.GOALS), set(order) ^ set(G.GOALS)

    blocks = []
    for k in order:
        d = G.GOALS[k]
        f = ["label:%s" % js_str(d["label"]), "group:%s" % js_str(group_of[k]),
             "tier:%s" % js_str(d["prefer_tier"]), "sort:%s" % js_str(d["sort"]),
             "short:%s" % js_str(GOAL_SHORT[k]), "desc:%s" % js_str(G.GOAL_DESCRIPTIONS.get(k, ""))]
        if "tolerance" in d:
            f.append("tol:%s" % js_num(d["tolerance"]))
        if "range_from" in d:
            f.append("rf:%s" % js_num(d["range_from"]))
        if "range_to" in d:
            f.append("rt:%s" % js_num(d["range_to"]))
        if d.get("target_scale"):
            f.append("scale:%s" % js_num(d["target_scale"]))
        f.append("snack:%d" % d.get("max_snacks", 2))
        f.append("dessert:%s" % ("true" if d.get("allow_dessert") else "false"))
        if d.get("max_items"):
            f.append("items:%d" % d["max_items"])
        if d.get("require_staple"):
            f.append("staple:true")
        if d.get("allow_snack_combo"):
            f.append("snackcombo:true")
        if d.get("min_protein_g"):
            f.append("minp:%d" % d["min_protein_g"])
        lim = {kk: vv for kk, vv in (d.get("limits") or {}).items() if vv}
        if lim:
            f.append("lim:{%s}" % ",".join("%s:%s" % (js_str(kk), js_num(vv)) for kk, vv in lim.items()))
        if d.get("exclude_keywords"):
            f.append("ex:[%s]" % ",".join(js_str(x) for x in d["exclude_keywords"]))
        if d.get("param_exclude"):
            f.append("param:%s" % js_str(d["param_exclude"]))
        if d.get("target_from_param"):
            f.append("budgetParam:%s" % js_str(d["target_from_param"]))
        blocks.append("  %s:{%s}" % (js_str(k), ",".join(f)))

    out = ["/* 13 个目标场景预设 —— 与 scripts/mcd_goal.py 的 GOALS 同源搬运，勿在此另写一套 */",
           "const GOALS = {", ",\n".join(blocks), "};",
           "const GOAL_ORDER = [%s];" % ",".join(js_str(k) for k in order),
           "const GOAL_GROUPS = [%s];" % ",".join(
               "[%s,[%s]]" % (js_str(n), ",".join(js_str(k) for k in ks)) for n, ks in GOAL_GROUPS)]
    al = {k: v for k, v in sorted(G.ALLERGEN_KEYWORDS.items())}
    out.append("/* 过敏原 → 关键词展开（粗筛；菜单无配料/过敏原表，必须带告警） */")
    out.append("const ALLERGENS = {")
    out.append(",\n".join("  %s:[%s]" % (js_str(k), ",".join(js_str(x) for x in v)) for k, v in al.items()))
    out.append("};")
    out.append(emit_dessert_kw())
    return "\n".join(out)

# ────────────────────────── 10. 历史订单（脱敏样本 + 逐项热量） ──────────────────────────
def emit_history():
    """把 data/history-orders.json 逐单展开 → 匹配营养表 → 逐项写死热量。

    页面只做「求和 / 求平均 / 判档」这类聚合，**逐项热量不重算**——
    复用 mcd_nutrition.Matcher（与 mcd_import.py 同一套归一/别名/默认规格），
    这样页面与 skill 的结论逐项一致，不会因为 JS 侧另写一套匹配而漂移。
    匹配不上 → kcal:null（页面标「热量未知」，绝不按 0 计）。
    """
    sys.path.insert(0, os.path.join(BASE, "scripts"))
    from mcd_nutrition import Matcher, load_nutrition
    from mcd_order import expand_order
    import mcd_daypart as dp

    raw = json.load(open(os.path.join(BASE, "data", "history-orders.json"), encoding="utf-8"))
    matcher = Matcher(load_nutrition())
    orders = []
    for o in raw.get("list", []):
        items, addons = expand_order(o)
        ct = o.get("createTime") or ""
        hhmm = ct.split()[1][:5] if len(ct.split()) > 1 else "12:00"
        daypart = dp.resolve_daypart(hhmm, None)
        rows = []
        for nm in items:
            res = matcher.match(nm, allow_defaults=True)
            if res["status"] == "hit":
                r = res["record"]
                rows.append({"n": nm, "st": "hit", "k": int(r["kcal"]),
                             "p": round(float(r["protein"]), 1), "na": int(r["sodium_mg"]),
                             "m": r["name"]})
            elif res["status"] == "ambiguous":
                rows.append({"n": nm, "st": "ambiguous", "c": res["candidates"][:4]})
            else:
                rows.append({"n": nm, "st": "unknown"})
        orders.append({
            "time": ct, "store": o.get("store") or "", "daypart": daypart,
            "amount": float(o.get("realTotalAmount") or 0),
            "status": o.get("orderStatus") or "",
            "items": rows, "addons": addons,
        })

    # 汇总口径与 mcd_import.summarize 对齐（供页面自检；页面也会自己再算一遍）
    tot = [sum(r["k"] for r in o["items"] if r.get("st") == "hit") for o in orders]
    std = [dp.tier_target(o["daypart"], "标准") for o in orders]
    over = sum(1 for t, s in zip(tot, std) if t - s > s * 0.12)
    unk = sum(1 for o in orders for r in o["items"] if r.get("st") == "unknown")
    nitems = sum(len(o["items"]) for o in orders)

    out = ["/* 历史订单（官方 order-list 导出后自动脱敏：无 orderId/storeCode/storeName/beCode，门店代称化）",
           "   逐项热量由 scripts/mcd_import.py 同一套 Matcher 预解析；匹配不上者 kcal 省略 → 页面标「热量未知」 */",
           "const HISTORY = {",
           "  meta:{source:%s,deidentifiedAt:%s,orderCount:%d,itemCount:%d,unknownCount:%d,overStandard:%d}," % (
               js_str(raw.get("_meta", {}).get("source", "")),
               js_str(raw.get("_meta", {}).get("deidentifiedAt", "")),
               len(orders), nitems, unk, over),
           "  orders:["]
    rows = []
    for o in orders:
        its = []
        for r in o["items"]:
            f = ["n:%s" % js_str(r["n"]), "st:%s" % js_str(r["st"])]
            if r.get("st") == "hit":
                f += ["k:%d" % r["k"], "p:%s" % js_num(r["p"]), "na:%d" % r["na"], "m:%s" % js_str(r["m"])]
            if r.get("st") == "ambiguous":
                f.append("c:[%s]" % ",".join(js_str(x) for x in r["c"]))
            its.append("{%s}" % ",".join(f))
        rows.append('    {time:%s,store:%s,daypart:%s,amount:%s,status:%s,items:[%s]}' % (
            js_str(o["time"]), js_str(o["store"]), js_str(o["daypart"]),
            js_num(o["amount"]), js_str(o["status"]), ",".join(its)))
    out.append(",\n".join(rows))
    out.append("  ]")
    out.append("};")
    return "\n".join(out)

# ────────────────────────── 11. 注入页面 ──────────────────────────
PAGE = os.path.join(os.path.dirname(BASE), "food.html")

def _block_span(src, name, endname=None):
    """定位 `const NAME = … ;` 的字符区间（含分号）。

    兼容三种右侧写法：对象字面量 `{…}`、数组字面量 `[…]`、`new Set([…])`。
    取「= 之后第一个 { 或 [」作为值的起点——本文件所有数据块都满足该性质。

    endname：一个发射器可能产出**多条连续声明**（如 GOALS 同时带
    GOAL_ORDER / GOAL_GROUPS / ALLERGENS）。此时把整个区域视为一个整体替换，
    区间终点取 endname 那条声明的末尾，避免只替换第一条而把其余条越叠越多。
    """
    m = re.search(r"^const %s\s*=\s*" % re.escape(name), src, re.M)
    if not m:
        return None
    cands = [i for i in (src.find("{", m.end()), src.find("[", m.end())) if i >= 0]
    if not cands:
        return None
    i = min(cands)
    op = src[i]
    cl = "}" if op == "{" else "]"
    depth, j = 0, i
    while j < len(src):
        if src[j] == op:
            depth += 1
        elif src[j] == cl:
            depth -= 1
            if depth == 0:
                break
        j += 1
    if j >= len(src):
        return None
    end = src.index(";", j) + 1
    if endname and endname != name:
        tail = _block_span(src[end:], endname)
        if not tail:
            return None
        end += tail[1]
    return (m.start(), end)

def _strip_lead_comment(text, name):
    """只保留 `const NAME = …` 那行及其之后的内容。

    发射器返回的文本带前置 `/* … */` 说明注释（print 模式有用），
    但页面里的注释是**静态作者内容**，若把注释一起参与替换，
    每注入一次就会多叠一层注释。故注入前裁掉。
    """
    m = re.search(r"^const %s\s*=" % re.escape(name), text, re.M)
    return text[m.start():] if m else text

def inject(names):
    """把生成的数据块写回「food.html」。

    改数据请改脚本后重跑，不要手改页面里的数组——手改下一次注入就被覆盖。
    幂等：同样的数据源，反复 inject 结果逐字节一致。
    """
    src = open(PAGE, encoding="utf-8").read()
    emitters = {"CATS": emit_cats, "ZERO": emit_zero, "NUTRI": emit_nutri, "TIERS": lambda: TIERS_JS,
                "LISTS": emit_lists, "MENU": emit_menu, "ROUNDS": emit_rounds, "MODS": emit_mods,
                "GOALS": emit_goals, "HISTORY": emit_history}
    # 一个发射器产出多条连续声明时，声明「区域终点」
    REGION_END = {"GOALS": "DESSERT_KW"}
    report = []
    for nm in names:
        span = _block_span(src, nm, REGION_END.get(nm))
        if not span:
            report.append("  ✗ %-8s 未在页面中找到" % nm)
            continue
        new = _strip_lead_comment(emitters[nm](), nm)
        old_len = span[1] - span[0]
        src = src[:span[0]] + new + src[span[1]:]
        report.append("  ✓ %-8s %6d → %6d 字符" % (nm, old_len, len(new)))
    open(PAGE, "w", encoding="utf-8").write(src)
    print("注入 %s：" % PAGE)
    print("\n".join(report))
    print("  页面总长 %d 字符" % len(src))

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if mode == "stats":
        from collections import Counter
        combos = [i for i in menu if i["role"] == "套餐"]
        print("快照商品总数（去重）:", len(registry))
        print("进入页面的商品数:", len(menu))
        print("角色分布:", dict(Counter(i["role"] for i in menu)))
        print("营养表条目（写入页面）:", len(nutri_used), "| 未命中:", len(unknown))
        print("套餐总数:", len(combos), "| 有组成(ROUNDS):", len(ROUNDS))
        print("零热量/非食品项:", len(ZERO_NAMES), list(ZERO_NAMES)[:8])
        print("有 MODS 的商品数:", sum(1 for i in menu if build_mods(i["n"], i["role"])))
        rc = Counter(r["category"] for rs in ROUNDS.values() for r in rs)
        print("轮次品类分布:", dict(rc))
        fixed = sum(1 for rs in ROUNDS.values() for r in rs if len(r["choices"]) == 1)
        total_r = sum(len(rs) for rs in ROUNDS.values())
        print("轮次总数: %d（其中单选固定项 %d）" % (total_r, fixed))
        allc = {c[0] for rs in ROUNDS.values() for r in rs for c in r["choices"]}
        hitc = {n for n in allc if resolve_nutri(n) or is_zero(n)}
        print("套餐选项名（去重）: %d，可算热量/非食品: %d (%.1f%%)" % (
            len(allc), len(hitc), 100 * len(hitc) / max(1, len(allc))))
        print()
        print("各餐段商品数:", {d: sum(1 for i in menu if d in i["dp"]) for d in DAYPARTS})
        print("各餐段分类数:", {d: len(CAT_ORDER[d]) for d in DAYPARTS})
        print("\n未命中营养表（前 30）:")
        for u in unknown[:30]:
            print("  -", u)
    elif mode == "inject":
        # inject [块名...]；不给块名 = 全部重写
        allnames = ["CATS", "ZERO", "NUTRI", "TIERS", "LISTS", "MENU", "ROUNDS", "MODS",
                    "GOALS", "HISTORY"]
        inject(sys.argv[2:] or allnames)
    else:
        key = {"nutri": emit_nutri, "menu": emit_menu, "rounds": emit_rounds, "lists": emit_lists,
               "mods": emit_mods, "cats": emit_cats, "zero": emit_zero,
               "goals": emit_goals, "history": emit_history,
               "dessert": emit_dessert_kw, "sc": lambda: json.dumps(scene_cats(), ensure_ascii=False, indent=1),
               "tiers": lambda: TIERS_JS}[mode]
        print(key())
