#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_engine.py — 引擎侧最小回归套件（v0.9 新增）。

目的：把 SKILL.md 里的红线钉进测试，防止重构/改数据时悄悄破坏。
运行：
    python3 -m unittest discover -s tests -v        # 标准库，零依赖
    pytest tests/ -v                                # pytest 亦兼容收集

覆盖（断言值全部来自 2026-10-10 实测探针，非猜测）：
  · nutrition  匹配矩阵：exact hit / 无证据歧义（不猜值红线）/ unknown
               含已知 bug 的 xfail：alias defaults「怡泉+c」因大小写未归一化
               命不中（mcd_nutrition.Matcher.match defaults 分支），修好后删 xfail
  · daypart    边界矩阵（21:59晚餐/22:00宵夜、跨零点、06:00 早餐线、10:30 午餐线）
               用户显式指定 > 门店时段 > 固定兜底 的优先级
  · goal       ±12% 容差不放宽（lo/hi 公式锁死）、硬上限（钠/碳水/脂肪/价格/预算）、
               0=关闭上限、kids 0.85 缩放、max_items 组合约束
  · taxonomy   品类兜底顺序（甜品→饮品→主食→小食）、组合品无条件排除、
               非食品词与食物词共存不排除（蘸酱炸鸡是食物）
  · cache      中文 key 无碰撞、TTL 过期返回 None、sweep 只删过期、429 退避生命周期
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import mcd_cache as Ccache          # noqa: E402
import mcd_daypart as dp            # noqa: E402
import mcd_goal as G                # noqa: E402
import mcd_taxonomy as tx           # noqa: E402
from mcd_nutrition import Matcher, load_nutrition, normalize_name  # noqa: E402


# ══════════════════════════ nutrition ══════════════════════════

class TestNutrition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = Matcher(load_nutrition())

    def test_exact_hit(self):
        r = self.m.match("巨无霸", allow_defaults=True)
        self.assertEqual(r["status"], "hit")
        self.assertEqual(r["method"], "exact")
        self.assertEqual(r["record"]["kcal"], 513.0)
        self.assertEqual(r["record"]["sodium_mg"], 961.0)

    def test_full_spec_hit(self):
        """带杯型的完整名精确命中（营养表收录的就是带数量条目名）。"""
        r = self.m.match("中杯怡泉+C", allow_defaults=False)
        self.assertEqual(r["status"], "hit")
        self.assertEqual(r["record"]["kcal"], 110.0)

    def test_unknown_no_guess(self):
        """查无此品 → unknown，record 必须 None（不猜值红线）。"""
        r = self.m.match("不存在的汉堡XZ", allow_defaults=True)
        self.assertEqual(r["status"], "unknown")
        self.assertIsNone(r["record"])

    def test_spec_missing_is_ambiguous(self):
        """怡泉+C 无杯型且不用 defaults 证据 → 歧义（中杯/大杯二选一），
        禁止猜值（PRD §7）。注意：allow_defaults=True 时有 alias.json#defaults
        证据消歧为中杯，由 test_defaults_should_resolve_ambiguous 覆盖。"""
        r = self.m.match("怡泉+C", allow_defaults=False)
        self.assertEqual(r["status"], "ambiguous")
        self.assertIn("中杯怡泉+C", r["candidates"])
        self.assertIn("大杯怡泉+C", r["candidates"])

    def test_defaults_should_resolve_ambiguous(self):
        """defaults 证据可消解歧义：alias.json#defaults 有「怡泉+c → 中杯怡泉+C」，
        match 的 defaults 分支对 dft 归一化后再查 by_key（2026-10-10 修复大小写 miss），
        allow_defaults=True 时「怡泉+C」应命中中杯而非 ambiguous。"""
        r = self.m.match("怡泉+C", allow_defaults=True)
        self.assertEqual(r["status"], "hit")
        self.assertEqual(r["record"]["name"], "中杯怡泉+C")

    def test_normalize_lowercases(self):
        self.assertEqual(normalize_name("怡泉+C"), "怡泉+c")


# ══════════════════════════ daypart ══════════════════════════

class TestDaypart(unittest.TestCase):
    def test_fixed_range_boundaries(self):
        """固定兜底边界矩阵（21:59 晚餐 / 22:00 宵夜 / 跨零点 / 两条晨午线）。"""
        cases = {
            "21:59": "晚餐", "22:00": "宵夜", "22:14": "宵夜", "23:59": "宵夜",
            "00:00": "宵夜", "05:59": "宵夜",           # 跨零点归宵夜
            "06:00": "早餐", "10:29": "早餐",
            "10:30": "午餐", "15:29": "午餐",
            "15:30": "随便吃吃", "17:59": "随便吃吃",
            "18:00": "晚餐",
        }
        for t, want in cases.items():
            self.assertEqual(dp.resolve_daypart(t, None), want, t)

    def test_store_table_cross_midnight(self):
        opts = "宵夜(00:00至04:45,22:14至23:59)"
        self.assertEqual(dp.resolve_store_daypart(opts, "03:00"), "宵夜")
        self.assertEqual(dp.resolve_store_daypart(opts, "22:14"), "宵夜")
        self.assertIsNone(dp.resolve_store_daypart(opts, "22:05"))  # 表内空档→交兜底

    def test_segment_alias(self):
        """接口餐段名映射：夜市→晚餐、下午茶→随便吃吃。"""
        self.assertEqual(dp.resolve_store_daypart("夜市(17:14至21:45)", "18:00"), "晚餐")
        self.assertEqual(dp.resolve_store_daypart("下午茶(14:44至16:45)", "15:00"), "随便吃吃")

    def test_user_specified_wins(self):
        self.assertEqual(dp.resolve_daypart("12:00", None, "宵夜"), "宵夜")

    def test_tier_targets(self):
        self.assertEqual(dp.tier_target("宵夜", "标准"), 450)
        self.assertEqual(dp.tier_target("午餐", "吃饱"), 1000)
        self.assertEqual(dp.tier_target("早餐", "轻量"), 300)

    def test_target_time_picks_latest_start(self):
        """多段餐段取起始最晚的一段（宵夜代表时刻落当晚而非次日）。"""
        opts = "宵夜(00:00至04:45,22:14至23:59)"
        self.assertEqual(dp.target_time_for(opts, "宵夜"), "22:44")  # 22:14+30min


# ══════════════════════════ goal ══════════════════════════

class TestGoalPlan(unittest.TestCase):
    def test_no_goal_is_tier_only(self):
        plan = G.resolve_plan("午餐", "标准", None)
        self.assertEqual(plan["target"], 750)
        self.assertEqual(plan["lo"], 660)   # 750 × 0.88
        self.assertEqual(plan["hi"], 840)   # 750 × 1.12

    def test_cut_uses_prefer_tier(self):
        """cut 场景强制用轻量档（不跟随用户档位），±12% 锁死。"""
        plan = G.resolve_plan("午餐", "吃饱", "cut")
        self.assertEqual(plan["tier_used"], "轻量")
        self.assertEqual(plan["target"], 500)
        self.assertEqual(plan["lo"], 440)
        self.assertEqual(plan["hi"], 560)

    def test_tolerance_not_widened(self):
        """容差红线：lo/hi 严格 = target×(1∓0.12)，引擎不得自行放宽。"""
        for goal, target in (("cut", 500), ("low-sodium", 500), ("high-protein", 750)):
            plan = G.resolve_plan("午餐", "标准", goal)
            self.assertEqual(plan["lo"], round(target * 0.88), goal)
            self.assertEqual(plan["hi"], round(target * 1.12), goal)

    def test_low_sodium_hard_cap(self):
        plan = G.resolve_plan("午餐", "标准", "low-sodium")
        self.assertEqual(plan["limits"], {"sodium_mg": 1000.0})

    def test_kids_scale(self):
        plan = G.resolve_plan("午餐", "标准", "kids")
        self.assertEqual(plan["target"], 425)   # 500 × 0.85
        self.assertEqual(plan["max_items"], 2)

    def test_param_overrides_limits(self):
        plan = G.resolve_plan("午餐", "标准", "low-sodium", {"sodium_max": 800})
        self.assertEqual(plan["limits"], {"sodium_mg": 800.0})

    def test_zero_disables_limit(self):
        """上限传 0 = 关闭（用户显式关闭，不是放宽默认）。"""
        plan = G.resolve_plan("午餐", "标准", "low-sodium", {"sodium_max": 0})
        self.assertEqual(plan["limits"], {})

    def test_unknown_goal_is_none(self):
        self.assertIsNone(G.get_goal("no-such-goal"))
        self.assertIsNone(G.get_goal(None))


class TestGoalHardLimits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = G.resolve_plan("午餐", "标准", "low-sodium")

    @staticmethod
    def totals(**kw):
        base = {"kcal": 700, "protein": 20, "fat": 20, "carb": 50,
                "sodium_mg": 900, "price": 30}
        base.update(kw)
        return base

    def test_sodium_within(self):
        self.assertTrue(G.totals_allowed(self.totals(), self.plan))

    def test_sodium_exceed(self):
        self.assertFalse(G.totals_allowed(self.totals(sodium_mg=1200), self.plan))

    def test_zero_limit_passes_everything(self):
        plan = G.resolve_plan("午餐", "标准", "low-sodium", {"sodium_max": 0})
        self.assertTrue(G.totals_allowed(self.totals(sodium_mg=99999), plan))

    def test_carb_fat_price_caps(self):
        carb = G.resolve_plan("午餐", "标准", "low-carb")
        self.assertFalse(G.totals_allowed(self.totals(carb=61), carb))
        self.assertTrue(G.totals_allowed(self.totals(carb=60), carb))
        fat = G.resolve_plan("午餐", "标准", "low-fat")
        self.assertFalse(G.totals_allowed(self.totals(fat=30.5), fat))
        val = G.resolve_plan("午餐", "标准", "value", {"price_max": 25})
        self.assertFalse(G.totals_allowed(self.totals(price=26), val))

    def test_budget_is_the_target(self):
        """daily-budget：budget 入参替换目标（target_from_param），
        区间 = 预算×[0.70, 1.00]（用满预算但不超）。"""
        plan = G.resolve_plan("午餐", "标准", "daily-budget", {"budget": 600})
        self.assertEqual(plan["target"], 600)
        self.assertEqual(plan["hi"], 600)   # 600 × 1.00
        self.assertEqual(plan["lo"], 420)   # 600 × 0.70

    def test_combo_max_items(self):
        plan = G.resolve_plan("午餐", "标准", "kids")   # max_items=2
        self.assertFalse(G.combo_allowed([1, 2, 3], plan))
        self.assertTrue(G.combo_allowed([1, 2], plan))
        self.assertTrue(G.combo_allowed([1], plan))

    def test_no_max_items_always_ok(self):
        plan = G.resolve_plan("午餐", "标准", "cut")    # max_items 未设
        self.assertTrue(G.combo_allowed([1] * 9, plan))


class TestPoolFilter(unittest.TestCase):
    def test_vegetarian_excludes_meat(self):
        plan = G.resolve_plan("午餐", "轻量", "vegetarian")
        pools = {"主食": [{"name": "巨无霸"}, {"name": "麦满分"}],
                 "小食": [{"name": "麦辣鸡翅"}]}
        out = G.filter_pools(pools, plan)
        self.assertEqual(out["主食"], [{"name": "麦满分"}])
        self.assertEqual(out["小食"], [])

    def test_cut_removes_dessert(self):
        plan = G.resolve_plan("午餐", "轻量", "cut")    # allow_dessert=False
        pools = {"主食": [{"name": "麦满分"}],
                 "小食": [{"name": "麦旋风"}, {"name": "中薯条"}]}
        out = G.filter_pools(pools, plan)
        self.assertEqual(out["小食"], [{"name": "中薯条"}])
        # 且不改原池
        self.assertEqual(len(pools["小食"]), 2)

    def test_allergen_warning_required(self):
        """过敏原是关键词粗筛 → 计划必须带警告（内容红线）。"""
        plan = G.resolve_plan("午餐", "标准", "allergen", {"allergens": ["花生"]})
        self.assertIsNotNone(plan["warning"])
        self.assertIn("粗筛", plan["warning"])


# ══════════════════════════ taxonomy ══════════════════════════

class TestTaxonomy(unittest.TestCase):
    def test_keyword_category_order(self):
        """兜底顺序：甜品→饮品→主食→小食；甜品/小食都归「小食」池。"""
        self.assertEqual(tx.keyword_category("麦旋风"), "小食")        # 甜品优先
        self.assertEqual(tx.keyword_category("麦旋风咖啡"), "小食")    # 甜品在饮品前
        self.assertEqual(tx.keyword_category("可口可乐中杯"), "饮品")
        self.assertEqual(tx.keyword_category("板烧鸡腿堡"), "主食")
        self.assertEqual(tx.keyword_category("中薯条"), "小食")

    def test_keyword_category_none(self):
        """「巨无霸」不含「堡」字且无其他关键词 → None（第一级菜单分类负责它）。"""
        self.assertIsNone(tx.keyword_category("巨无霸"))

    def test_combo_name_excluded_unconditionally(self):
        self.assertEqual(tx.excluded("巨无霸中套餐"), "套餐")
        self.assertEqual(tx.excluded("麦乐鸡件套"), "件套")

    def test_nonfood_with_food_hint_kept(self):
        """「蘸酱炸鸡」含食物词 → 不排除（是含酱的食物，非单卖蘸酱）。"""
        self.assertIsNone(tx.excluded("蘸酱炸鸡"))
        self.assertIsNone(tx.excluded("5块心形薯饼+韩式辣椒黄油风味酱"))

    def test_nonfood_without_food_hint_excluded(self):
        self.assertEqual(tx.excluded("按摩捶"), "按摩捶")
        self.assertEqual(tx.excluded("山葵酱"), "山葵酱")

    def test_normal_food_not_excluded(self):
        self.assertIsNone(tx.excluded("中杯可口可乐"))

    def test_menu_category_newline_stripped(self):
        self.assertEqual(tx.category_from_menu_name("麦咖啡\n咖啡"), "饮品")

    def test_rules_loaded_once(self):
        """规则唯一加载点：taxonomy.RULES 即 category-rules.json。"""
        rules = json.loads(
            (SKILL_ROOT / "data" / "category-rules.json").read_text(encoding="utf-8"))
        self.assertEqual(tx.RULES, rules)


# ══════════════════════════ cache ══════════════════════════

class TestCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = (Ccache.CACHE_DIR, Ccache.BACKOFF_FILE)
        Ccache.CACHE_DIR = Path(self._tmp.name)
        Ccache.BACKOFF_FILE = Ccache.CACHE_DIR / "_backoff.json"

    def tearDown(self):
        Ccache.CACHE_DIR, Ccache.BACKOFF_FILE = self._saved
        self._tmp.cleanup()

    def test_cjk_keys_no_collision(self):
        """中文 key 不碰撞（曾因 ASCII 白名单把「午餐/晚餐」折叠成同名）。"""
        p1 = Ccache.put("menu", "3570190-午餐", {"m": "lunch"})
        p2 = Ccache.put("menu", "3570190-晚餐", {"m": "dinner"})
        self.assertNotEqual(p1, p2)
        self.assertEqual(Ccache.get("menu", "3570190-午餐")["m"], "lunch")
        self.assertEqual(Ccache.get("menu", "3570190-晚餐")["m"], "dinner")

    def test_ttl_per_kind(self):
        """同一条目在不同 kind 下 TTL 不同：取「2 小时前」——
        menu（10min）已过期，nutrition（24h）仍新鲜。"""
        two_h_ago = (datetime.now(Ccache._TZ) - timedelta(hours=2)).strftime(Ccache._ISO_FMT)
        stale_for_menu = {"x": 1, "_meta": {"fetchedAt": two_h_ago}}
        Ccache.put("menu", "k", stale_for_menu)
        Ccache.put("nutrition", "k", stale_for_menu)
        self.assertIsNone(Ccache.get("menu", "k"))
        self.assertIsNotNone(Ccache.get("nutrition", "k"))

    def test_get_missing_is_none(self):
        self.assertIsNone(Ccache.get("menu", "never-written"))

    def test_sweep_removes_only_expired(self):
        two_h_ago = (datetime.now(Ccache._TZ) - timedelta(hours=2)).strftime(Ccache._ISO_FMT)
        Ccache.put("menu", "old", {"x": 1, "_meta": {"fetchedAt": two_h_ago}})
        Ccache.put("menu", "new", {"x": 2})   # fetchedAt=now
        self.assertEqual(Ccache.sweep(), 1)
        self.assertIsNone(Ccache.get("menu", "old"))
        self.assertIsNotNone(Ccache.get("menu", "new"))

    def test_put_stamps_now_on_unparseable_ts(self):
        """put 的设计：fetchedAt 缺失/不可解析 → 补写当前时间
        （文件确实是此刻采集的，落真实语义而非垃圾戳）。"""
        Ccache.put("menu", "bad", {"x": 1, "_meta": {"fetchedAt": "garbage"}})
        raw = json.loads(Ccache.path("menu", "bad").read_text(encoding="utf-8"))
        self.assertIsNotNone(Ccache._parse_ts(raw["_meta"]["fetchedAt"]))

    def test_unparseable_ts_treated_expired(self):
        """get 侧：文件里的 fetchedAt 不可解析（外部写入/损坏）→ 视为过期，
        宁可重采不猜。绕过 put 直写文件以构造该状态。"""
        p = Ccache.path("menu", "corrupt")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"x": 1, "_meta": {"fetchedAt": "garbage"}}),
                     encoding="utf-8")
        self.assertIsNone(Ccache.get("menu", "corrupt"))

    def test_upstream_fetched_at_preserved(self):
        Ccache.put("menu", "u", {"x": 1, "_meta": {"fetchedAt": "2026-10-10T09:00:00+0800"}})
        raw = json.loads(Ccache.path("menu", "u").read_text(encoding="utf-8"))
        self.assertEqual(raw["_meta"]["fetchedAt"], "2026-10-10T09:00:00+0800")

    def test_backoff_lifecycle(self):
        tool = "list-nutrition-foods"
        Ccache.set_backoff(tool, 30, "test 429")
        self.assertTrue(Ccache.backoff_active(tool))
        self.assertGreater(Ccache.backoff_remaining(tool), 25)
        self.assertFalse(Ccache.backoff_active("query-meals"))   # 按工具隔离
        Ccache.clear_backoff(tool)
        self.assertFalse(Ccache.backoff_active(tool))
        self.assertEqual(Ccache.backoff_remaining(tool), 0.0)

    def test_clear_backoff_all(self):
        Ccache.set_backoff("a", 30)
        Ccache.set_backoff("b", 30)
        Ccache.clear_backoff(None)
        self.assertFalse(Ccache.backoff_active("a"))
        self.assertFalse(Ccache.backoff_active("b"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
