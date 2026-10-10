"""Fuentes revisadas que NO se consultan, con el motivo comprobado.

Se registran igualmente para que el panel muestre por qué no hay datos de ellas
y para que, si algún día ofrecen acceso autorizado (API con licencia, exportación
oficial), baste con implementar fetch_prices() aquí.
"""

from __future__ import annotations

from .base import PriceSource


class UnavailableSource(PriceSource):
    kind = "unavailable"
    reason = ""

    def availability(self):
        return False, self.reason

    def fetch_catalog(self, stop_event=None):
        return []

    def fetch_prices(self, player_ids, stop_event=None):
        return []


class FutbinSource(UnavailableSource):
    name = "futbin"
    label = "FUTBIN"
    url = "https://www.futbin.com"
    reason = ("Sin API pública. La web responde con un desafío de Cloudflare (HTTP 403) a los "
              "clientes automatizados; consultarla exigiría eludir esa protección, así que no se usa. "
              "Puedes anotar a mano los precios que veas o importar un CSV propio.")


class FutGGSource(UnavailableSource):
    name = "futgg"
    label = "FUT.GG"
    url = "https://www.fut.gg"
    reason = ("Sus Términos de Servicio (Stormstrike Inc.) prohíben el acceso mediante bots, "
              "scrapers o crawlers salvo permiso expreso, y robots.txt bloquea /api/*. "
              "No se consulta automáticamente. Úsala manualmente y registra los precios en la app.")
