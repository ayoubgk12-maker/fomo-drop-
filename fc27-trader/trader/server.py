"""Servidor HTTP local: API JSON + panel web (biblioteca estándar)."""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .alerts import ALERT_TYPES, AlertEngine, validate_rule
from .analysis import RISK_PROFILES, STRATEGIES, TIME_PROFILES, Analyzer
from .config import RUNTIME_EDITABLE, deep_merge, public_view, resolve_path
from .db import Database
from .market import MarketRules
from .sources import PLATFORM_LABELS, build_sources
from .sources.manual import build_manual_quote, import_csv
from .updater import Updater

log = logging.getLogger("fc27.server")
STATIC = Path(__file__).resolve().parent / "static"


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class App:
    """Une base de datos, fuentes, motor de análisis, alertas y actualizador."""

    def __init__(self, cfg: dict, demo: bool = False, db_path: str | None = None):
        self.base_cfg = cfg
        self.demo = demo
        path = db_path or resolve_path(cfg["demo_database"] if demo else cfg["database"])
        self.db = Database(path)
        self.cfg = cfg
        self._apply_runtime_settings()
        if demo:
            self.cfg = deep_merge(self.cfg, {"tracking": {"min_rating": 0}})
        self.rules = MarketRules.from_config(self.cfg["market"])
        self.sources = build_sources(self.cfg, demo=demo)
        self.analyzer = Analyzer(self.db, self.cfg, self.rules)
        self.alerts = AlertEngine(self.db, self.analyzer, self.cfg)
        self.updater = Updater(self.db, self.cfg, self.sources, self.alerts)
        if demo:
            for s in self.sources:
                if hasattr(s, "restore_state"):
                    s.restore_state(self.db)

    def _apply_runtime_settings(self):
        saved = self.db.get_setting("runtime", {}) or {}
        self.cfg = deep_merge(self.base_cfg, {k: v for k, v in saved.items() if k in RUNTIME_EDITABLE})

    def update_settings(self, patch: dict) -> dict:
        patch = {k: v for k, v in (patch or {}).items() if k in RUNTIME_EDITABLE}
        if "strategy" in patch:
            s = patch["strategy"]
            if "risk" in s and s["risk"] not in RISK_PROFILES:
                raise HttpError(400, "risk debe ser low, medium o high")
            if "time" in s and s["time"] not in TIME_PROFILES:
                raise HttpError(400, "time debe ser short, medium o long")
            if "enabled" in s and not set(s["enabled"]) <= set(STRATEGIES):
                raise HttpError(400, "Estrategia desconocida")
        if "update_interval_minutes" in patch and float(patch["update_interval_minutes"]) < 1:
            raise HttpError(400, "El intervalo mínimo es 1 minuto")
        saved = deep_merge(self.db.get_setting("runtime", {}) or {}, patch)
        self.db.set_setting("runtime", saved)
        new_cfg = deep_merge(self.base_cfg, saved)
        if self.demo:
            new_cfg = deep_merge(new_cfg, {"tracking": {"min_rating": 0}})
        # Mutar en sitio para que analizador, alertas y actualizador vean el cambio.
        self.cfg.clear()
        self.cfg.update(new_cfg)
        return public_view(self.cfg)

    # ---- vistas ------------------------------------------------------------------
    def status(self) -> dict:
        now = time.time()
        sources = []
        for s in self.sources:
            info = s.describe()
            info["status"] = self.db.get_source_status(s.name)
            sources.append(info)
        last = self.db.one("SELECT MAX(fetched_at) AS f, MAX(observed_at) AS o, COUNT(*) AS n FROM prices")
        counts = self.db.one("SELECT COUNT(*) AS players FROM players")
        return {
            "version": __version__,
            "mode": "demo" if self.demo else "real",
            "now": now,
            "sources": sources,
            "last_fetch_at": last["f"],
            "last_observed_at": last["o"],
            "price_rows": last["n"],
            "players": counts["players"],
            "update_interval_minutes": self.cfg["update_interval_minutes"],
            "last_run": self.updater.last_run,
            "unacknowledged_alerts": self.db.one(
                "SELECT COUNT(*) AS n FROM alert_log WHERE acknowledged=0")["n"],
            "platforms": PLATFORM_LABELS,
            "strategies": STRATEGIES,
            "alert_types": ALERT_TYPES,
            "config": public_view(self.cfg),
        }

    def players(self, q: dict) -> dict:
        where, params = [], []
        if q.get("q"):
            where.append("lower(p.name) LIKE ?")
            params.append(f"%{q['q'].lower()}%")
        for key, col in (("position", "p.position"), ("league", "p.league"), ("nation", "p.nation"),
                         ("rarity", "p.rarity")):
            if q.get(key):
                where.append(f"{col} = ?")
                params.append(q[key])
        if q.get("min_rating"):
            where.append("p.rating >= ?")
            params.append(int(q["min_rating"]))
        platform = q.get("platform") or "ps"
        latest = {r["player_id"]: r for r in self.db.latest_prices(platform)}
        rows = self.db.query("SELECT p.* FROM players p" + (" WHERE " + " AND ".join(where) if where else "")
                             + " ORDER BY p.rating DESC, p.name LIMIT 2000", params)
        stats = self.analyzer.all_stats(platform)
        watch = {r["player_id"] for r in self.db.query("SELECT player_id FROM watchlist")}
        out = []
        min_p = int(q["min_price"]) if q.get("min_price") else None
        max_p = int(q["max_price"]) if q.get("max_price") else None
        only_priced = q.get("only_priced", "1") == "1"
        for r in rows:
            lp = latest.get(r["id"])
            if lp is None and (only_priced or min_p or max_p):
                continue
            if lp and ((min_p and lp["price"] < min_p) or (max_p and lp["price"] > max_p)):
                continue
            st = stats.get((r["id"], platform)) or {}
            out.append({
                "id": r["id"], "name": r["name"], "rating": r["rating"], "position": r["position"],
                "league": r["league"], "nation": r["nation"], "club": r["club"], "rarity": r["rarity"],
                "is_demo": bool(r["is_demo"]), "watched": r["id"] in watch,
                "price": lp["price"] if lp else None,
                "price_source": lp["source"] if lp else None,
                "observed_at": lp["observed_at"] if lp else None,
                "freshness": st.get("freshness"), "trend": st.get("trend"),
                "median": st.get("median"), "samples": st.get("n", 0),
                "slope_long_pct_day": st.get("slope_long_pct_day"),
            })
        limit = int(q.get("limit") or 200)
        return {"platform": platform, "count": len(out), "items": out[:limit]}

    def player_detail(self, pid: str) -> dict:
        p = self.db.get_player(pid)
        if not p:
            raise HttpError(404, "Jugador no encontrado")
        p["external_ids"] = json.loads(p.get("external_ids") or "{}")
        stats = {plat: self.analyzer.stats_for(pid, plat) for plat in ("ps", "pc")}
        watch = self.db.one("SELECT * FROM watchlist WHERE player_id=?", (pid,))
        opps = self.analyzer.opportunities(player_ids={pid}, strategy_cfg={"max_results": 20})
        return {"player": p, "stats": stats, "watch": watch, "opportunities": opps["items"],
                "skipped": opps["skipped"]}

    def meta(self) -> dict:
        def distinct(col):
            return [r["v"] for r in self.db.query(
                f"SELECT DISTINCT {col} AS v FROM players WHERE {col} IS NOT NULL ORDER BY {col}")]
        return {k: distinct(k) for k in ("position", "league", "nation", "rarity")}


# ---- HTTP -------------------------------------------------------------------------
ROUTES: list[tuple[str, re.Pattern, str]] = []


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn.__name__))
        return fn
    return deco


class Handler(BaseHTTPRequestHandler):
    app: App = None  # type: ignore[assignment]
    server_version = "fc27-trader"

    def log_message(self, fmt, *args):  # silencia el log por petición
        log.debug("%s - %s", self.address_string(), fmt % args)

    # ---- despacho --------------------------------------------------------------
    def _dispatch(self, method: str):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        self.query = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        try:
            if path.startswith("/api/"):
                for m, rx, name in ROUTES:
                    match = rx.match(path)
                    if m == method and match:
                        args = [urllib.parse.unquote(a) for a in match.groups()]
                        return self._json(200, getattr(self, name)(*args))
                raise HttpError(404, "Ruta no encontrada")
            if method != "GET":
                raise HttpError(405, "Método no permitido")
            return self._static(path)
        except HttpError as exc:
            self._json(exc.status, {"error": str(exc)})
        except (ValueError, KeyError, TypeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            log.exception("Error en %s %s", method, path)
            self._json(500, {"error": f"Error interno: {exc}"})

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 5_000_000:
            raise HttpError(413, "Cuerpo demasiado grande")
        raw = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type", "")
        if "json" in ctype:
            return json.loads(raw.decode("utf-8") or "{}")
        return raw.decode("utf-8")

    def _json(self, status: int, data):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC / rel).resolve()
        if STATIC not in target.parents or not target.is_file():
            raise HttpError(404, "No encontrado")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(str(target))[0] or "application/octet-stream")
                         + ("; charset=utf-8" if target.suffix in (".html", ".js", ".css") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- API ---------------------------------------------------------------------
    @route("GET", r"/api/status")
    def api_status(self):
        return self.app.status()

    @route("GET", r"/api/meta")
    def api_meta(self):
        return self.app.meta()

    @route("GET", r"/api/players")
    def api_players(self):
        return self.app.players(self.query)

    @route("GET", r"/api/players/([^/]+)")
    def api_player(self, pid):
        return self.app.player_detail(pid)

    @route("GET", r"/api/players/([^/]+)/history")
    def api_history(self, pid):
        hours = float(self.query.get("hours") or 168)
        rows = self.app.db.price_history(pid, self.query.get("platform") or None, time.time() - hours * 3600)
        return {"player_id": pid, "hours": hours, "items": rows}

    @route("GET", r"/api/opportunities")
    def api_opportunities(self):
        q = self.query
        overrides = {}
        if q.get("budget"):
            overrides["budget"] = float(q["budget"])
        for k in ("risk", "time"):
            if q.get(k):
                overrides[k] = q[k]
        if q.get("strategy"):
            overrides["enabled"] = q["strategy"].split(",")
        if q.get("min_profit"):
            overrides["min_profit"] = float(q["min_profit"])
        return self.app.analyzer.opportunities(q.get("platform") or None, overrides)

    @route("GET", r"/api/platform-gaps")
    def api_gaps(self):
        return {"items": self.app.analyzer.platform_gaps(),
                "note": "Informativo: las monedas no se transfieren entre plataformas."}

    @route("GET", r"/api/market")
    def api_market(self):
        return self.app.analyzer.market_index(self.query.get("platform") or "ps",
                                              float(self.query.get("hours") or 72))

    @route("GET", r"/api/trends")
    def api_trends(self):
        platform = self.query.get("platform") or "ps"
        players = {p["id"]: p for p in self.app.db.query("SELECT id, name, rating, position FROM players")}
        items = []
        for (pid, plat), st in self.app.analyzer.all_stats(platform).items():
            if st.get("sufficient") and st["trend"] in ("alcista", "bajista") and st["freshness"] != "caducado":
                p = players.get(pid, {})
                items.append({"player_id": pid, "player_name": p.get("name"), "rating": p.get("rating"),
                              "platform": plat, "trend": st["trend"], "current": st["current"],
                              "slope_long_pct_day": st["slope_long_pct_day"],
                              "slope_short_pct_day": st["slope_short_pct_day"],
                              "freshness": st["freshness"], "source": st["current_source"]})
        items.sort(key=lambda x: abs(x["slope_long_pct_day"] or 0), reverse=True)
        return {"items": items}

    @route("GET", r"/api/calc")
    def api_calc(self):
        buy = float(self.query["buy"])
        sell = float(self.query["sell"])
        qty = int(self.query.get("quantity") or 1)
        r = self.app.rules
        out = r.profit(r.round_down(buy), r.round_down(sell), qty)
        out["note"] = (f"Impuesto {r.tax_rate * 100:g} % redondeado a favor de la prudencia; "
                       "precios ajustados a los incrementos válidos del mercado.")
        return out

    # lista de seguimiento
    @route("GET", r"/api/watchlist")
    def api_watch_list(self):
        rows = self.app.db.query("SELECT w.*, p.name, p.rating, p.position FROM watchlist w "
                                 "LEFT JOIN players p ON p.id=w.player_id ORDER BY w.added_at DESC")
        latest = {}
        for r in self.app.db.latest_prices():
            latest.setdefault(r["player_id"], {})[r["platform"]] = r
        for r in rows:
            r["prices"] = latest.get(r["player_id"], {})
        return {"items": rows}

    @route("POST", r"/api/watchlist")
    def api_watch_add(self):
        b = self._body()
        pid = b.get("player_id")
        if not pid or not self.app.db.get_player(pid):
            raise HttpError(400, "Jugador desconocido")
        self.app.db.execute(
            "INSERT INTO watchlist(player_id, note, target_buy, target_sell, added_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(player_id) DO UPDATE SET note=excluded.note, target_buy=excluded.target_buy, "
            "target_sell=excluded.target_sell",
            (pid, b.get("note"), b.get("target_buy") or None, b.get("target_sell") or None, time.time()))
        return {"ok": True}

    @route("DELETE", r"/api/watchlist/([^/]+)")
    def api_watch_del(self, pid):
        self.app.db.execute("DELETE FROM watchlist WHERE player_id=?", (pid,))
        return {"ok": True}

    # alertas
    @route("GET", r"/api/alerts/rules")
    def api_rules(self):
        return {"items": self.app.db.query(
            "SELECT r.*, p.name AS player_name FROM alert_rules r "
            "LEFT JOIN players p ON p.id=r.player_id ORDER BY r.id DESC")}

    @route("POST", r"/api/alerts/rules")
    def api_rule_add(self):
        rule = validate_rule(self._body())
        cur = self.app.db.execute(
            "INSERT INTO alert_rules(type, player_id, platform, threshold, window_hours, label, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (rule["type"], rule["player_id"], rule["platform"], rule["threshold"],
             rule["window_hours"], rule["label"], time.time()))
        return {"ok": True, "id": cur.lastrowid}

    @route("DELETE", r"/api/alerts/rules/(\d+)")
    def api_rule_del(self, rid):
        self.app.db.execute("DELETE FROM alert_rules WHERE id=?", (int(rid),))
        return {"ok": True}

    @route("GET", r"/api/alerts/log")
    def api_alert_log(self):
        return {"items": self.app.db.query("SELECT * FROM alert_log ORDER BY fired_at DESC LIMIT 200")}

    @route("POST", r"/api/alerts/log/ack")
    def api_alert_ack(self):
        self.app.db.execute("UPDATE alert_log SET acknowledged=1")
        return {"ok": True}

    @route("POST", r"/api/alerts/evaluate")
    def api_alert_eval(self):
        return {"fired": self.app.alerts.evaluate()}

    # operaciones
    @route("GET", r"/api/trades")
    def api_trades(self):
        rows = self.app.db.query("SELECT * FROM trades ORDER BY COALESCE(sell_at, buy_at) DESC")
        r = self.app.rules
        realized = invested_open = 0
        for t in rows:
            if t["sell_price"]:
                calc = r.profit(t["buy_price"], t["sell_price"], t["quantity"])
                t["profit"] = calc["total_profit"]
                t["tax"] = calc["tax"] * t["quantity"]
                realized += calc["total_profit"]
            else:
                t["profit"] = None
                invested_open += t["buy_price"] * t["quantity"]
        closed = [t for t in rows if t["sell_price"]]
        wins = sum(1 for t in closed if t["profit"] > 0)
        return {"items": rows, "summary": {
            "realized_profit": realized, "open_capital": invested_open,
            "closed": len(closed), "open": len(rows) - len(closed),
            "win_rate": round(wins / len(closed) * 100, 1) if closed else None}}

    @route("POST", r"/api/trades")
    def api_trade_add(self):
        b = self._body()
        if not b.get("buy_price") or int(b["buy_price"]) <= 0:
            raise HttpError(400, "buy_price es obligatorio")
        name = b.get("player_name")
        if b.get("player_id") and not name:
            p = self.app.db.get_player(b["player_id"])
            name = p["name"] if p else None
        cur = self.app.db.execute(
            "INSERT INTO trades(player_id, player_name, platform, quantity, buy_price, buy_at, "
            "sell_price, sell_at, strategy, note) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (b.get("player_id"), name, b.get("platform") or "ps", int(b.get("quantity") or 1),
             int(b["buy_price"]), b.get("buy_at") or time.time(),
             int(b["sell_price"]) if b.get("sell_price") else None,
             (b.get("sell_at") or time.time()) if b.get("sell_price") else None,
             b.get("strategy"), b.get("note")))
        return {"ok": True, "id": cur.lastrowid}

    @route("PUT", r"/api/trades/(\d+)")
    def api_trade_sell(self, tid):
        b = self._body()
        if not b.get("sell_price"):
            raise HttpError(400, "sell_price es obligatorio")
        self.app.db.execute("UPDATE trades SET sell_price=?, sell_at=? WHERE id=?",
                            (int(b["sell_price"]), b.get("sell_at") or time.time(), int(tid)))
        return {"ok": True}

    @route("DELETE", r"/api/trades/(\d+)")
    def api_trade_del(self, tid):
        self.app.db.execute("DELETE FROM trades WHERE id=?", (int(tid),))
        return {"ok": True}

    # eventos / SBC
    @route("GET", r"/api/events")
    def api_events(self):
        rows = self.app.db.query("SELECT * FROM events ORDER BY starts_at")
        for r in rows:
            r["player_ids"] = json.loads(r["player_ids"] or "[]")
        return {"items": rows}

    @route("POST", r"/api/events")
    def api_event_add(self):
        b = self._body()
        if not b.get("name") or not b.get("starts_at"):
            raise HttpError(400, "name y starts_at son obligatorios")
        cur = self.app.db.execute(
            "INSERT INTO events(name, kind, starts_at, ends_at, player_ids, rating_min, rating_max, note, "
            "created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (b["name"], b.get("kind") or "sbc", float(b["starts_at"]),
             float(b["ends_at"]) if b.get("ends_at") else None, json.dumps(b.get("player_ids") or []),
             int(b["rating_min"]) if b.get("rating_min") else None,
             int(b["rating_max"]) if b.get("rating_max") else None, b.get("note"), time.time()))
        return {"ok": True, "id": cur.lastrowid}

    @route("DELETE", r"/api/events/(\d+)")
    def api_event_del(self, eid):
        self.app.db.execute("DELETE FROM events WHERE id=?", (int(eid),))
        return {"ok": True}

    # precios manuales
    @route("POST", r"/api/prices/manual")
    def api_manual_price(self):
        if self.app.demo:
            raise HttpError(400, "En modo demo no se admiten precios reales (usa el modo normal).")
        b = self._body()
        row = build_manual_quote(self.app.db, player_id=b.get("player_id"), name=b.get("name"),
                                 platform=b.get("platform"), price=b.get("price"),
                                 observed_at=b.get("observed_at"), source_label=b.get("source") or "manual",
                                 rating=b.get("rating"), position=b.get("position"))
        return {"saved": self.app.db.insert_prices([row]), "player_id": row["player_id"]}

    @route("POST", r"/api/import/csv")
    def api_import_csv(self):
        if self.app.demo:
            raise HttpError(400, "En modo demo no se admiten precios reales (usa el modo normal).")
        body = self._body()
        text = body.get("csv") if isinstance(body, dict) else body
        return import_csv(self.app.db, text or "")

    # actualización y ajustes
    @route("POST", r"/api/update")
    def api_update(self):
        self.app.updater.trigger()
        return {"ok": True, "message": "Actualización solicitada"}

    @route("GET", r"/api/settings")
    def api_settings(self):
        return public_view(self.app.cfg)

    @route("PUT", r"/api/settings")
    def api_settings_put(self):
        return self.app.update_settings(self._body())


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # El navegador cerró la conexión (p. ej. al cambiar de app en el móvil): no es un error.
        import sys

        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def make_server(app: App, host: str, port: int) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    return QuietServer((host, port), handler)
