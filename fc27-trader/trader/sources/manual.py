"""Entrada manual de precios e importación CSV.

Es la vía permitida para incorporar precios que tú mismo ves en el juego, en la
app web de EA o en webs que no admiten acceso automatizado. Cada precio queda
marcado con la fuente "manual" (o la que indiques en el CSV) para que el panel
no lo confunda con una consulta automática.
"""

from __future__ import annotations

import csv
import io
import re
import time
import unicodedata

from .base import PLATFORMS, PriceSource
from .futdb import parse_iso

PLATFORM_ALIASES = {
    "ps": "ps", "ps4": "ps", "ps5": "ps", "playstation": "ps", "console": "ps", "consola": "ps",
    "xbox": "ps", "xb": "ps", "pc": "pc",
}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "jugador"


def normalize_platform(value: str) -> str:
    p = PLATFORM_ALIASES.get((value or "").strip().lower())
    if p not in PLATFORMS:
        raise ValueError(f"Plataforma no reconocida: {value!r} (usa ps o pc)")
    return p


class ManualSource(PriceSource):
    name = "manual"
    label = "Entrada manual / CSV"
    kind = "manual"
    supports_prices = True
    authorized_note = "Precios introducidos por ti. Se muestran como 'introducido por el usuario'."

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    def availability(self):
        if not self.cfg.get("enabled", True):
            return False, "Desactivada en la configuración."
        return True, ""

    def fetch_prices(self, player_ids, stop_event=None):
        return []  # no consulta nada: los datos entran por el panel o por CSV


def build_manual_quote(db, *, player_id=None, name=None, platform, price, observed_at=None,
                       min_price=None, max_price=None, source_label="manual", rating=None,
                       position=None):
    """Valida una entrada manual y la convierte en fila de precio (creando el jugador si hace falta)."""
    platform = normalize_platform(platform)
    price = int(float(price))
    if price <= 0:
        raise ValueError("El precio debe ser positivo")
    if player_id:
        if not db.get_player(player_id):
            raise ValueError(f"Jugador desconocido: {player_id}")
    else:
        if not name:
            raise ValueError("Indica player_id o name")
        match = db.one("SELECT id FROM players WHERE lower(name)=lower(?) ORDER BY is_demo LIMIT 1", (name,))
        if match:
            player_id = match["id"]
        else:
            player_id = f"manual:{slugify(name)}"
            db.upsert_players([{
                "id": player_id, "source": "manual", "name": name,
                "rating": int(rating) if rating not in (None, "") else None,
                "position": position or None,
            }])
    ts = observed_at
    if isinstance(ts, str):
        ts = parse_iso(ts)
    return {
        "player_id": player_id,
        "platform": platform,
        "price": price,
        "min_price": int(min_price) if min_price not in (None, "") else None,
        "max_price": int(max_price) if max_price not in (None, "") else None,
        "source": f"manual:{slugify(source_label)}" if source_label != "manual" else "manual",
        "observed_at": float(ts) if ts else time.time(),
        "verified": True,
        "is_demo": False,
    }


def import_csv(db, text: str) -> dict:
    """Columnas: player_id o name, platform, price; opcionales: observed_at (ISO 8601),
    min_price, max_price, source, rating, position."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise ValueError("CSV vacío")
    fields = {f.strip().lower() for f in reader.fieldnames}
    if "price" not in fields or "platform" not in fields or not ({"player_id", "name"} & fields):
        raise ValueError("Faltan columnas: se necesitan price, platform y player_id o name")
    rows, errors = [], []
    for i, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        try:
            rows.append(build_manual_quote(
                db,
                player_id=row.get("player_id") or None,
                name=row.get("name") or None,
                platform=row.get("platform", ""),
                price=row.get("price", ""),
                observed_at=row.get("observed_at") or None,
                min_price=row.get("min_price"),
                max_price=row.get("max_price"),
                source_label=row.get("source") or "manual",
                rating=row.get("rating"),
                position=row.get("position"),
            ))
        except (ValueError, TypeError) as exc:
            errors.append(f"Fila {i}: {exc}")
    saved = db.insert_prices(rows)
    return {"saved": saved, "rows": len(rows), "errors": errors}
