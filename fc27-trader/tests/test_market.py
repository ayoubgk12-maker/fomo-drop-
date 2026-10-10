import unittest

from trader.market import MarketRules


class MarketRulesTest(unittest.TestCase):
    def setUp(self):
        self.r = MarketRules()

    def test_steps_per_tier(self):
        self.assertEqual(self.r.step(500), 50)
        self.assertEqual(self.r.step(1000), 100)
        self.assertEqual(self.r.step(9900), 100)
        self.assertEqual(self.r.step(10000), 250)
        self.assertEqual(self.r.step(50000), 500)
        self.assertEqual(self.r.step(150000), 1000)

    def test_rounding(self):
        self.assertEqual(self.r.round_down(1234), 1200)
        self.assertEqual(self.r.round_up(1234), 1300)
        self.assertEqual(self.r.round_down(10_100), 10_000)
        self.assertEqual(self.r.round_up(9_950), 10_000)
        self.assertEqual(self.r.round_down(120), 150)  # precio mínimo
        self.assertEqual(self.r.next_price(9_900), 10_000)
        self.assertEqual(self.r.next_price(10_000), 10_250)

    def test_tax_and_profit(self):
        self.assertEqual(self.r.net_after_tax(10_000), 9_500)
        self.assertEqual(self.r.tax(10_000), 500)
        self.assertEqual(self.r.net_after_tax(1_050), 997)  # redondeo prudente hacia abajo
        p = self.r.profit(10_000, 11_500, quantity=3)
        self.assertEqual(p["net_sell"], 10_925)
        self.assertEqual(p["profit_per_unit"], 925)
        self.assertEqual(p["total_profit"], 2_775)
        self.assertEqual(p["capital"], 30_000)
        self.assertAlmostEqual(p["margin_pct"], 9.25)

    def test_breakeven(self):
        be = self.r.breakeven_sell(10_000)
        self.assertGreaterEqual(self.r.net_after_tax(be), 10_000)
        self.assertLess(self.r.net_after_tax(be - self.r.step(be - 1)), 10_000)
        self.assertEqual(be, 10_750)

    def test_clamp_to_range(self):
        self.assertEqual(self.r.clamp_to_range(20_000, 5_000, 15_000), 15_000)
        self.assertEqual(self.r.clamp_to_range(1_000, 5_000, 15_000), 5_000)
        self.assertEqual(self.r.clamp_to_range(12_345, None, None), 12_250)

    def test_configurable(self):
        r = MarketRules.from_config({"tax_rate": 0.1, "min_price": 200, "tiers": [[None, 100]]})
        self.assertEqual(r.net_after_tax(1000), 900)
        self.assertEqual(r.round_down(150), 200)
        self.assertEqual(r.step(99999), 100)


if __name__ == "__main__":
    unittest.main()
