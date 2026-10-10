"""Reglas del mercado de transferencias de Ultimate Team.

Los valores por defecto (impuesto del 5 %, tramos de incremento de precio y precio
mínimo) son las reglas conocidas del mercado de FUT. Son configurables porque EA
puede cambiarlas entre ediciones: compruébalas en el juego al empezar FC 27.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_TAX_RATE = 0.05
DEFAULT_MIN_PRICE = 150
# (límite superior exclusivo del tramo, incremento). None = sin límite.
DEFAULT_TIERS = [(1000, 50), (10000, 100), (50000, 250), (100000, 500), (None, 1000)]


@dataclass
class MarketRules:
    tax_rate: float = DEFAULT_TAX_RATE
    min_price: int = DEFAULT_MIN_PRICE
    tiers: list = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.tiers is None:
            self.tiers = list(DEFAULT_TIERS)
        self.tiers = [(None if lim is None else int(lim), int(step)) for lim, step in self.tiers]

    @classmethod
    def from_config(cls, cfg: dict) -> "MarketRules":
        return cls(
            tax_rate=float(cfg.get("tax_rate", DEFAULT_TAX_RATE)),
            min_price=int(cfg.get("min_price", DEFAULT_MIN_PRICE)),
            tiers=cfg.get("tiers") or list(DEFAULT_TIERS),
        )

    # ---- incrementos de precio -------------------------------------------------
    def step(self, price: float) -> int:
        """Incremento válido para un precio dado (el del tramo en el que cae)."""
        for limit, step in self.tiers:
            if limit is None or price < limit:
                return step
        return self.tiers[-1][1]

    def round_down(self, price: float) -> int:
        """Mayor precio válido <= price."""
        if price < self.min_price:
            return self.min_price
        step = self.step(price)
        return max(self.min_price, int(math.floor(price / step) * step))

    def round_up(self, price: float) -> int:
        """Menor precio válido >= price."""
        if price <= self.min_price:
            return self.min_price
        step = self.step(price)
        value = int(math.ceil(price / step) * step)
        # Si al subir cruzamos a otro tramo, el valor sigue siendo válido en ese tramo
        # porque los límites de tramo son múltiplos del incremento siguiente.
        return value

    def next_price(self, price: int) -> int:
        return self.round_down(price) + self.step(price)

    # ---- impuesto y beneficio --------------------------------------------------
    def net_after_tax(self, sell_price: float) -> int:
        """Monedas recibidas al vender. Se redondea hacia abajo (criterio conservador)."""
        return int(math.floor(sell_price * (1.0 - self.tax_rate)))

    def tax(self, sell_price: float) -> int:
        return int(sell_price) - self.net_after_tax(sell_price)

    def breakeven_sell(self, buy_price: float) -> int:
        """Precio de venta válido más bajo que no da pérdidas tras el impuesto."""
        candidate = self.round_up(buy_price / (1.0 - self.tax_rate))
        while self.net_after_tax(candidate) < buy_price:
            candidate = self.next_price(candidate)
        return candidate

    def profit(self, buy_price: float, sell_price: float, quantity: int = 1) -> dict:
        net = self.net_after_tax(sell_price)
        unit_profit = net - int(buy_price)
        margin = (unit_profit / buy_price * 100.0) if buy_price else 0.0
        return {
            "buy_price": int(buy_price),
            "sell_price": int(sell_price),
            "tax": self.tax(sell_price),
            "net_sell": net,
            "profit_per_unit": unit_profit,
            "margin_pct": round(margin, 2),
            "quantity": quantity,
            "capital": int(buy_price) * quantity,
            "total_profit": unit_profit * quantity,
            "breakeven_sell": self.breakeven_sell(buy_price) if buy_price else None,
        }

    def clamp_to_range(self, price: int, min_price: int | None, max_price: int | None) -> int:
        """Ajusta un precio al rango de precios permitido por EA para la carta (si se conoce)."""
        if min_price:
            price = max(price, int(min_price))
        if max_price:
            price = min(price, int(max_price))
        return self.round_down(price)
