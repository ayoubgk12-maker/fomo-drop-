"""Adaptador FUT-DB probado con un transporte simulado que reproduce las respuestas
documentadas en su especificación OpenAPI (no se hacen peticiones de red)."""

import json
import unittest

from trader.sources.base import AuthError, PriceQuote, RateLimiter, SourceError
from trader.sources.futdb import FutDBSource, parse_iso


class FakeTransport:
    def __init__(self, routes):
        self.routes = routes  # path -> lista de (status, body) que se consumen en orden
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        path = url.split("api.test", 1)[1]
        self.calls.append((method, path, headers))
        queue = self.routes.get(path)
        if not queue:
            return 404, {}, b""
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        status, payload = item[0], item[1]
        headers_out = item[2] if len(item) > 2 else {}
        return status, headers_out, json.dumps(payload).encode()


def page(items, total=1, current=1):
    return {"pagination": {"pageCurrent": current, "pageTotal": total}, "items": items}


def make_source(routes, token="secreto"):
    t = FakeTransport(routes)
    src = FutDBSource({"token": token, "base_url": "https://api.test", "catalog_max_pages": 5},
                      transport=t, limiter=RateLimiter(10_000), sleep=lambda s: None)
    return src, t


class FutDBTest(unittest.TestCase):
    def test_requires_token(self):
        src, _ = make_source({}, token="")
        ok, reason = src.availability()
        self.assertFalse(ok)
        self.assertIn("token", reason)

    def test_sends_auth_header_and_maps_catalog(self):
        routes = {
            "/api/leagues?page=1": [(200, page([{"id": 13, "name": "Premier League"}]))],
            "/api/nations?page=1": [(200, page([{"id": 18, "name": "France"}]))],
            "/api/clubs?page=1": [(200, page([{"id": 243, "name": "Real Madrid"}]))],
            "/api/rarities?page=1": [(200, page([{"id": 1, "name": "Rare"}]))],
            "/api/players?page=1": [(200, page([{
                "id": 501, "commonName": "Mbappé", "rating": 91, "position": "ST",
                "positionAlternatives": ["LW"], "league": 13, "nation": 18, "club": 243, "rarity": 1,
                "futBinId": 777}], total=2))],
            "/api/players?page=2": [(200, page([{"id": 502, "firstName": "Ana", "lastName": "Pérez",
                                                 "rating": 84}], total=2, current=2))],
        }
        src, t = make_source(routes)
        players = src.fetch_catalog()
        self.assertEqual([p["id"] for p in players], ["futdb:501", "futdb:502"])
        p = players[0]
        self.assertEqual((p["name"], p["league"], p["nation"], p["club"], p["rarity"]),
                         ("Mbappé", "Premier League", "France", "Real Madrid", "Rare"))
        self.assertEqual(p["external_ids"], {"futBinId": 777})
        self.assertEqual(players[1]["name"], "Ana Pérez")
        self.assertTrue(all(h["X-AUTH-TOKEN"] == "secreto" for _, _, h in t.calls))

    def test_maps_prices_for_both_platforms(self):
        routes = {"/api/players/501/price": [(200, {
            "playstation": {"price": 250000, "minPrice": 100000, "maxPrice": 900000,
                            "priceUpdate": "2026-10-10T05:00:00Z"},
            "pc": {"price": 280000, "minPrice": 100000, "maxPrice": 900000, "priceUpdate": None},
        })]}
        src, _ = make_source(routes)
        quotes = list(src.fetch_prices(["futdb:501"]))
        self.assertEqual(len(quotes), 2)
        ps = next(q for q in quotes if q.platform == "ps")
        self.assertIsInstance(ps, PriceQuote)
        self.assertEqual((ps.price, ps.min_price, ps.max_price), (250000, 100000, 900000))
        self.assertEqual(ps.observed_at, parse_iso("2026-10-10T05:00:00Z"))
        self.assertTrue(ps.verified)
        pc = next(q for q in quotes if q.platform == "pc")
        self.assertFalse(pc.verified)  # sin hora de la fuente: no se presenta como verificada

    def test_null_price_is_skipped(self):
        routes = {"/api/players/9/price": [(200, {"playstation": {"price": None}, "pc": {"price": 0}})]}
        src, _ = make_source(routes)
        self.assertEqual(list(src.fetch_prices(["futdb:9"])), [])

    def test_auth_error_stops_batch(self):
        routes = {"/api/players/1/price": [(403, {})], "/api/players/2/price": [(200, {})]}
        src, t = make_source(routes)
        out = list(src.fetch_prices(["futdb:1", "futdb:2"]))
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], AuthError)
        self.assertTrue(src.prices_forbidden)
        self.assertEqual(len(t.calls), 1)

    def test_retries_server_errors_then_succeeds(self):
        routes = {"/api/players/1/price": [(503, {}), (502, {}),
                                           (200, {"playstation": {"price": 1000}, "pc": {}})]}
        src, t = make_source(routes)
        out = list(src.fetch_prices(["futdb:1"]))
        self.assertEqual(len(out), 1)
        self.assertEqual(len(t.calls), 3)

    def test_rate_limit_retry(self):
        routes = {"/api/players/1/price": [(429, {}, {"Retry-After": "0"}),
                                           (200, {"playstation": {"price": 1000}, "pc": {}})]}
        src, _ = make_source(routes)
        out = list(src.fetch_prices(["futdb:1"]))
        self.assertIsInstance(out[0], PriceQuote)

    def test_network_error_after_retries(self):
        routes = {"/api/players/1/price": [SourceError("timeout")]}
        src, t = make_source(routes)
        out = list(src.fetch_prices(["futdb:1"]))
        self.assertIsInstance(out[0], SourceError)
        self.assertEqual(len(t.calls), 4)  # 1 intento + 3 reintentos


class RateLimiterTest(unittest.TestCase):
    def test_blocks_when_empty(self):
        clock = [0.0]
        slept = []

        def sleep(s):
            slept.append(s)
            clock[0] += s

        rl = RateLimiter(2, clock=lambda: clock[0], sleep=sleep)
        rl.acquire(); rl.acquire()
        self.assertEqual(slept, [])
        rl.acquire()
        self.assertGreater(sum(slept), 25)  # 2/min → ~30 s por ficha


if __name__ == "__main__":
    unittest.main()
