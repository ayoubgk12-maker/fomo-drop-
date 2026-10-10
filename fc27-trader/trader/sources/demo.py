"""Datos de DEMOSTRACIÓN (sintéticos).

Solo se usan con `python run.py --demo`, en una base de datos aparte
(data/demo.db). Todos los jugadores llevan el prefijo "[DEMO]" y nombres,
ligas y clubes ficticios; cada precio se guarda con is_demo=1 y el panel muestra
un aviso permanente. No representan el mercado real de FC 27.
"""

from __future__ import annotations

import math
import random
import time

from ..market import MarketRules
from .base import PriceQuote, PriceSource

POSITIONS = ["ST", "CF", "LW", "RW", "CAM", "CM", "CDM", "LM", "RM", "LB", "RB", "CB", "GK"]
LEAGUES = ["Liga Demo Norte", "Liga Demo Sur", "Liga Demo Este", "Liga Demo Oeste"]
NATIONS = ["Nación Alfa", "Nación Beta", "Nación Gamma", "Nación Delta", "Nación Épsilon"]
RARITIES = ["Oro raro", "Oro común", "Promo Demo", "Icono Demo"]
SURNAMES = ["Arrieta", "Bellamy", "Castell", "Duarte", "Esposito", "Ferraz", "Galvão", "Halvorsen",
            "Ibarra", "Jansen", "Kowal", "Lindqvist", "Moreau", "Nakamura", "Okafor", "Pereira",
            "Quintero", "Rinaldi", "Sandoval", "Tavares", "Ulloa", "Varga", "Weber", "Yilmaz",
            "Zamora", "Abreu", "Brandt", "Cuesta", "Dimitrov", "Echeverri", "Falk", "Gómez",
            "Haddad", "Ilic", "Jovanovic", "Keller"]

# Comportamientos de precio para que todas las estrategias tengan algo que analizar.
PATTERNS = ["stable", "stable", "mean_revert", "mean_revert", "uptrend", "downtrend",
            "dip", "event_spike", "volatile"]


class DemoSource(PriceSource):
    name = "demo"
    label = "Datos de demostración (sintéticos)"
    kind = "demo"
    supports_catalog = True
    supports_prices = True
    authorized_note = "Generados localmente. NO son precios reales."

    def __init__(self, seed: int = 27, n_players: int = 36, rules: MarketRules | None = None):
        self.seed = seed
        self.n_players = n_players
        self.rules = rules or MarketRules()
        self.rng = random.Random(seed)
        self.players = self._build_players()
        self.state: dict[tuple[str, str], float] = {}

    def _build_players(self):
        rng = random.Random(self.seed)
        players = []
        for i in range(self.n_players):
            rating = rng.choice([82, 83, 84, 84, 85, 85, 86, 87, 88, 89, 90, 91])
            base = int(600 * math.exp((rating - 82) * 0.42) * rng.uniform(0.7, 1.5))
            players.append({
                "id": f"demo:{i + 1}",
                "source": self.name,
                "name": f"[DEMO] {SURNAMES[i % len(SURNAMES)]}",
                "rating": rating,
                "position": POSITIONS[i % len(POSITIONS)],
                "alt_positions": [],
                "league_id": i % len(LEAGUES), "league": LEAGUES[i % len(LEAGUES)],
                "nation_id": i % len(NATIONS), "nation": NATIONS[i % len(NATIONS)],
                "club_id": i, "club": f"Club Demo {i % 9 + 1}",
                "rarity_id": i % len(RARITIES), "rarity": RARITIES[i % len(RARITIES)],
                "is_demo": True,
                "_base": max(self.rules.min_price * 2, base),
                "_pattern": PATTERNS[i % len(PATTERNS)],
            })
        return players

    def fetch_catalog(self, stop_event=None):
        return [{k: v for k, v in p.items() if not k.startswith("_")} for p in self.players]

    # ---- modelo de precios sintético -------------------------------------------
    def _target(self, p: dict, t_hours: float, platform: str) -> float:
        base = p["_base"] * (1.0 if platform == "ps" else 1.12)
        pat = p["_pattern"]
        day = t_hours / 24.0
        if pat == "uptrend":
            return base * (1 + 0.05 * day)
        if pat == "downtrend":
            return base * max(0.4, 1 - 0.04 * day)
        if pat == "event_spike":
            return base * (1 + 0.35 * math.exp(-((day - 4.5) ** 2) / 0.6))
        if pat == "dip":
            return base * (0.86 if day > 6.6 else 1.0)
        return base * (1 + 0.04 * math.sin(t_hours / 7.0))

    def _step(self, p, platform, t_hours, prev):
        target = self._target(p, t_hours, platform)
        vol = {"volatile": 0.05, "mean_revert": 0.03}.get(p["_pattern"], 0.015)
        if prev is None:
            prev = target
        value = prev + 0.35 * (target - prev) + self.rng.gauss(0, vol) * target
        if p["_pattern"] == "dip" and t_hours / 24.0 > 6.6:
            value = min(value, target * 1.01)
        return float(self.rules.round_down(max(self.rules.min_price, value)))

    def seed_history(self, db, days: float = 7.0, every_minutes: int = 15, now: float | None = None):
        """Genera historial sintético hasta `now` (solo si la base demo está vacía)."""
        if db.one("SELECT 1 FROM prices LIMIT 1"):
            return 0
        now = now or time.time()
        start = now - days * 86400
        steps = int(days * 24 * 60 / every_minutes)
        rows = []
        for p in self.players:
            for platform in ("ps", "pc"):
                prev = None
                for s in range(steps + 1):
                    t = start + s * every_minutes * 60
                    t_hours = (t - start) / 3600.0
                    prev = self._step(p, platform, t_hours, prev)
                    rows.append(self._quote(p, platform, prev, t).as_row())
                self.state[(p["id"], platform)] = prev
        self._start = start
        return db.insert_prices(rows)

    def _quote(self, p, platform, price, ts):
        base = p["_base"]
        return PriceQuote(
            player_id=p["id"], platform=platform, price=int(price), source=self.name,
            observed_at=ts, fetched_at=ts,
            min_price=self.rules.round_down(base * 0.35), max_price=self.rules.round_up(base * 3),
            verified=False, is_demo=True,
        )

    def fetch_prices(self, player_ids, stop_event=None):
        now = time.time()
        start = getattr(self, "_start", now - 7 * 86400)
        by_id = {p["id"]: p for p in self.players}
        for pid in player_ids:
            p = by_id.get(pid)
            if not p:
                continue
            for platform in ("ps", "pc"):
                prev = self.state.get((pid, platform))
                price = self._step(p, platform, (now - start) / 3600.0, prev)
                self.state[(pid, platform)] = price
                yield self._quote(p, platform, price, now)

    def restore_state(self, db):
        """Recupera el último precio de cada carta al reiniciar el modo demo."""
        first = db.one("SELECT MIN(observed_at) AS t FROM prices")
        if first and first["t"]:
            self._start = first["t"]
        for row in db.latest_prices():
            self.state[(row["player_id"], row["platform"])] = float(row["price"])
