#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd_daypart.py — 餐段识别与时段解析（T15/T16/T17）

优先级：用户显式指定 > 门店 reservationTimeOptions 实测时段 > PRD 固定值兜底。
实测确认（D1）：query-meals 无 daypart 字段，取指定餐段菜单用 reservationDate 传目标时刻。
"""
from __future__ import annotations

import re
from typing import Optional

SEG_RE = re.compile(r"(早餐|午餐|下午茶|夜市|宵夜)\(([^)]+)\)")
RANGE_RE = re.compile(r"(\d{2}:\d{2})至(\d{2}:\d{2})")

# 接口餐段名 → Skill 餐段
# 2026-10-10 决策：宵夜单列档位（不再并入晚餐）。
# 实测各店宵夜约 22:14 起（跨零点如 00:00至04:45 亦存在）。
SEGMENT_ALIAS = {"早餐": "早餐", "午餐": "午餐", "下午茶": "随便吃吃",
                 "夜市": "晚餐", "宵夜": "宵夜"}

# PRD §6 热量档位（kcal，默认值，用户可调整）。
# 宵夜为单列档：介于"随便吃吃"与"晚餐"之间（参考值）。
TIERS = {
    "早餐":   {"轻量": 300, "标准": 450, "吃饱": 600},
    "午餐":   {"轻量": 500, "标准": 750, "吃饱": 1000},
    "晚餐":   {"轻量": 500, "标准": 750, "吃饱": 1000},
    "宵夜":   {"轻量": 300, "标准": 450, "吃饱": 600},
    "随便吃吃": {"轻量": 150, "标准": 300, "吃饱": 450},
}

# PRD F2 固定时段（仅兜底；实测各店差异大，见 docs/store-chain.md）
# 宵夜跨零点：实测门店存在 00:00至04:45 段（2026-10-10），兜底须覆盖凌晨，
# 否则 00:00–05:59 会全部误判为晚餐。
FIXED_RANGES = {
    "早餐": [("06:00", "10:29")],
    "午餐": [("10:30", "15:29")],
    "随便吃吃": [("15:30", "17:59")],
    "晚餐": [("18:00", "21:59")],
    "宵夜": [("22:00", "23:59"), ("00:00", "05:59")],
}

# 无门店时段表时，取某餐段菜单用的代表时刻（query-meals.reservationDate）
DEFAULT_TARGET_TIME = {"早餐": "08:00", "午餐": "12:30", "随便吃吃": "16:30",
                       "晚餐": "19:00", "宵夜": "22:30"}


def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def parse_reservation_options(text: str) -> dict[str, list[tuple[str, str]]]:
    """解析 '早餐(07:14至10:15)，午餐(10:44至14:15)，宵夜(00:00至04:45,22:14至23:59)'。

    返回 {餐段名: [(start,end), ...]}，解析失败返回空 dict。
    """
    out: dict[str, list[tuple[str, str]]] = {}
    for name, ranges in SEG_RE.findall(text or ""):
        pairs = RANGE_RE.findall(ranges)
        if pairs:
            out.setdefault(name, []).extend(pairs)
    return out


def _in_ranges(ranges: list[tuple[str, str]], minutes: int) -> bool:
    for s, e in ranges:
        a, b = _to_min(s), _to_min(e)
        if a <= b:
            if a <= minutes <= b:
                return True
        else:  # 跨零点（实测：宵夜 00:00至04:45）
            if minutes >= a or minutes <= b:
                return True
    return False


def resolve_store_daypart(store_options: Optional[str], hhmm: str) -> Optional[str]:
    """按门店实测时段表判定餐段；无表或不落段返回 None（交给兜底）。"""
    table = parse_reservation_options(store_options or "")
    minutes = _to_min(hhmm)
    for seg, ranges in table.items():
        if _in_ranges(ranges, minutes):
            return SEGMENT_ALIAS.get(seg, seg)
    return None


def resolve_daypart(hhmm: str,
                    store_options: Optional[str] = None,
                    user_specified: Optional[str] = None) -> str:
    """餐段判定主入口。用户显式指定 > 门店时段 > 固定兜底。"""
    if user_specified:
        return user_specified
    hit = resolve_store_daypart(store_options, hhmm)
    if hit:
        return hit
    minutes = _to_min(hhmm)
    for seg, ranges in FIXED_RANGES.items():
        if _in_ranges(ranges, minutes):
            return SEGMENT_ALIAS.get(seg, seg)
    return "晚餐"


def target_time_for(store_options: Optional[str], daypart: str) -> str:
    """取某餐段的代表时刻，供 query-meals 的 reservationDate 使用（T17）。

    同一餐段有多段时（如宵夜 00:00–04:45 + 22:14–23:59），取起始最晚的一段，
    保证代表时刻落在"当晚"而非次日零点之后。
    """
    table = parse_reservation_options(store_options or "")
    for seg in table:
        if SEGMENT_ALIAS.get(seg) == daypart:
            s, _e = max(table[seg], key=lambda r: _to_min(r[0]))
            h, m = map(int, s.split(":"))
            total = h * 60 + m + 30  # 起始后 30 分钟
            return f"{(total // 60) % 24:02d}:{total % 60:02d}"
    return DEFAULT_TARGET_TIME.get(daypart, "12:00")


def tier_target(daypart: str, tier: str) -> int:
    return TIERS[daypart][tier]


if __name__ == "__main__":
    demo = ("宵夜(00:00至04:45,22:14至23:59)，早餐(05:14至10:15)，"
            "午餐(10:44至14:15)，下午茶(14:44至16:45)，夜市(17:14至21:45)")
    for t in ["05:30", "10:20", "12:00", "16:00", "18:00", "23:00", "03:00"]:
        print(f"  {t} → {resolve_daypart(t, demo)}")
    print("  无门店表 09:00 →", resolve_daypart("09:00", None))
    print("  早餐代表时刻 →", target_time_for(demo, "早餐"))
    print("  宵夜代表时刻 →", target_time_for(demo, "宵夜"))
    print("  宵夜档位 →", TIERS["宵夜"])
