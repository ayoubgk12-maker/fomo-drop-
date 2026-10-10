import time
import unittest

from tests.helpers import add_series, make_cfg, make_db
from trader.alerts import AlertEngine, validate_rule
from trader.analysis import Analyzer


class AlertsTest(unittest.TestCase):
    def setUp(self):
        self.db = make_db([{"id": f"t:{i}", "source": "t", "name": f"J{i}", "rating": 85} for i in range(4)])
        self.cfg = make_cfg()
        self.engine = AlertEngine(self.db, Analyzer(self.db, self.cfg), self.cfg)
        self.now = time.time()

    def add_rule(self, **rule):
        r = validate_rule(rule)
        self.db.execute("INSERT INTO alert_rules(type, player_id, platform, threshold, window_hours) "
                        "VALUES(?,?,?,?,?)", (r["type"], r["player_id"], r["platform"], r["threshold"],
                                              r["window_hours"]))

    def test_validation(self):
        with self.assertRaises(ValueError):
            validate_rule({"type": "price_below", "threshold": 100})  # falta jugador
        with self.assertRaises(ValueError):
            validate_rule({"type": "nope", "threshold": 1})
        with self.assertRaises(ValueError):
            validate_rule({"type": "market_crash", "threshold": -5})
        self.assertEqual(validate_rule({"type": "pct_rise", "player_id": "t:1", "threshold": 5})["window_hours"], 24.0)

    def test_price_below_fires_once_with_cooldown(self):
        add_series(self.db, "t:0", [10_000, 9_000], end=self.now)
        self.add_rule(type="price_below", player_id="t:0", platform="ps", threshold=9_500)
        fired = self.engine.evaluate(self.now)
        self.assertEqual(len(fired), 1)
        self.assertIn("9.000", fired[0]["message"])
        self.assertEqual(self.engine.evaluate(self.now + 60), [])  # periodo de enfriamiento (60 min)
        self.cfg["alerts"]["cooldown_minutes"] = 20
        self.assertEqual(len(self.engine.evaluate(self.now + 1500)), 1)  # pasado el enfriamiento

    def test_price_below_ignores_stale_prices(self):
        add_series(self.db, "t:0", [10_000, 9_000], end=self.now - 5 * 3600)
        self.add_rule(type="price_below", player_id="t:0", threshold=9_500)
        self.assertEqual(self.engine.evaluate(self.now), [])

    def test_pct_rise(self):
        add_series(self.db, "t:1", [10_000, 10_500, 11_200], end=self.now, every_min=60)
        self.add_rule(type="pct_rise", player_id="t:1", platform="ps", threshold=10, window_hours=6)
        fired = self.engine.evaluate(self.now)
        self.assertEqual(len(fired), 1)
        self.assertAlmostEqual(fired[0]["data"]["change_pct"], 12.0)

    def test_market_crash(self):
        for i in range(4):
            add_series(self.db, f"t:{i}", [10_000, 8_500], end=self.now, every_min=60)
        self.add_rule(type="market_crash", platform="ps", threshold=10, window_hours=6)
        fired = self.engine.evaluate(self.now)
        self.assertEqual(len(fired), 1)
        self.assertIn("Caída de mercado", fired[0]["message"])
        log = self.db.query("SELECT * FROM alert_log")
        self.assertEqual(len(log), 1)


if __name__ == "__main__":
    unittest.main()
