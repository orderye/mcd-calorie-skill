#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd_nutrition.py — 营养表解析、名称归一化、四级匹配器（T6/T7/T8）

无第三方依赖。数据来自 list-nutrition-foods 的紧凑字符串快照。
核心纪律：匹配不上的商品一律 UNKNOWN，绝不按 0 计算（PRD F1 / §9）。
"""
from __future__ import annotations

import json
import re
import unicodedata
from bisect import bisect_left, bisect_right
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

SKILL_ROOT = Path(__file__).resolve().parent.parent
NUTRITION_RAW = SKILL_ROOT / "fixtures" / "nutrition.raw.txt"
ALIAS_FILE = SKILL_ROOT / "data" / "alias.json"

# 数值列顺序（与表头一致）
NUM_FIELDS = ("kj", "kcal", "protein", "fat", "carb", "sodium_mg", "calcium_mg")
FUZZY_THRESHOLD = 0.85  # 兜底阈值，不得为提升命中率上调（见实施计划 R3）
FUZZY_LEN_FLOOR = 0.80  # 长度窗口剪枝阈值 t：ratio 上界 2*min/(l1+l2) < t 的候选
                        # 既不可能成为 best（需 ≥0.85），也不可能触发
                        # best−second≥0.05 的失败分支（失败需 second > best−0.05 ≥ 0.80）。
                        # 剪枝可证不改变匹配结果（见 __init__ 长度索引）


# ────────────────────────── T6 营养表解析 ──────────────────────────

def parse_nutrition(raw: str) -> tuple[list[dict], dict]:
    """解析紧凑格式字符串 → 结构化记录列表。

    返回 (records, stats)。非法数值 → None（绝不填 0）；同名重复 → 保留首条。
    """
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    header_re = re.compile(r"^\[(\d+)\]\{(.+)\}:$")
    records: list[dict] = []
    seen: set[str] = set()
    duplicates = 0
    bad_rows = 0

    for ln in lines:
        m = header_re.match(ln)
        if m:  # 表头行
            continue
        parts = ln.split(",")
        if len(parts) != 9:
            bad_rows += 1
            continue
        name = parts[0].strip()
        desc = None if parts[1] == "null" else parts[1].strip()
        vals = []
        for v in parts[2:]:
            try:
                vals.append(float(v))
            except ValueError:
                vals.append(None)
        if name in seen:
            duplicates += 1
            continue
        seen.add(name)
        rec = {"name": name, "description": desc}
        rec.update(dict(zip(NUM_FIELDS, vals)))
        records.append(rec)

    stats = {
        "declared_count": None, "parsed": len(records),
        "duplicates_removed": duplicates, "bad_rows": bad_rows,
    }
    hm = header_re.match(lines[0]) if lines else None
    if hm:
        stats["declared_count"] = int(hm.group(1))
    return records, stats


def load_nutrition() -> list[dict]:
    records, _stats = parse_nutrition(NUTRITION_RAW.read_text(encoding="utf-8"))
    return records


# ────────────────────────── T7 名称归一化 ──────────────────────────

_BRAND_PREFIXES = ("麦咖啡™", "麦咖啡", "McCafé", "McCafe")
_PAREN_RE = re.compile(r"[（(][^（）()]*[）)]")           # （盒装）/（椒盐风味）/(加)
_ADDON_RE = re.compile(r"加[^加]{1,8}(?:（加）|\(加\))$")  # "巨无霸加吉士(加)" → 巨无霸
_POOL_RE = re.compile(r"-pool\d+$", re.IGNORECASE)        # "-poolN" 后缀


def _to_halfwidth(s: str) -> str:
    out = []
    for ch in s:
        code = ord(ch)
        if code == 0x3000:  # 全角空格
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def normalize_name(name: str) -> str:
    """归一化为匹配键：全半角、品牌前缀、pool 后缀、加料段、括号段、空白。"""
    s = unicodedata.normalize("NFC", str(name))
    s = _to_halfwidth(s)
    for p in _BRAND_PREFIXES:
        if s.startswith(p):
            s = s[len(p):]
            break
    s = _POOL_RE.sub("", s)
    s = _ADDON_RE.sub("", s)
    s = _PAREN_RE.sub("", s)
    s = re.sub(r"\s+", "", s)
    # 冰/热前缀仅作次级键，保留在主键里（冰奶铁 ≠ 热奶铁，营养表分列）
    return s.strip().lower()


# ────────────────────────── T8 四级匹配器 ──────────────────────────

def _load_alias() -> tuple[dict[str, str], dict[str, str]]:
    if ALIAS_FILE.exists():
        data = json.loads(ALIAS_FILE.read_text(encoding="utf-8"))
        mappings = {normalize_name(k): v for k, v in data.get("mappings", {}).items()}
        defaults = {normalize_name(k): v for k, v in data.get("defaults", {}).items()}
        return mappings, defaults
    return {}, {}


_QTY_SUFFIX = re.compile(r"(?:-\s*)?\d+\s*块$")   # 订单侧数量后缀（麦麦脆汁鸡1块）


def normalize_query(name: str) -> str:
    """查询侧归一化：在 normalize_name 之上剥离数量后缀。

    仅用于查询键；营养表索引保持原样（"麦辣鸡翅-2块" 本身是营养表条目名）。
    """
    key = normalize_name(name)
    key = _QTY_SUFFIX.sub("", key).strip("- ").strip()
    return key or normalize_name(name)


class Matcher:
    """四级匹配：精确 → 归一化精确 → 别名 → 去规格前后缀 → 模糊。

    match() 返回:
      {"status": "hit"|"ambiguous"|"unknown",
       "method": "exact|alias|prefix|suffix|fuzzy",
       "record": dict|None, "candidates": [names]}
    """

    def __init__(self, records: Optional[list[dict]] = None):
        self.records = records if records is not None else load_nutrition()
        self.by_key: dict[str, dict] = {}
        for r in self.records:
            self.by_key.setdefault(normalize_name(r["name"]), r)
        self.alias, self.defaults = _load_alias()
        # 模糊匹配长度索引：按 key 长度排序，查询时仅遍历长度窗口内候选
        self._by_len = sorted(self.by_key.items(), key=lambda kv: len(kv[0]))
        self._lens = [len(k) for k, _r in self._by_len]

    def match(self, name: str, allow_defaults: bool = False) -> dict:
        """allow_defaults=True 时（订单/套餐上下文），歧义候选中若存在
        有实测证据的默认规格（alias.json#defaults），按默认命中并标注来源。
        无证据的歧义仍然返回 ambiguous，禁止猜测（PRD §7）。"""
        key = normalize_query(name)
        if not key:
            return {"status": "unknown", "method": "empty", "record": None, "candidates": []}

        # 1) 归一化精确
        if key in self.by_key:
            return {"status": "hit", "method": "exact", "record": self.by_key[key], "candidates": []}

        # 1.5) 原始键精确（不剥数量后缀）
        #     normalize_query 会剥掉「N块」等后缀，导致「麦乐鸡5块」被降级成
        #     前缀歧义（麦乐鸡4块/5块 二选一）。营养表本身收录的就是带数量的条目名，
        #     查询侧带数量时应优先按原名精确命中，禁止退化成猜测。
        raw_key = normalize_name(name)
        if raw_key != key and raw_key in self.by_key:
            return {"status": "hit", "method": "exact-qty", "record": self.by_key[raw_key],
                    "candidates": []}

        # 2) 别名表
        if key in self.alias:
            target = self.alias[key]
            if target in self.by_key:
                return {"status": "hit", "method": "alias", "record": self.by_key[target], "candidates": []}

        # 3) 规格（杯型/份数/部位）缺失：营养表名以订单名开头或结尾
        prefixed = [r for k, r in self.by_key.items() if k.startswith(key) and k != key]
        suffixed = [r for k, r in self.by_key.items() if k.endswith(key) and k != key]
        if len(prefixed) == 1 and not suffixed:
            return {"status": "hit", "method": "prefix", "record": prefixed[0], "candidates": []}
        if len(suffixed) == 1 and not prefixed:
            return {"status": "hit", "method": "suffix", "record": suffixed[0], "candidates": []}
        cands = prefixed + suffixed
        if cands:
            cand_names = sorted({r["name"] for r in cands})
            if allow_defaults and key in self.defaults:
                dft = self.defaults[key]
                # defaults 值是菜单原名（如「中杯怡泉+C」），by_key 键是归一化名，
                # 必须经 normalize_name 归一后再查，否则大小写不一致恒 miss。
                dft_key = normalize_name(dft)
                if dft in cand_names and dft_key in self.by_key:
                    return {"status": "hit", "method": "default-evidence",
                            "record": self.by_key[dft_key], "candidates": cand_names}
            return {"status": "ambiguous", "method": "spec-missing",
                    "record": None, "candidates": cand_names}

        # 4) 模糊兜底（长度窗口剪枝：窗口外候选 ratio 上界 < 0.80，不影响判定）
        t = FUZZY_LEN_FLOOR
        klen = len(key)
        i0 = bisect_left(self._lens, klen * t / (2 - t))
        i1 = bisect_right(self._lens, klen * (2 - t) / t)
        best, best_ratio = None, 0.0
        second = 0.0
        for k, r in self._by_len[i0:i1]:
            ratio = SequenceMatcher(None, key, k).ratio()
            if ratio > best_ratio:
                second, best, best_ratio = best_ratio, r, ratio
            elif ratio > second:
                second = ratio
        if best_ratio >= FUZZY_THRESHOLD and best_ratio - second >= 0.05:
            return {"status": "hit", "method": "fuzzy", "record": best,
                    "candidates": [best["name"]]}
        return {"status": "unknown", "method": "none", "record": None, "candidates": []}


def match_or_none(matcher: Matcher, name: str) -> Optional[dict]:
    """便捷封装：命中返回营养记录，否则 None（调用方按 UNKNOWN 处理）。"""
    res = matcher.match(name)
    return res["record"] if res["status"] == "hit" else None


if __name__ == "__main__":
    import sys
    records, stats = parse_nutrition(NUTRITION_RAW.read_text(encoding="utf-8"))
    print(f"解析条目: {stats['parsed']} (声明 {stats['declared_count']}, "
          f"去重 {stats['duplicates_removed']}, 坏行 {stats['bad_rows']})")
    m = Matcher(records)
    for q in sys.argv[1:] or ["猪柳麦满分", "麦咖啡™热奶铁中杯", "可乐", "薯条", "麦辣鸡翅",
                              "100% 苹果汁(盒装)", "那么大鸡排（椒盐风味）", "吉士蛋麦满分", "新地"]:
        r = m.match(q)
        if r["status"] == "hit":
            print(f"  {q:<22} → HIT   [{r['method']}] {r['record']['name']} "
                  f"{r['record']['kcal']:.0f} kcal")
        elif r["status"] == "ambiguous":
            print(f"  {q:<22} → AMBIG [{', '.join(r['candidates'][:5])}]")
        else:
            print(f"  {q:<22} → UNKNOWN")
