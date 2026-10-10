"""Adaptador de la API REST oficial de FUT-DB (https://api.futdatabase.com).

Comprobado contra su especificación OpenAPI (versión "27"):
  * Autenticación: cabecera X-AUTH-TOKEN (cuenta en futdatabase.com).
  * Catálogo (/api/players, /api/leagues, /api/nations, /api/clubs, /api/rarities): plan gratuito.
  * Precio actual (/api/players/{id}/price): solo plan premium. Devuelve consola
    ("playstation") y PC con price, minPrice, maxPrice, prp y priceUpdate.
  * No hay endpoint de historial: el historial se construye guardando cada consulta.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime

from .base import AuthError, PriceQuote, PriceSource, RateLimiter, RateLimitError, SourceError

USER_AGENT = "fc27-trader/1.0 (+analisis personal, solo lectura)"
PLATFORM_MAP = {"playstation": "ps", "pc": "pc"}


def parse_iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        v = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            from datetime import timezone

            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None, timeout: float):
    """Transporte HTTP por defecto. Devuelve (status, headers, cuerpo en bytes)."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read() if exc.fp else b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceError(f"Error de red: {exc}") from exc


class FutDBSource(PriceSource):
    name = "futdb"
    label = "FUT-DB API"
    kind = "api"
    url = "https://www.futdatabase.com"
    supports_catalog = True
    supports_prices = True
    authorized_note = ("API REST pública y documentada con token propio. "
                       "Los precios requieren plan premium.")

    def __init__(self, cfg: dict, transport=urllib_transport, limiter: RateLimiter | None = None,
                 sleep=time.sleep):
        self.cfg = cfg
        self.base_url = cfg.get("base_url", "https://api.futdatabase.com").rstrip("/")
        self.token = (cfg.get("token") or "").strip()
        self.timeout = float(cfg.get("timeout_seconds", 20))
        self.transport = transport
        self.limiter = limiter or RateLimiter(cfg.get("max_requests_per_minute", 30))
        self.sleep = sleep
        self.requests_made = 0
        self.prices_forbidden = False  # se activa si el plan no incluye precios

    def availability(self):
        if not self.cfg.get("enabled", True):
            return False, "Desactivada en la configuración."
        if not self.token:
            return False, ("Falta el token. Crea una cuenta en futdatabase.com y ponlo en "
                           "config.json (sources.futdb.token) o en la variable FUTDB_TOKEN.")
        return True, ""

    # ---- HTTP -------------------------------------------------------------------
    def _request(self, method: str, path: str, body=None, stop_event=None, retries: int = 3):
        url = f"{self.base_url}{path}"
        headers = {"X-AUTH-TOKEN": self.token, "Accept": "application/json",
                   "User-Agent": USER_AGENT}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        delay = 2.0
        for attempt in range(retries + 1):
            if not self.limiter.acquire(stop_event):
                raise SourceError("Actualización cancelada")
            self.requests_made += 1
            try:
                status, resp_headers, raw = self.transport(method, url, headers, data, self.timeout)
            except SourceError:
                if attempt >= retries:
                    raise
                self.sleep(delay)
                delay *= 2
                continue
            if status == 200:
                try:
                    return json.loads(raw.decode("utf-8") or "null")
                except ValueError as exc:
                    raise SourceError(f"Respuesta no JSON en {path}") from exc
            if status in (401, 403):
                raise AuthError(f"HTTP {status} en {path}: token inválido o el plan no incluye este endpoint.")
            if status == 404:
                return None
            if status == 429:
                retry_after = _retry_after(resp_headers)
                self.limiter.block_for(60 if retry_after is None else retry_after)
                if attempt >= retries:
                    raise RateLimitError(f"Límite de peticiones alcanzado en {path}", retry_after)
                continue
            if 500 <= status < 600 and attempt < retries:
                self.sleep(delay)
                delay *= 2
                continue
            raise SourceError(f"HTTP {status} en {path}")
        raise SourceError(f"Sin respuesta válida en {path}")

    def _paged(self, path: str, max_pages: int, stop_event=None):
        page = 1
        while page <= max_pages:
            if stop_event is not None and stop_event.is_set():
                return
            data = self._request("GET", f"{path}?page={page}", stop_event=stop_event)
            if not data:
                return
            for item in data.get("items") or []:
                yield item
            pag = data.get("pagination") or {}
            if page >= int(pag.get("pageTotal") or 0):
                return
            page += 1

    # ---- catálogo ---------------------------------------------------------------
    def fetch_catalog(self, stop_event=None):
        max_pages = int(self.cfg.get("catalog_max_pages", 60))
        names = {}
        for kind in ("leagues", "nations", "clubs", "rarities"):
            names[kind] = {int(i["id"]): i.get("name") for i in self._paged(f"/api/{kind}", 200, stop_event)}
        players = []
        for item in self._paged("/api/players", max_pages, stop_event):
            players.append(self.map_player(item, names))
        return players

    def map_player(self, item: dict, names: dict) -> dict:
        def name_of(kind, key):
            val = item.get(key)
            return names.get(kind, {}).get(int(val)) if val is not None else None

        display = item.get("commonName") or item.get("name") or \
            " ".join(x for x in (item.get("firstName"), item.get("lastName")) if x) or f"#{item['id']}"
        return {
            "id": f"futdb:{item['id']}",
            "source": self.name,
            "name": display,
            "rating": item.get("rating"),
            "position": item.get("position"),
            "alt_positions": item.get("positionAlternatives") or [],
            "league_id": item.get("league"), "league": name_of("leagues", "league"),
            "nation_id": item.get("nation"), "nation": name_of("nations", "nation"),
            "club_id": item.get("club"), "club": name_of("clubs", "club"),
            "rarity_id": item.get("rarity"), "rarity": name_of("rarities", "rarity"),
            "external_ids": {k: item.get(k) for k in ("futBinId", "futWizId", "resourceId")
                             if item.get(k)},
        }

    # ---- precios ----------------------------------------------------------------
    def fetch_prices(self, player_ids, stop_event=None):
        for pid in player_ids:
            if stop_event is not None and stop_event.is_set():
                return
            native = pid.split(":", 1)[1]
            try:
                data = self._request("GET", f"/api/players/{native}/price", stop_event=stop_event)
            except AuthError as exc:
                self.prices_forbidden = True
                yield exc
                return  # sin permiso no tiene sentido seguir pidiendo
            except SourceError as exc:
                yield exc
                continue
            if not data:
                continue
            for key, platform in PLATFORM_MAP.items():
                p = data.get(key) or {}
                if not p.get("price"):
                    continue  # sin precio (carta no comerciable o sin datos)
                yield PriceQuote(
                    player_id=pid,
                    platform=platform,
                    price=int(p["price"]),
                    min_price=p.get("minPrice"),
                    max_price=p.get("maxPrice"),
                    source=self.name,
                    observed_at=parse_iso(p.get("priceUpdate")) or time.time(),
                    verified=parse_iso(p.get("priceUpdate")) is not None,
                )


def _retry_after(headers: dict) -> float | None:
    for k, v in (headers or {}).items():
        if k.lower() == "retry-after":
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    return None
