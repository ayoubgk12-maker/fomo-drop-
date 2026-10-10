import json
import unittest

from tests.helpers import NOW, add_series, make_cfg, make_db
from trader.analysis import Analyzer, merge_duplicates, sell_probability, series_stats


def oscillating(n, low=9_500, high=10_500):
    """Serie que alterna entre una zona baja y una alta (mercado lateral con rebotes)."""
    out = []
    for i in range(n):
        phase = i % 8
        out.append(low if phase < 2 else high if phase >= 5 else 10_000)
    return out


class StatsTest(unittest.TestCase):
    def test_insufficient_data(self):
        cfg = make_cfg()
        series = [{"price": 1000, "observed_at": NOW - 600, "source": "t"},
                  {"price": 1100, "observed_at": NOW, "source": "t"}]
        st = series_stats(series, NOW, cfg["analysis"])
        self.assertFalse(st["sufficient"])
        self.assertIn("Datos insuficientes", st["reason"])

    def test_freshness_and_trend(self):
        cfg = make_cfg()
        series = [{"price": int(1000 * 1.002 ** i), "observed_at": NOW - (200 - i) * 900, "source": "t"}
                  for i in range(200)]
        st = series_stats(series, NOW, cfg["analysis"])
        self.assertEqual(st["freshness"], "reciente")
        self.assertEqual(st["trend"], "alcista")
        st_old = series_stats(series, NOW + 30 * 3600, cfg["analysis"])
        self.assertEqual(st_old["freshness"], "caducado")


class ProbabilityTest(unittest.TestCase):
    def test_counts_episodes_and_eta(self):
        series = [{"price": p, "observed_at": i * 3600} for i, p in enumerate(
            [100, 90, 110, 100, 90, 95, 110, 100, 90, 100, 100, 100] + [100] * 30)]
        out = sell_probability(series, buy=90, sell=110, horizon_h=5, min_episodes=3)
        self.assertEqual(out["episodes"], 3)
        self.assertEqual(out["successes"], 2)
        self.assertAlmostEqual(out["probability"], 2 / 3, places=3)

    def test_not_enough_episodes(self):
        series = [{"price": p, "observed_at": i * 3600} for i, p in enumerate([100, 90, 110] + [100] * 30)]
        out = sell_probability(series, buy=90, sell=110, horizon_h=5, min_episodes=5)
        self.assertIsNone(out["probability"])
        self.assertIn("episodios", out["reason"])

    def test_recent_episode_without_full_horizon_is_censored(self):
        series = [{"price": p, "observed_at": i * 3600} for i, p in enumerate([100] * 10 + [90])]
        out = sell_probability(series, buy=90, sell=110, horizon_h=5, min_episodes=1)
        self.assertEqual(out["episodes"], 0)


class OpportunitiesTest(unittest.TestCase):
    def setUp(self):
        self.db = make_db([
            {"id": "t:1", "source": "t", "name": "Lateral", "rating": 85, "position": "ST"},
            {"id": "t:2", "source": "t", "name": "Bajista", "rating": 86, "position": "CB"},
            {"id": "t:3", "source": "t", "name": "Poco historial", "rating": 87, "position": "GK"},
        ])
        self.cfg = make_cfg(strategy={"budget": 200_000, "risk": "high", "time": "medium", "min_profit": 100,
                                      "min_margin_pct": 1.0})
        self.an = Analyzer(self.db, self.cfg)

    def test_flip_rejected_when_tax_eats_the_margin(self):
        # Compra 9.500, venta 10.000: tras el 5 % se reciben 9.500 → beneficio 0. No debe proponerse.
        prices = oscillating(400)
        prices[-1] = 9_500
        add_series(self.db, "t:1", prices)
        res = self.an.opportunities("ps", now=NOW)
        self.assertFalse([o for o in res["items"] if o["player_id"] == "t:1"])
        self.assertTrue(res["skipped"].get("beneficio por debajo del mínimo"))

    def test_profitable_flip_has_probability_and_labels(self):
        prices = [9_000 if i % 8 < 2 else 11_000 if i % 8 >= 5 else 10_500 for i in range(400)]
        prices[-1] = 9_000
        add_series(self.db, "t:1", prices)
        res = self.an.opportunities("ps", now=NOW)
        o = next(o for o in res["items"] if o["player_id"] == "t:1")
        self.assertIn("flip", o["strategies"])
        self.assertEqual(o["data"]["current"], 9_000)
        self.assertEqual(o["data"]["source"], "t")
        self.assertIsNotNone(o["estimate"]["probability"])
        self.assertGreater(o["estimate"]["profit_per_unit"], 0)
        self.assertLessEqual(o["estimate"]["capital"], 200_000)

    def test_no_flip_on_downtrend(self):
        prices = [int(20_000 * 0.995 ** i) for i in range(300)]
        add_series(self.db, "t:2", prices)
        res = self.an.opportunities("ps", now=NOW)
        self.assertFalse([o for o in res["items"] if o["player_id"] == "t:2" and o["strategy"] == "flip"])

    def test_insufficient_and_stale_are_skipped(self):
        add_series(self.db, "t:3", [5_000, 4_000, 5_000])
        res = self.an.opportunities("ps", now=NOW)
        self.assertEqual(res["skipped"].get("datos insuficientes"), 1)
        prices = oscillating(400)
        add_series(self.db, "t:1", prices, end=NOW - 48 * 3600)
        res = self.an.opportunities("ps", now=NOW)
        self.assertNotIn("t:1", [o["player_id"] for o in res["items"]])

    def test_budget_filter(self):
        prices = [9_000 if i % 8 < 2 else 11_000 if i % 8 >= 5 else 10_500 for i in range(400)]
        prices[-1] = 9_000
        add_series(self.db, "t:1", prices)
        res = self.an.opportunities("ps", strategy_cfg={"budget": 5_000}, now=NOW)
        self.assertEqual(res["items"], [])
        self.assertTrue(res["skipped"].get("fuera de presupuesto"))

    def test_pre_event_requires_user_event(self):
        prices = oscillating(400)
        prices[-1] = 9_500
        add_series(self.db, "t:1", prices)
        res = self.an.opportunities("ps", strategy_cfg={"enabled": ["pre_event"]}, now=NOW)
        self.assertEqual(res["items"], [])
        self.db.execute("INSERT INTO events(name, kind, starts_at, player_ids, rating_min, rating_max) "
                        "VALUES(?,?,?,?,?,?)", ("SBC 85", "sbc", NOW + 86400, json.dumps([]), 85, 85))
        res = self.an.opportunities("ps", strategy_cfg={"enabled": ["pre_event"]}, now=NOW)
        self.assertTrue(res["items"])
        self.assertIn("introducido por el usuario", " ".join(res["items"][0]["reasons"]))

    def test_merge_duplicates(self):
        base = {"player_id": "a", "platform": "ps", "estimate": {"buy_price": 1, "sell_price": 2}}
        items = [dict(base, strategy="flip", score=1, reasons=["x"]),
                 dict(base, strategy="dip", score=2, reasons=["y"])]
        merged = merge_duplicates(items)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["strategy"], "dip")
        self.assertEqual(sorted(merged[0]["strategies"]), ["dip", "flip"])
        self.assertEqual(sorted(merged[0]["reasons"]), ["x", "y"])


class MarketViewsTest(unittest.TestCase):
    def test_platform_gap_and_market_change(self):
        db = make_db([{"id": f"t:{i}", "source": "t", "name": f"J{i}", "rating": 85} for i in range(4)])
        cfg = make_cfg()
        an = Analyzer(db, cfg)
        for i in range(4):
            add_series(db, f"t:{i}", [10_000, 9_000, 8_000], platform="ps", every_min=60)
        add_series(db, "t:0", [12_000], platform="pc")
        gaps = an.platform_gaps(now=NOW)
        self.assertEqual(gaps[0]["player_id"], "t:0")
        self.assertEqual(gaps[0]["gap_pct"], 50.0)
        change = an.market_change("ps", 24, now=NOW)
        self.assertEqual(change["change_pct"], -20.0)


if __name__ == "__main__":
    unittest.main()
