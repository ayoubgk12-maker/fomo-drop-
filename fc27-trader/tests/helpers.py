import copy

from trader.config import DEFAULTS
from trader.db import Database

NOW = 1_800_000_000.0  # instante fijo para que las pruebas sean deterministas


def make_cfg(**overrides):
    cfg = copy.deepcopy(DEFAULTS)
    for section, values in overrides.items():
        if isinstance(values, dict):
            cfg[section].update(values)
        else:
            cfg[section] = values
    return cfg


def make_db(players=None):
    db = Database(":memory:")
    db.upsert_players(players or [{"id": "t:1", "source": "t", "name": "Jugador Uno", "rating": 85,
                                   "position": "ST"}])
    return db


def add_series(db, pid, prices, platform="ps", every_min=15, end=NOW, source="t", min_price=None,
               max_price=None):
    """Inserta una serie que termina en `end`, un precio cada `every_min` minutos."""
    n = len(prices)
    rows = []
    for i, price in enumerate(prices):
        ts = end - (n - 1 - i) * every_min * 60
        rows.append({"player_id": pid, "platform": platform, "price": price, "source": source,
                     "observed_at": ts, "fetched_at": ts, "min_price": min_price, "max_price": max_price})
    db.insert_prices(rows)
