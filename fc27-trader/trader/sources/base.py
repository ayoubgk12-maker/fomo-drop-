"""Interfaz común de fuentes de precios.

Para añadir una fuente nueva: crea una subclase de PriceSource, implementa
fetch_catalog() y/o fetch_prices(), y regístrala en sources/__init__.py.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

PLATFORMS = ("ps", "pc")
PLATFORM_LABELS = {"ps": "Consola (PlayStation/Xbox)", "pc": "PC"}


class SourceError(Exception):
    """Error recuperable (red, 5xx, respuesta inesperada)."""


class AuthError(SourceError):
    """Token ausente o inválido, o endpoint que requiere un plan superior."""


class RateLimitError(SourceError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class PriceQuote:
    player_id: str
    platform: str
    price: int
    source: str
    observed_at: float
    min_price: int | None = None
    max_price: int | None = None
    verified: bool = True
    is_demo: bool = False
    fetched_at: float = field(default_factory=time.time)

    def as_row(self) -> dict:
        return self.__dict__.copy()


class RateLimiter:
    """Cubo de fichas: como máximo `per_minute` peticiones por minuto."""

    def __init__(self, per_minute: float, clock=time.monotonic, sleep=time.sleep):
        self.capacity = max(1.0, float(per_minute))
        self.rate = self.capacity / 60.0
        self.tokens = self.capacity
        self.clock = clock
        self.sleep = sleep
        self.last = clock()
        self.lock = threading.Lock()
        self.blocked_until = 0.0

    def block_for(self, seconds: float) -> None:
        with self.lock:
            self.blocked_until = max(self.blocked_until, self.clock() + seconds)
            self.tokens = 0

    def acquire(self, stop_event: threading.Event | None = None) -> bool:
        while True:
            with self.lock:
                now = self.clock()
                self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
                self.last = now
                if now >= self.blocked_until and self.tokens >= 1:
                    self.tokens -= 1
                    return True
                wait = max(self.blocked_until - now, (1 - self.tokens) / self.rate)
            if stop_event is not None and stop_event.is_set():
                return False
            self.sleep(min(wait, 1.0))


class PriceSource:
    name = "base"
    label = "Fuente"
    kind = "api"  # api | manual | demo | unavailable
    url = ""
    supports_catalog = False
    supports_prices = False
    authorized_note = ""

    def availability(self) -> tuple[bool, str]:
        """(disponible, motivo). Si no está disponible, el actualizador no la usa."""
        return True, ""

    def describe(self) -> dict:
        ok, reason = self.availability()
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "url": self.url,
            "available": ok,
            "reason": reason,
            "supports_catalog": self.supports_catalog,
            "supports_prices": self.supports_prices,
            "authorized_note": self.authorized_note,
        }

    def fetch_catalog(self, stop_event=None):  # pragma: no cover - interfaz
        return []

    def fetch_prices(self, player_ids: list[str], stop_event=None):  # pragma: no cover
        """Devuelve un iterable de PriceQuote o de excepciones SourceError por jugador."""
        return []

    def owns(self, player_id: str) -> bool:
        return player_id.startswith(self.name + ":")
