"""Carga de configuración: valores por defecto + config.json + variables de entorno."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "server": {"host": "127.0.0.1", "port": 8027},
    "database": "data/trader.db",
    "demo_database": "data/demo.db",
    "update_interval_minutes": 15,
    "catalog_refresh_hours": 24,
    "sources": {
        "futdb": {
            "enabled": True,
            "token": "",
            "base_url": "https://api.futdatabase.com",
            "max_requests_per_minute": 30,
            "catalog_max_pages": 60,
            "timeout_seconds": 20,
        },
        "manual": {"enabled": True},
    },
    "tracking": {
        # Jugadores a los que se les consulta el precio en cada ciclo (además de la
        # lista de seguimiento). La API cobra/limita una petición por jugador.
        "max_tracked_players": 150,
        "min_rating": 84,
        "include_watchlist": True,
    },
    "market": {
        "tax_rate": 0.05,
        "min_price": 150,
        "tiers": [[1000, 50], [10000, 100], [50000, 250], [100000, 500], [None, 1000]],
    },
    "analysis": {
        "window_hours": 72,
        "short_window_hours": 6,
        "probability_lookback_hours": 336,
        "probability_horizon_hours": 24,
        "min_samples": 12,
        "min_span_hours": 6,
        "min_episodes": 5,
        "stale_after_minutes": 60,
        "exclude_after_hours": 24,
        "dip_pct": 8.0,
        "undervalued_pct": 7.0,
        "trend_min_pct_per_day": 3.0,
        "platform_gap_pct": 10.0,
    },
    "strategy": {
        "budget": 100000,
        "risk": "medium",  # low | medium | high
        "time": "medium",  # short | medium | long
        "enabled": ["flip", "dip", "trend", "pre_event", "liquidity"],
        "min_profit": 300,
        "min_margin_pct": 3.0,
        "max_results": 50,
    },
    "alerts": {"cooldown_minutes": 60},
}

# Claves que el usuario puede cambiar desde el panel (se guardan en la base de datos).
RUNTIME_EDITABLE = ("strategy", "analysis", "tracking", "update_interval_minutes")


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(path: str | os.PathLike | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    path = Path(path) if path else ROOT / "config.json"
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            cfg = deep_merge(cfg, json.load(fh))
    token = os.environ.get("FUTDB_TOKEN")
    if token:
        cfg["sources"]["futdb"]["token"] = token.strip()
    return cfg


def resolve_path(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else ROOT / path


def public_view(cfg: dict) -> dict:
    """Configuración sin secretos, para mostrar en el panel."""
    view = copy.deepcopy(cfg)
    token = view.get("sources", {}).get("futdb", {}).get("token")
    view["sources"]["futdb"]["token"] = "configurado" if token else ""
    return view
