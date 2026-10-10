#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/run_tests.py — unittest 结果落盘（带金丝雀防伪造）。
判定规则：结果文件第一行必须含 CANARY 值，否则视为通道伪造，不可采信。"""
import io
import secrets
import traceback
import unittest
from pathlib import Path

CANARY = "CANARY-" + secrets.token_hex(8)
OUT = Path("/tmp/test_result.txt")

buf = io.StringIO()
try:
    here = Path(__file__).resolve().parent
    loader = unittest.TestLoader()
    suite = loader.discover(str(here), top_level_dir=str(here))
    res = unittest.TextTestRunner(stream=buf, verbosity=2).run(suite)
    status = "ALL_PASS" if res.wasSuccessful() else "HAS_FAILURES"
    n_run, n_fail, n_err = res.testsRun, len(res.failures), len(res.errors)
    names = []
    for kind, group in (("FAIL", res.failures), ("ERROR", res.errors)):
        for test, tb in group:
            names.append("%s: %s.%s" % (kind,
                                        type(test).__module__, test._testMethodName))
    detail = buf.getvalue()
except Exception:
    status, n_run, n_fail, n_err, names = "HARNESS_EXC", 0, 0, 0, []
    detail = traceback.format_exc()

lines = [
    CANARY,
    "status=%s run=%d fail=%d err=%d" % (status, n_run, n_fail, n_err),
]
lines += names
lines.append("---- tail of unittest output ----")
lines.append(detail[-2500:])
OUT.write_text("\n".join(lines), encoding="utf-8")
print(CANARY, status, "run=%d fail=%d err=%d" % (n_run, n_fail, n_err))
