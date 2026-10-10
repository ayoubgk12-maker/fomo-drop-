"""Alertas configurables. Se evalúan tras cada actualización de precios."""

from __future__ import annotations

import json
import time

from .analysis import coins

ALERT_TYPES = {
    "price_below": "El precio baja de un valor (threshold = monedas)",
    "pct_rise": "El precio sube un % en la ventana (threshold = %, window_hours)",
    "pct_drop": "El precio cae un % en la ventana (threshold = %, window_hours)",
    "platform_gap": "Diferencia consola/PC mayor que un % (threshold = %)",
    "market_crash": "Caída mediana del mercado mayor que un % (threshold = %, window_hours, platform)",
    "opportunity_profit": "Aparece una oportunidad con beneficio neto >= threshold monedas",
}
NEEDS_PLAYER = {"price_below", "pct_rise", "pct_drop", "platform_gap"}


def validate_rule(rule: dict) -> dict:
    rtype = rule.get("type")
    if rtype not in ALERT_TYPES:
        raise ValueError(f"Tipo de alerta desconocido: {rtype}")
    if rtype in NEEDS_PLAYER and not rule.get("player_id"):
        raise ValueError("Esta alerta necesita un jugador")
    try:
        threshold = float(rule.get("threshold"))
    except (TypeError, ValueError):
        raise ValueError("threshold debe ser numérico") from None
    if threshold <= 0:
        raise ValueError("threshold debe ser positivo")
    platform = rule.get("platform") or None
    if platform not in (None, "ps", "pc"):
        raise ValueError("platform debe ser ps, pc o vacío")
    window = rule.get("window_hours")
    window = float(window) if window not in (None, "") else None
    if rtype in ("pct_rise", "pct_drop", "market_crash") and not window:
        window = 24.0
    return {"type": rtype, "player_id": rule.get("player_id") or None, "platform": platform,
            "threshold": threshold, "window_hours": window, "label": rule.get("label") or None}


class AlertEngine:
    def __init__(self, db, analyzer, cfg: dict):
        self.db = db
        self.analyzer = analyzer
        self.cfg = cfg

    def evaluate(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        cooldown = self.cfg["alerts"]["cooldown_minutes"] * 60
        fired = []
        opps = None
        for rule in self.db.query("SELECT * FROM alert_rules WHERE enabled=1"):
            if rule["last_fired_at"] and now - rule["last_fired_at"] < cooldown:
                continue
            if rule["type"] == "opportunity_profit" and opps is None:
                opps = self.analyzer.opportunities(rule["platform"], now=now)["items"]
            hit = self._check(rule, now, opps)
            if hit:
                message, data = hit
                self.db.execute("INSERT INTO alert_log(rule_id, fired_at, message, data) VALUES(?,?,?,?)",
                                (rule["id"], now, message, json.dumps(data)))
                self.db.execute("UPDATE alert_rules SET last_fired_at=? WHERE id=?", (now, rule["id"]))
                fired.append({"rule_id": rule["id"], "message": message, "data": data})
        return fired

    def _player_name(self, pid):
        p = self.db.get_player(pid) if pid else None
        return p["name"] if p else pid

    def _platforms(self, rule):
        return [rule["platform"]] if rule["platform"] else ["ps", "pc"]

    def _check(self, rule, now, opps):
        t, thr = rule["type"], rule["threshold"]
        acfg = self.cfg["analysis"]
        stale = acfg["stale_after_minutes"] * 60
        if t == "price_below":
            for plat in self._platforms(rule):
                hist = self.db.price_history(rule["player_id"], plat, now - stale)
                if hist and hist[-1]["price"] < thr:
                    last = hist[-1]
                    return (f"{self._player_name(rule['player_id'])} ({plat.upper()}) a "
                            f"{coins(last['price'])} < {coins(int(thr))} [fuente: {last['source']}]",
                            {"price": last["price"], "platform": plat, "observed_at": last["observed_at"]})
        elif t in ("pct_rise", "pct_drop"):
            for plat in self._platforms(rule):
                hist = self.db.price_history(rule["player_id"], plat, now - rule["window_hours"] * 3600)
                if len(hist) < 2 or now - hist[-1]["observed_at"] > stale:
                    continue
                first, last = hist[0]["price"], hist[-1]["price"]
                change = (last / first - 1) * 100
                if (t == "pct_rise" and change >= thr) or (t == "pct_drop" and change <= -thr):
                    verb = "sube" if t == "pct_rise" else "cae"
                    return (f"{self._player_name(rule['player_id'])} ({plat.upper()}) {verb} "
                            f"{change:+.1f} % en {rule['window_hours']:g} h ({coins(first)} → {coins(last)})",
                            {"change_pct": round(change, 2), "platform": plat})
        elif t == "platform_gap":
            for g in self.analyzer.platform_gaps(now, min_pct=thr):
                if g["player_id"] == rule["player_id"]:
                    return (f"{g['player_name']}: consola {coins(g['ps'])} vs PC {coins(g['pc'])} "
                            f"({g['gap_pct']} %)", g)
        elif t == "market_crash":
            for plat in self._platforms(rule):
                m = self.analyzer.market_change(plat, rule["window_hours"], now)
                if m["change_pct"] is not None and m["change_pct"] <= -thr:
                    return (f"Caída de mercado ({plat.upper()}): mediana {m['change_pct']:+.1f} % "
                            f"en {rule['window_hours']:g} h sobre {m['players']} jugadores seguidos", m)
        elif t == "opportunity_profit":
            best = [o for o in (opps or [])
                    if o["estimate"]["profit_per_unit"] >= thr
                    and (not rule["player_id"] or o["player_id"] == rule["player_id"])]
            if best:
                o = best[0]
                return (f"Oportunidad: {o['player_name']} ({o['platform'].upper()}, {o['strategy']}) "
                        f"compra {coins(o['estimate']['buy_price'])} → venta {coins(o['estimate']['sell_price'])}, "
                        f"beneficio neto estimado {coins(o['estimate']['profit_per_unit'])}",
                        {"player_id": o["player_id"], "strategy": o["strategy"],
                         "profit": o["estimate"]["profit_per_unit"], "count": len(best)})
        return None
