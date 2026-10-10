"""Actualización periódica de precios con límites de peticiones y cortacircuitos.

Por cada fuente disponible:
  1. Sincroniza el catálogo si toca (catalog_refresh_hours).
  2. Elige qué jugadores consultar (lista de seguimiento + filtros de seguimiento),
     rotando para repartir las peticiones entre ciclos.
  3. Guarda los precios con su fuente y hora.
  4. Si una fuente falla varias veces seguidas, se "abre el circuito": se deja de
     consultar con espera exponencial (máx. 6 h). Un error de autenticación la
     detiene hasta que cambies el token y reinicies.
Tras cada ciclo se evalúan las alertas.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback

from .sources.base import AuthError, PriceQuote, RateLimitError, SourceError

log = logging.getLogger("fc27.updater")
MAX_BACKOFF = 6 * 3600


class Updater:
    def __init__(self, db, cfg: dict, sources: list, alert_engine=None):
        self.db = db
        self.cfg = cfg
        self.sources = sources
        self.alert_engine = alert_engine
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.run_lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.last_run: dict | None = None
        self._cursor: dict[str, int] = {}
        # Al arrancar se da otra oportunidad a las fuentes detenidas: el usuario puede
        # haber cambiado el token o el plan desde la última ejecución.
        for src in sources:
            st = db.get_source_status(src.name)
            if st["state"] in ("auth_error", "circuit_open"):
                db.update_source_status(src.name, state="pending", consecutive_failures=0,
                                        next_attempt_at=None)

    # ---- ciclo de vida ---------------------------------------------------------------
    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, name="updater", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()

    def trigger(self) -> None:
        self.wake_event.set()

    @property
    def interval_seconds(self) -> float:
        return max(1.0, float(self.cfg["update_interval_minutes"])) * 60

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - el hilo nunca debe morir
                log.error("Fallo inesperado en la actualización:\n%s", traceback.format_exc())
            self.wake_event.wait(self.interval_seconds)
            self.wake_event.clear()

    # ---- un ciclo --------------------------------------------------------------------
    def run_once(self, now: float | None = None) -> dict:
        if not self.run_lock.acquire(blocking=False):
            return {"skipped": "actualización ya en curso"}
        try:
            summary = {"started_at": time.time(), "sources": {}}
            for src in self.sources:
                summary["sources"][src.name] = self._run_source(src, now)
            if self.alert_engine:
                try:
                    summary["alerts_fired"] = len(self.alert_engine.evaluate())
                except Exception as exc:  # noqa: BLE001
                    summary["alerts_error"] = str(exc)
            summary["finished_at"] = time.time()
            self.last_run = summary
            return summary
        finally:
            self.run_lock.release()

    def _run_source(self, src, now=None) -> dict:
        now = now or time.time()
        ok, reason = src.availability()
        status = self.db.get_source_status(src.name)
        if not ok:
            state = "unavailable" if src.kind == "unavailable" else "not_configured"
            self.db.update_source_status(src.name, state=state, detail=reason)
            return {"state": state, "detail": reason}
        if src.kind == "manual":
            self.db.update_source_status(src.name, state="ok", detail="Entrada manual / CSV disponible")
            return {"state": "ok"}
        if status["state"] == "auth_error":
            return {"state": "auth_error", "detail": status["last_error"]}
        if status["next_attempt_at"] and now < status["next_attempt_at"]:
            return {"state": status["state"], "detail": "En espera tras errores (circuito abierto)"}

        run = {"state": "ok", "prices_saved": 0, "errors": 0, "catalog": None}
        started = time.time()
        self.db.update_source_status(src.name, last_attempt=started)
        try:
            if src.supports_catalog and self._catalog_due(status, now):
                players = list(src.fetch_catalog(self.stop_event))
                n = self.db.upsert_players(players)
                run["catalog"] = n
                self.db.update_source_status(src.name, catalog_synced_at=time.time())
                if hasattr(src, "seed_history"):
                    src.seed_history(self.db)
            if src.supports_prices:
                ids = self.select_players(src)
                quotes, errors = [], []
                for item in src.fetch_prices(ids, self.stop_event):
                    if isinstance(item, PriceQuote):
                        quotes.append(item.as_row())
                    elif isinstance(item, Exception):
                        errors.append(item)
                run["requested"] = len(ids)
                run["prices_saved"] = self.db.insert_prices(quotes)
                run["errors"] = len(errors)
                auth = next((e for e in errors if isinstance(e, AuthError)), None)
                if auth:
                    raise auth
                if errors and not quotes:
                    raise errors[0]
                if errors:
                    run["state"] = "partial"
                    run["detail"] = f"{len(errors)} errores; último: {errors[-1]}"
            fields = dict(state=run["state"], last_success=time.time(), consecutive_failures=0,
                          next_attempt_at=None,
                          detail=run.get("detail") or f"{run['prices_saved']} precios guardados")
            if hasattr(src, "requests_made"):
                fields["requests_made"] = src.requests_made
            self.db.update_source_status(src.name, **fields)
        except AuthError as exc:
            run.update(state="auth_error", detail=str(exc))
            self.db.update_source_status(
                src.name, state="auth_error", last_error=str(exc), last_error_at=time.time(),
                detail="Revisa el token o el plan de la API (los precios de FUT-DB son premium).")
        except (SourceError, OSError, ValueError) as exc:
            fails = (status["consecutive_failures"] or 0) + 1
            backoff = min(self.interval_seconds * (2 ** (fails - 1)), MAX_BACKOFF)
            if isinstance(exc, RateLimitError) and exc.retry_after:
                backoff = max(backoff, exc.retry_after)
            state = "circuit_open" if fails >= 3 else "error"
            run.update(state=state, detail=str(exc))
            self.db.update_source_status(
                src.name, state=state, last_error=str(exc), last_error_at=time.time(),
                consecutive_failures=fails,
                next_attempt_at=time.time() + backoff if fails >= 3 else None)
        self.db.execute(
            "INSERT INTO update_runs(source, started_at, finished_at, prices_saved, errors, detail) "
            "VALUES(?,?,?,?,?,?)",
            (src.name, started, time.time(), run.get("prices_saved", 0), run.get("errors", 0),
             run.get("detail")))
        return run

    def _catalog_due(self, status, now) -> bool:
        synced = status.get("catalog_synced_at")
        return not synced or now - synced >= self.cfg["catalog_refresh_hours"] * 3600

    def select_players(self, src) -> list[str]:
        """Lista de seguimiento primero; después jugadores por valoración, rotando."""
        tcfg = self.cfg["tracking"]
        limit = int(tcfg["max_tracked_players"])
        prefix = src.name + ":%"
        chosen: list[str] = []
        if tcfg.get("include_watchlist", True):
            chosen = [r["player_id"] for r in self.db.query(
                "SELECT player_id FROM watchlist WHERE player_id LIKE ?", (prefix,))]
        pool = [r["id"] for r in self.db.query(
            "SELECT id FROM players WHERE id LIKE ? AND COALESCE(rating, 0) >= ? "
            "ORDER BY rating DESC, id", (prefix, int(tcfg["min_rating"])))]
        pool = [p for p in pool if p not in set(chosen)]
        room = max(0, limit - len(chosen))
        if pool and room:
            start = self._cursor.get(src.name, 0) % len(pool)
            rotated = pool[start:] + pool[:start]
            picked = rotated[:room]
            self._cursor[src.name] = start + len(picked)
            chosen += picked
        return chosen[:max(limit, len(chosen))]
