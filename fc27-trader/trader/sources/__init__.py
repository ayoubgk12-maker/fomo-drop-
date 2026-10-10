"""Registro de fuentes de precios."""

from __future__ import annotations

from ..market import MarketRules
from .base import PLATFORM_LABELS, PLATFORMS, AuthError, PriceQuote, PriceSource, RateLimiter, RateLimitError, SourceError
from .demo import DemoSource
from .futdb import FutDBSource
from .manual import ManualSource
from .unavailable import FutbinSource, FutGGSource


def build_sources(cfg: dict, demo: bool = False) -> list[PriceSource]:
    """Fuentes activas según el modo. En modo demo no se consulta ninguna fuente real,
    para que datos reales y sintéticos nunca acaben en la misma base de datos."""
    if demo:
        return [DemoSource(rules=MarketRules.from_config(cfg["market"])), FutbinSource(), FutGGSource()]
    src_cfg = cfg.get("sources", {})
    return [
        FutDBSource(src_cfg.get("futdb", {})),
        ManualSource(src_cfg.get("manual", {})),
        FutbinSource(),
        FutGGSource(),
    ]


__all__ = [
    "AuthError", "DemoSource", "FutDBSource", "FutbinSource", "FutGGSource", "ManualSource",
    "PLATFORMS", "PLATFORM_LABELS", "PriceQuote", "PriceSource", "RateLimitError", "RateLimiter",
    "SourceError", "build_sources",
]
