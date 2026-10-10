#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd_taxonomy.py — 品类归类与排除规则（基座层，零依赖其他 mcd_* 模块）

从 mcd_combo.py 抽出的品类判定单一实现（v0.9 架构调整）：
- 第一级：菜单分类名 → 品类（menuCategoryMap）
- 第三级兜底：名称关键词 → 品类（甜品/冰淇淋 → 饮品 → 主食 → 小食）
- 排除判定：组合品词（无条件排除）+ 非食品词（不与食物词共存才排除）
- 套餐线索词（comboHints，mcd_catalog 用）

之前 mcd_order 反向 import mcd_combo 的私有 _keyword_category（层级倒置），
现在 order / combo / catalog 统一从本模块导入，规则只有这一份。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

SKILL_ROOT = Path(__file__).resolve().parent.parent

RULES = json.loads((SKILL_ROOT / "data" / "category-rules.json").read_text(encoding="utf-8"))

# 菜单分类名 → 品类（第一级，权威来源之一）
_MENU_CAT = []
for cat, names in RULES["menuCategoryMap"].items():
    _MENU_CAT.extend((n, cat) for n in names)

_NONFOOD_PATTERNS = tuple(RULES.get("excludeNonFoodPatterns") or ())
_FOOD_HINTS = tuple(RULES.get("foodHintKeywords") or ())

COMBO_HINTS = tuple(RULES["comboHints"])


def category_from_menu_name(menu_category: str) -> Optional[str]:
    """第一级：菜单分类名 → 品类。"""
    low = menu_category.replace("\n", "")
    for frag, cat in _MENU_CAT:
        if frag in low:
            return cat
    return None


def excluded(name: str) -> Optional[str]:
    """返回命中的排除词；无则 None。

    两类排除词区别对待（v0.8）：
    - **组合品词**（套餐/件套/随心选…）：无条件排除——组合品不得进单品候选位（PRD D4）。
    - **非食品词**（蘸酱/风味酱/山葵酱…）：仅当**不与食物词共存**时才排除。
      「蘸酱炸鸡」「蘸酱麦麦脆汁鸡」「5块心形薯饼+韩式辣椒黄油风味酱」是含酱的**食物**，
      名字里有「鸡/薯/块」→ 不排除；否则会把一顿正餐挡在候选外（与
      build_demo_menu.is_zero 的判据一致）。
    """
    for p in RULES["excludeNamePatterns"]:
        if p in name:
            return p
    for p in _NONFOOD_PATTERNS:
        if p in name and not any(k in name for k in _FOOD_HINTS):
            return p
    return None


def keyword_category(name: str) -> Optional[str]:
    """第三级兜底。顺序：甜品/冰淇淋 → 饮品 → 主食 → 小食。"""
    for kw in RULES["dessertKeywords"]:
        if kw in name:
            return "小食"
    for kw in RULES["drinkKeywords"]:
        if kw in name:
            return "饮品"
    for kw in RULES["stapleKeywords"]:
        if kw in name:
            return "主食"
    for kw in RULES["snackKeywords"]:
        if kw in name:
            return "小食"
    return None


# 旧私有名兼容别名（外部曾有 from mcd_combo import _keyword_category 的用法）
_keyword_category = keyword_category
_excluded = excluded
_category_from_menu_name = category_from_menu_name
