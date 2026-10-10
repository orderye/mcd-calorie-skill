#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcd_cache.py — 带 TTL 的本地缓存机制（v0.9 新增）。

背景：SKILL.md 的缓存纪律（营养表 ≥24h、菜单按 店+餐段 10min、429 退避）
原本只写在文档里靠自觉。本模块把纪律落成机制：

  · 缓存文件：data/cache/<kind>/<safe_key>.json，JSON 内含 _meta.fetchedAt
    （ISO 北京时间，来源响应里的 fetchedAt / datetime 优先，写入时兜底补 now）。
  · get(kind, key)：超 TTL 或无文件 → None，调用方自行重新采集。
  · 429 退避：data/cache/_backoff.json 记录各工具的冷却截止 epoch，
    冷却期内 backoff_active(tool) 为真，调用方应跳过请求。

TTL 表（秒）——与 SKILL.md「限流 600 次/分钟」一节保持一致：
  nutrition ≥24h；menu（按 店+餐段）10min；其余默认 24h。

CLI（供人查缓存状态，脚本走 import）：
  python3 scripts/mcd_cache.py list                 # 全部缓存条目+剩余有效期
  python3 scripts/mcd_cache.py show <kind> <key>    # 看单条（打印 JSON）
  python3 scripts/mcd_cache.py clear [--kind K]     # 清空（全部或某类）

约束：仅标准库；不触碰 fixtures/；不做任何网络请求（采集仍由
fetch_meal_details.py / Agent 的 MCP 工具完成，这里只管存取与时效）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

SKILL_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = SKILL_ROOT / "data" / "cache"
BACKOFF_FILE = CACHE_DIR / "_backoff.json"

# ── TTL（秒）。键 = 缓存 kind，与 SKILL.md 限流纪律一致 ──
TTL = {
    "nutrition": 24 * 3600,   # 营养表全量缓存 ≥24h
    "menu": 10 * 60,          # 菜单按 店+餐段 缓存 10min
}
DEFAULT_TTL = 24 * 3600

# 北京时间（Asia/Shanghai 无夏令时，固定 +8）
_TZ = timezone(timedelta(hours=8))
_ISO_FMT = "%Y-%m-%dT%H:%M:%S%z"


def now_iso() -> str:
    return datetime.now(_TZ).strftime(_ISO_FMT)


def _safe_key(key: str) -> str:
    """任意 key → 安全文件名。

    保留 \\w（含中文/数字/下划线，本项目 key 天然是「店+餐段」中文）与 . -，
    其余（/ 空格 : 控制符等）折叠为 _。注意：不能只用 ASCII 白名单，
    否则「3570190-午餐」「3570190-晚餐」会碰撞成同一文件名互相覆盖。
    """
    k = re.sub(r"[^\w.\-]+", "_", str(key), flags=re.UNICODE)
    return k.strip("._")[:120] or "_"


def path(kind: str, key: str) -> Path:
    return CACHE_DIR / _safe_key(kind) / (_safe_key(key) + ".json")


def _load(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                  # noqa: BLE001
        return None


def _parse_ts(v: Any) -> Optional[float]:
    """把 _meta.fetchedAt 解析成 epoch；解析失败返回 None（宁可重采不猜）。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    for fmt in (_ISO_FMT, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=_TZ).timestamp()
        except ValueError:
            continue
    return None


def age(kind: str, key: str) -> Optional[float]:
    """缓存条目的年龄（秒）；无条目或时间戳不可解析 → None。"""
    d = _load(path(kind, key))
    if not d:
        return None
    meta = d.get("_meta") or {}
    return _age_from_ts(meta.get("fetchedAt"))


def _age_from_ts(ts: Any) -> Optional[float]:
    ep = _parse_ts(ts)
    if ep is None:
        return None
    return max(0.0, time.time() - ep)


def get(kind: str, key: str, ttl: Optional[int] = None) -> Optional[dict]:
    """命中且未超 TTL → 返回 payload dict；否则 None（调用方重采）。"""
    p = path(kind, key)
    if not p.exists():
        return None
    d = _load(p)
    if not d:
        return None
    ttl = TTL.get(kind, DEFAULT_TTL) if ttl is None else ttl
    a = _age_from_ts((d.get("_meta") or {}).get("fetchedAt"))
    if a is None or a > ttl:
        return None
    return d


def put(kind: str, key: str, payload: dict) -> Path:
    """写入缓存。若 payload 已带 _meta.fetchedAt（如上游响应的 datetime）则沿用，
    否则补写当前北京时间。返回缓存文件路径。"""
    p = path(kind, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    meta = dict(body.get("_meta") or {})
    if not _parse_ts(meta.get("fetchedAt")):
        meta["fetchedAt"] = now_iso()
    body["_meta"] = meta
    p.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return p


def sweep(max_age: Optional[float] = None) -> int:
    """删除超龄缓存文件，返回删除数。max_age=None 时按各 kind 的 TTL 判。"""
    removed = 0
    if not CACHE_DIR.exists():
        return 0
    for p in sorted(CACHE_DIR.rglob("*.json")):
        if p.name == BACKOFF_FILE.name:
            continue
        kind = p.parent.name
        d = _load(p)
        if not d:
            p.unlink(missing_ok=True)
            removed += 1
            continue
        ttl = max_age if max_age is not None else TTL.get(kind, DEFAULT_TTL)
        a = _age_from_ts((d.get("_meta") or {}).get("fetchedAt"))
        if a is None or a > ttl:
            p.unlink(missing_ok=True)
            removed += 1
    return removed


# ────────────────────────── 429 退避 ──────────────────────────

def _load_backoff() -> dict:
    try:
        return json.loads(BACKOFF_FILE.read_text(encoding="utf-8"))
    except Exception:                                  # noqa: BLE001
        return {}


def backoff_active(tool: str) -> bool:
    """该工具仍在 429 冷却期内 → True（调用方应跳过请求）。"""
    b = _load_backoff().get(tool) or {}
    until = b.get("until")
    try:
        return time.time() < float(until)
    except (TypeError, ValueError):
        return False


def backoff_remaining(tool: str) -> float:
    """冷却剩余秒数；未在冷却 → 0.0。"""
    b = _load_backoff().get(tool) or {}
    try:
        return max(0.0, float(b.get("until", 0)) - time.time())
    except (TypeError, ValueError):
        return 0.0


def set_backoff(tool: str, seconds: float, reason: str = "") -> None:
    """记录冷却截止时间（收到 429 时调用）。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    b = _load_backoff()
    b[tool] = {"until": time.time() + seconds, "reason": reason,
               "setAt": now_iso()}
    BACKOFF_FILE.write_text(json.dumps(b, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")


def clear_backoff(tool: Optional[str] = None) -> None:
    """成功响应后清除冷却（tool=None 清全部）。"""
    if tool is None:
        BACKOFF_FILE.unlink(missing_ok=True)
        return
    b = _load_backoff()
    if tool in b:
        del b[tool]
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        BACKOFF_FILE.write_text(json.dumps(b, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")


# ────────────────────────── CLI ──────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="mcd 本地缓存查看/清理（无网络操作）")
    ap.add_argument("cmd", choices=["list", "show", "clear"])
    ap.add_argument("kind", nargs="?")
    ap.add_argument("key", nargs="?")
    ap.add_argument("--all", action="store_true", help="clear: 清全部 kind")
    a = ap.parse_args()

    if a.cmd == "show":
        if not (a.kind and a.key):
            print("用法: mcd_cache.py show <kind> <key>", file=sys.stderr)
            return 2
        d = get(a.kind, a.key)
        if d is None:
            print("(未命中或已过期)", file=sys.stderr)
            return 1
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return 0

    if a.cmd == "clear":
        targets = [CACHE_DIR] if a.all else ([CACHE_DIR / _safe_key(a.kind)] if a.kind else None)
        if not targets:
            print("用法: mcd_cache.py clear <kind> | clear --all", file=sys.stderr)
            return 2
        n = 0
        for t in targets:
            if t.exists():
                for p in sorted(t.rglob("*.json")):
                    p.unlink(missing_ok=True)
                    n += 1
        print("已清除 %d 个缓存文件" % n)
        return 0

    # list
    if not CACHE_DIR.exists():
        print("(缓存目录不存在：%s)" % CACHE_DIR)
        return 0
    for kind_dir in sorted(p for p in CACHE_DIR.iterdir() if p.is_dir()):
        files = sorted(kind_dir.glob("*.json"))
        if not files:
            continue
        ttl = TTL.get(kind_dir.name, DEFAULT_TTL)
        print("[%s]  TTL=%s" % (kind_dir.name,
                                "%dm" % (ttl // 60) if ttl < 3600 else "%dh" % (ttl // 3600)))
        for p in files:
            d = _load(p) or {}
            a_s = _age_from_ts((d.get("_meta") or {}).get("fetchedAt"))
            if a_s is None:
                state = "?"
            elif a_s > ttl:
                state = "已过期"
            else:
                state = "剩 %s" % ("%dm%02ds" % (int(ttl - a_s) // 60, int(ttl - a_s) % 60)
                                   if ttl < 3600 else
                                   "%.1fh" % ((ttl - a_s) / 3600))
            print("  %-50s %s" % (p.stem, state))
    b = _load_backoff()
    if b:
        print("[429 退避]")
        for tool, v in sorted(b.items()):
            print("  %-24s 剩 %.0fs  (%s)" % (tool, backoff_remaining(tool),
                                              v.get("reason", "")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
