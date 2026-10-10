import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from tests.helpers import make_cfg, make_db
from trader.server import App, make_server
from trader.sources.base import AuthError, PriceQuote, PriceSource, SourceError
from trader.sources.manual import import_csv
from trader.updater import Updater


class FakeSource(PriceSource):
    name = "fake"
    kind = "api"
    supports_prices = True

    def __init__(self, behaviour="ok"):
        self.behaviour = behaviour
        self.requested = []

    def fetch_prices(self, ids, stop_event=None):
        self.requested.append(list(ids))
        for pid in ids:
            if self.behaviour == "auth":
                yield AuthError("HTTP 401")
                return
            if self.behaviour == "fail":
                yield SourceError("HTTP 500")
                continue
            yield PriceQuote(pid, "ps", 1000, self.name, time.time())


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        self.db = make_db([{"id": f"fake:{i}", "source": "fake", "name": f"J{i}", "rating": 80 + i}
                           for i in range(10)])
        self.cfg = make_cfg(tracking={"max_tracked_players": 4, "min_rating": 0, "include_watchlist": True})

    def test_saves_prices_and_status(self):
        src = FakeSource()
        up = Updater(self.db, self.cfg, [src])
        res = up.run_once()
        self.assertEqual(res["sources"]["fake"]["prices_saved"], 4)
        self.assertEqual(self.db.get_source_status("fake")["state"], "ok")

    def test_watchlist_first_and_rotation(self):
        self.db.execute("INSERT INTO watchlist(player_id, added_at) VALUES('fake:0', 0)")
        src = FakeSource()
        up = Updater(self.db, self.cfg, [src])
        up.run_once()
        up.run_once()
        first, second = src.requested
        self.assertEqual(first[0], "fake:0")
        self.assertEqual(second[0], "fake:0")
        self.assertNotEqual(first[1:], second[1:])  # rota el resto de jugadores

    def test_auth_error_stops_source(self):
        up = Updater(self.db, self.cfg, [FakeSource("auth")])
        up.run_once()
        st = self.db.get_source_status("fake")
        self.assertEqual(st["state"], "auth_error")
        res = up.run_once()
        self.assertEqual(res["sources"]["fake"]["state"], "auth_error")

    def test_restart_clears_auth_error(self):
        Updater(self.db, self.cfg, [FakeSource("auth")]).run_once()
        self.assertEqual(self.db.get_source_status("fake")["state"], "auth_error")
        src = FakeSource()  # p. ej. tras poner un token válido y reiniciar
        res = Updater(self.db, self.cfg, [src]).run_once()
        self.assertEqual(res["sources"]["fake"]["state"], "ok")

    def test_circuit_breaker_opens_after_three_failures(self):
        src = FakeSource("fail")
        up = Updater(self.db, self.cfg, [src])
        for _ in range(3):
            self.db.update_source_status("fake", next_attempt_at=None)
            up.run_once()
        st = self.db.get_source_status("fake")
        self.assertEqual(st["state"], "circuit_open")
        self.assertEqual(st["consecutive_failures"], 3)
        self.assertGreater(st["next_attempt_at"], time.time())
        calls = len(src.requested)
        up.run_once()
        self.assertEqual(len(src.requested), calls)  # en pausa: no consulta


class CsvImportTest(unittest.TestCase):
    def test_import(self):
        db = make_db()
        text = ("name,platform,price,observed_at,source\n"
                "Jugador Uno,ps,12500,2026-10-10T10:00:00Z,mercado del juego\n"
                "Nuevo Jugador,xbox,3000,,\n"
                "Malo,switch,100,,\n"
                "Sin precio,pc,,,\n")
        res = import_csv(db, text)
        self.assertEqual(res["saved"], 2)
        self.assertEqual(len(res["errors"]), 2)
        self.assertTrue(db.get_player("manual:nuevo-jugador"))
        row = db.one("SELECT * FROM prices WHERE player_id='t:1'")
        self.assertEqual(row["source"], "manual:mercado-del-juego")
        self.assertEqual(row["platform"], "ps")

    def test_rejects_missing_columns(self):
        with self.assertRaises(ValueError):
            import_csv(make_db(), "foo,bar\n1,2\n")


class ApiTest(unittest.TestCase):
    """Arranca el servidor real en un puerto libre contra bases de datos temporales."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = make_cfg()
        cfg["sources"]["futdb"]["token"] = ""
        cls.demo = App(make_cfg(), demo=True, db_path=str(Path(cls.tmp.name) / "demo.db"))
        cls.demo.updater.run_once()
        cls.real = App(cfg, demo=False, db_path=str(Path(cls.tmp.name) / "real.db"))
        cls.servers = []
        for app in (cls.demo, cls.real):
            srv = make_server(app, "127.0.0.1", 0)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            cls.servers.append(srv)
        cls.demo_url = "http://127.0.0.1:%d" % cls.servers[0].server_address[1]
        cls.real_url = "http://127.0.0.1:%d" % cls.servers[1].server_address[1]

    @classmethod
    def tearDownClass(cls):
        for s in cls.servers:
            s.shutdown()
            s.server_close()
        cls.tmp.cleanup()

    def call(self, base, path, method="GET", body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_status_reports_modes_and_sources(self):
        _, s = self.call(self.demo_url, "/api/status")
        self.assertEqual(s["mode"], "demo")
        _, s = self.call(self.real_url, "/api/status")
        self.assertEqual(s["mode"], "real")
        by_name = {x["name"]: x for x in s["sources"]}
        self.assertFalse(by_name["futdb"]["available"])
        self.assertIn("token", by_name["futdb"]["reason"])
        self.assertFalse(by_name["futbin"]["available"])
        self.assertFalse(by_name["futgg"]["available"])
        self.assertNotIn("secreto", json.dumps(s))

    def test_demo_data_is_flagged(self):
        _, players = self.call(self.demo_url, "/api/players?limit=5")
        self.assertTrue(players["items"])
        self.assertTrue(all(p["is_demo"] and p["name"].startswith("[DEMO]") for p in players["items"]))
        _, opps = self.call(self.demo_url, "/api/opportunities?risk=high&time=long")
        for o in opps["items"]:
            self.assertTrue(o["data"]["is_demo"])

    def test_demo_rejects_real_prices(self):
        status, body = self.call(self.demo_url, "/api/prices/manual", "POST",
                                 {"name": "X", "platform": "ps", "price": 1000})
        self.assertEqual(status, 400)

    def test_real_mode_manual_price_and_detail(self):
        status, body = self.call(self.real_url, "/api/prices/manual", "POST",
                                 {"name": "Jugador Manual", "platform": "pc", "price": 15000})
        self.assertEqual(status, 200)
        pid = body["player_id"]
        _, detail = self.call(self.real_url, f"/api/players/{pid}")
        self.assertEqual(detail["stats"]["pc"]["current"], 15000)
        self.assertFalse(detail["stats"]["pc"]["sufficient"])  # un solo precio: no hay análisis

    def test_crud_endpoints(self):
        _, players = self.call(self.demo_url, "/api/players?limit=1")
        pid = players["items"][0]["id"]
        self.assertEqual(self.call(self.demo_url, "/api/watchlist", "POST", {"player_id": pid})[0], 200)
        _, wl = self.call(self.demo_url, "/api/watchlist")
        self.assertIn(pid, [w["player_id"] for w in wl["items"]])
        status, _ = self.call(self.demo_url, "/api/alerts/rules", "POST", {"type": "price_below", "threshold": 1})
        self.assertEqual(status, 400)
        status, rule = self.call(self.demo_url, "/api/alerts/rules", "POST",
                                 {"type": "price_below", "player_id": pid, "threshold": 10_000_000})
        self.assertEqual(status, 200)
        _, fired = self.call(self.demo_url, "/api/alerts/evaluate", "POST", {})
        self.assertTrue(any(f["rule_id"] == rule["id"] for f in fired["fired"]))
        _, t = self.call(self.demo_url, "/api/trades", "POST",
                         {"player_id": pid, "buy_price": 10000, "sell_price": 11500, "quantity": 2})
        _, trades = self.call(self.demo_url, "/api/trades")
        self.assertEqual(trades["summary"]["realized_profit"], 1850)
        status, _ = self.call(self.demo_url, "/api/events", "POST",
                              {"name": "SBC", "starts_at": time.time() + 3600, "rating_min": 85})
        self.assertEqual(status, 200)

    def test_settings_validation(self):
        status, _ = self.call(self.demo_url, "/api/settings", "PUT", {"strategy": {"risk": "yolo"}})
        self.assertEqual(status, 400)
        status, cfg = self.call(self.demo_url, "/api/settings", "PUT", {"strategy": {"budget": 50000}})
        self.assertEqual(status, 200)
        self.assertEqual(cfg["strategy"]["budget"], 50000)
        self.assertEqual(self.demo.analyzer.cfg["strategy"]["budget"], 50000)

    def test_calc_and_static(self):
        _, c = self.call(self.demo_url, "/api/calc?buy=10000&sell=11500")
        self.assertEqual(c["profit_per_unit"], 925)
        with urllib.request.urlopen(self.demo_url + "/") as r:
            self.assertIn(b"FC 27", r.read())
        status, _ = self.call(self.demo_url, "/api/nope")
        self.assertEqual(status, 404)
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(self.demo_url + "/../config.py")


if __name__ == "__main__":
    unittest.main()
