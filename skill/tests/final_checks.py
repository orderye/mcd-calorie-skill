#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""final_checks.py — 收尾验证：eval_match + 注入幂等（带金丝雀，结果落盘）。

页面文件不按名硬编码（沙箱回显对中文名有改写），改为按内容签名定位：
项目根下含 `hm-skin` 切换器与 `CATS` 数据块的单文件演示页。
"""
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

CANARY = "CANARY-" + secrets.token_hex(8)
SKILL = Path(__file__).resolve().parent.parent          # skill/
ROOT = SKILL.parent                                      # 项目根
OUT = Path("/tmp/final_checks.txt")

lines = [CANARY]

# ── 0) 按签名定位演示页 ──
def find_page() -> Path:
    hits = []
    for p in ROOT.glob("*.html"):
        try:
            t = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "hm-skin" in t and "var CATS" in t.replace(" ", "")[:200000] or \
           ("hm-skin" in t and "CATS" in t and "ROUNDS" in t):
            hits.append(p)
    if len(hits) != 1:
        raise SystemExit("定位失败：签名命中 %d 个 → %s" % (len(hits), [p.name for p in hits]))
    return hits[0]

PAGE = find_page()
lines.append("[page] %s" % PAGE.name)

# ── 1) eval_match ──
r = subprocess.run([sys.executable, str(SKILL / "tools" / "eval_match.py")],
                   capture_output=True, text=True, cwd=str(SKILL))
tail = (r.stdout or "").strip().splitlines()[-6:]
lines.append("[eval_match] exit=%d" % r.returncode)
lines += ["  " + t for t in tail]

# ── 2) 注入幂等（备份 → inject → 比对 → 有差异则还原）──
bk = Path("/tmp/order-page-backup-final.html")
shutil.copy2(PAGE, bk)
r2 = subprocess.run([sys.executable, str(SKILL / "scripts" / "build_demo_menu.py"), "inject"],
                    capture_output=True, text=True, cwd=str(ROOT))
same = bk.read_bytes() == PAGE.read_bytes()
lines.append("[inject] exit=%d identical=%s" % (r2.returncode, same))
if not same:
    shutil.copy2(bk, PAGE)
    lines.append("  CHANGED → 已从备份还原（请人工核查 inject 输出）")
else:
    bk.unlink(missing_ok=True)
    lines.append("  IDEMPOTENT_OK")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(CANARY, "DONE")
