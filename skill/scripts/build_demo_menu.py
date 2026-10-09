#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_demo_menu.py —— 用真实采集快照生成「点餐页.html」的产品数据块。

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
    out = ["const MENU = ["]
    rows = []
    for it in menu:
        f = ["n:" + js_str(it["n"]), "role:" + js_str(it["role"]),
             "c:[" + ",".join(js_str(c) for c in it["c"]) + "],"
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
    else:
        key = {"nutri": emit_nutri, "menu": emit_menu, "rounds": emit_rounds, "lists": emit_lists,
               "mods": emit_mods, "cats": emit_cats, "zero": emit_zero,
               "tiers": lambda: TIERS_JS}[mode]
        print(key())
