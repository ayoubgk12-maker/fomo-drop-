"""Motor de análisis: estadísticas, oportunidades, riesgo y probabilidad.

Principios:
  * "Dato real" = precio guardado de una fuente (con su hora y su origen).
  * "Estimación" = todo lo calculado (precio de compra/venta recomendado,
    probabilidad, tiempo de venta, riesgo). Se etiqueta siempre como tal.
  * Si no hay datos suficientes, el campo vale None y se explica el motivo; nunca
    se rellena con un valor inventado.
  * Los precios son el precio más bajo publicado (BIN) que da la fuente, no
    ventas reales: las fuentes autorizadas no publican volumen de ventas.
"""

from __future__ import annotations

import math
import statistics
import time
from collections import defaultdict

from .market import MarketRules

STRATEGIES = {
    "flip": "Flipping: comprar por debajo del precio habitual y revender al precio habitual",
    "dip": "Compra en caída: precio actual claramente por debajo de su mediana",
    "trend": "Tendencia alcista: subida sostenida a corto y medio plazo",
    "pre_event": "Inversión previa a SBC/evento (eventos introducidos por ti)",
    "liquidity": "Flipping en cartas con mucha actividad de precio (proxy de liquidez)",
}

RISK_PROFILES = {
    # máximo riesgo aceptado, probabilidad mínima, % del presupuesto por operación
    "low": {"max_risk": 35, "min_probability": 0.6, "position_pct": 0.20, "require_probability": True},
    "medium": {"max_risk": 60, "min_probability": 0.45, "position_pct": 0.35, "require_probability": False},
    "high": {"max_risk": 100, "min_probability": 0.0, "position_pct": 0.60, "require_probability": False},
}

TIME_PROFILES = {
    # horizonte de la operación en horas y estrategias preferidas
    "short": {"horizon_hours": 6, "preferred": {"flip", "dip", "liquidity"}},
    "medium": {"horizon_hours": 48, "preferred": {"flip", "dip", "trend", "liquidity", "pre_event"}},
    "long": {"horizon_hours": 168, "preferred": {"trend", "pre_event", "dip"}},
}


# ---- utilidades estadísticas -----------------------------------------------------
def coins(value) -> str:
    """Formato de monedas con punto de millares (estilo español)."""
    return f"{int(round(value)):,}".replace(",", ".")


def percentile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("lista vacía")
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return float(s[lo] + (s[hi] - s[lo]) * (pos - lo))


def log_slope_pct_per_day(points: list[tuple[float, float]]) -> float | None:
    """Pendiente de la regresión lineal de ln(precio) frente al tiempo, en % por día."""
    if len(points) < 3:
        return None
    xs = [t / 86400.0 for t, _ in points]
    ys = [math.log(p) for _, p in points if p > 0]
    if len(ys) != len(xs):
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return (math.exp(slope) - 1.0) * 100.0


def series_stats(series: list[dict], now: float, acfg: dict) -> dict:
    """Estadísticas de una serie ordenada por tiempo (dicts con price y observed_at)."""
    window_from = now - acfg["window_hours"] * 3600
    short_from = now - acfg["short_window_hours"] * 3600
    win = [r for r in series if r["observed_at"] >= window_from]
    if not win:
        return {"n": 0, "sufficient": False, "reason": "Sin precios en la ventana de análisis"}
    prices = [r["price"] for r in win]
    last = win[-1]
    span_h = (win[-1]["observed_at"] - win[0]["observed_at"]) / 3600.0
    mean = statistics.fmean(prices)
    stdev = statistics.pstdev(prices) if len(prices) > 1 else 0.0
    short = [(r["observed_at"], r["price"]) for r in win if r["observed_at"] >= short_from]
    changes = sum(1 for a, b in zip(prices, prices[1:]) if a != b)
    age_min = (now - last["observed_at"]) / 60.0
    sufficient = len(win) >= acfg["min_samples"] and span_h >= acfg["min_span_hours"]
    reason = "" if sufficient else (
        f"Datos insuficientes: {len(win)} precios en {span_h:.1f} h "
        f"(mínimo {acfg['min_samples']} precios y {acfg['min_span_hours']} h)")
    slope_long = log_slope_pct_per_day([(r["observed_at"], r["price"]) for r in win])
    slope_short = log_slope_pct_per_day(short)
    return {
        "n": len(win),
        "span_hours": round(span_h, 2),
        "current": last["price"],
        "current_source": last["source"],
        "current_observed_at": last["observed_at"],
        "current_age_minutes": round(age_min, 1),
        "min_price_range": last.get("min_price"),
        "max_price_range": last.get("max_price"),
        "mean": round(mean, 1),
        "median": percentile(prices, 0.5),
        "p20": percentile(prices, 0.2),
        "p80": percentile(prices, 0.8),
        "low": min(prices),
        "high": max(prices),
        "stdev": round(stdev, 1),
        "cv": round(stdev / mean, 4) if mean else None,
        "slope_long_pct_day": None if slope_long is None else round(slope_long, 2),
        "slope_short_pct_day": None if slope_short is None else round(slope_short, 2),
        "changes_per_day": round(changes / max(span_h / 24.0, 1 / 24.0), 1) if span_h else 0.0,
        "trend": classify_trend(slope_short, slope_long, acfg["trend_min_pct_per_day"]),
        "freshness": freshness(age_min, acfg),
        "sufficient": sufficient,
        "reason": reason,
        "is_demo": bool(last.get("is_demo")),
        "verified": bool(last.get("verified", 1)),
    }


def classify_trend(short, long, threshold) -> str:
    if long is None:
        return "sin datos"
    if long >= threshold and (short is None or short > 0):
        return "alcista"
    if long <= -threshold and (short is None or short < 0):
        return "bajista"
    return "lateral"


def freshness(age_minutes: float, acfg: dict) -> str:
    if age_minutes <= acfg["stale_after_minutes"]:
        return "reciente"
    if age_minutes <= acfg["exclude_after_hours"] * 60:
        return "desactualizado"
    return "caducado"


def sell_probability(series: list[dict], buy: float, sell: float, horizon_h: float,
                     min_episodes: int) -> dict:
    """Frecuencia histórica con la que, tras estar el precio en <= buy, alcanzó >= sell
    dentro del horizonte. Es una estimación empírica sobre precios publicados (no ventas)."""
    episodes = successes = 0
    times: list[float] = []
    n = len(series)
    end_t = series[-1]["observed_at"] if series else 0
    i = 0
    while i < n:
        r = series[i]
        entered = r["price"] <= buy and (i == 0 or series[i - 1]["price"] > buy)
        if not entered:
            i += 1
            continue
        t0 = r["observed_at"]
        hit = None
        j = i + 1
        while j < n and series[j]["observed_at"] - t0 <= horizon_h * 3600:
            if series[j]["price"] >= sell:
                hit = series[j]["observed_at"] - t0
                break
            j += 1
        if hit is not None:
            episodes += 1
            successes += 1
            times.append(hit / 3600.0)
        elif end_t - t0 >= horizon_h * 3600:
            episodes += 1  # episodio completo sin éxito
        # episodios recientes sin horizonte completo se descartan (censurados)
        i = j if hit is not None else i + 1
    out = {"episodes": episodes, "successes": successes, "probability": None, "eta_hours": None}
    if episodes >= min_episodes:
        out["probability"] = round(successes / episodes, 3)
    else:
        out["reason"] = (f"Solo {episodes} episodios históricos comparables "
                         f"(mínimo {min_episodes}); no se estima probabilidad")
    if len(times) >= 3:
        out["eta_hours"] = round(statistics.median(times), 1)
    elif episodes:
        out["eta_reason"] = "Pocos episodios con venta para estimar el tiempo"
    return out


def risk_score(stats: dict, buy: int, budget: float, acfg: dict) -> tuple[int, list[str]]:
    notes = []
    score = 0.0
    cv = stats.get("cv") or 0.0
    score += min(cv / 0.15, 1.0) * 35
    if cv >= 0.08:
        notes.append(f"volatilidad alta ({cv * 100:.1f} %)")
    slope = stats.get("slope_long_pct_day") or 0.0
    if slope < 0:
        score += min(-slope / 6.0, 1.0) * 30
        if slope <= -acfg["trend_min_pct_per_day"]:
            notes.append(f"tendencia bajista ({slope:.1f} %/día)")
    score += (1 - min(stats["n"] / 60.0, 1.0)) * 15
    if stats["n"] < 30:
        notes.append(f"historial corto ({stats['n']} precios)")
    score += min(stats["current_age_minutes"] / max(acfg["stale_after_minutes"], 1), 1.0) * 10
    if stats["freshness"] != "reciente":
        notes.append("precio no reciente")
    if budget:
        share = buy / budget
        score += min(share / 0.5, 1.0) * 15
        if share > 0.35:
            notes.append(f"usa el {share * 100:.0f} % del presupuesto")
    return int(round(min(score, 100))), notes


def merge_duplicates(items: list[dict]) -> list[dict]:
    """Une oportunidades idénticas (mismo jugador, plataforma, compra y venta) detectadas
    por varias estrategias; conserva la de mayor puntuación y acumula estrategias y motivos."""
    merged: dict = {}
    for o in items:
        key = (o["player_id"], o["platform"], o["estimate"]["buy_price"], o["estimate"]["sell_price"])
        if key not in merged:
            o["strategies"] = [o["strategy"]]
            merged[key] = o
            continue
        m = merged[key]
        if o["score"] > m["score"]:
            o["strategies"] = m["strategies"]
            o["reasons"] = m["reasons"] + [r for r in o["reasons"] if r not in m["reasons"]]
            m, merged[key] = o, o
        if o["strategy"] not in m["strategies"]:
            m["strategies"].append(o["strategy"])
        for reason in o["reasons"]:
            if reason not in m["reasons"]:
                m["reasons"].append(reason)
    return list(merged.values())


def risk_level(score: int) -> str:
    return "bajo" if score < 35 else "medio" if score < 60 else "alto"


# ---- motor ----------------------------------------------------------------------
class Analyzer:
    def __init__(self, db, cfg: dict, rules: MarketRules | None = None):
        self.db = db
        self.cfg = cfg
        self.rules = rules or MarketRules.from_config(cfg["market"])

    @property
    def acfg(self) -> dict:
        return self.cfg["analysis"]

    def load_series(self, platform: str | None = None, hours: float | None = None,
                    now: float | None = None) -> dict:
        now = now or time.time()
        hours = hours or max(self.acfg["window_hours"], self.acfg["probability_lookback_hours"])
        grouped: dict = defaultdict(list)
        for r in self.db.history_since(now - hours * 3600, platform):
            grouped[(r["player_id"], r["platform"])].append(r)
        return grouped

    def stats_for(self, player_id: str, platform: str, now: float | None = None) -> dict:
        now = now or time.time()
        since = now - self.acfg["window_hours"] * 3600
        series = self.db.price_history(player_id, platform, since)
        return series_stats(series, now, self.acfg)

    def all_stats(self, platform: str | None = None, now: float | None = None) -> dict:
        now = now or time.time()
        grouped = self.load_series(platform, self.acfg["window_hours"], now)
        return {k: series_stats(v, now, self.acfg) for k, v in grouped.items()}

    # ---- oportunidades -----------------------------------------------------------
    def opportunities(self, platform: str | None = None, strategy_cfg: dict | None = None,
                      now: float | None = None, player_ids: set | None = None) -> dict:
        now = now or time.time()
        scfg = dict(self.cfg["strategy"])
        scfg.update(strategy_cfg or {})
        risk_p = RISK_PROFILES.get(scfg.get("risk"), RISK_PROFILES["medium"])
        time_p = TIME_PROFILES.get(scfg.get("time"), TIME_PROFILES["medium"])
        enabled = set(scfg.get("enabled") or STRATEGIES)
        budget = float(scfg.get("budget") or 0)
        players = {p["id"]: p for p in self.db.query("SELECT * FROM players")}
        events = self.upcoming_events(now)
        grouped = self.load_series(platform, now=now)
        results, skipped = [], defaultdict(int)

        for (pid, plat), series in grouped.items():
            if player_ids and pid not in player_ids:
                continue
            stats = series_stats(series, now, self.acfg)
            if stats["n"] == 0:
                continue
            if stats["freshness"] == "caducado":
                skipped["precio caducado"] += 1
                continue
            if not stats["sufficient"]:
                skipped["datos insuficientes"] += 1
                continue
            player = players.get(pid) or {"id": pid, "name": pid}
            candidates = self._candidates(stats, player, events, enabled, time_p, now)
            for strat, buy, sell, reasons in candidates:
                opp = self._evaluate(series, stats, player, plat, strat, buy, sell, reasons,
                                     budget, risk_p, time_p, scfg)
                if isinstance(opp, str):
                    skipped[opp] += 1
                elif opp:
                    results.append(opp)

        results = merge_duplicates(results)
        results.sort(key=lambda o: o["score"], reverse=True)
        return {
            "generated_at": now,
            "settings": {k: scfg.get(k) for k in ("budget", "risk", "time", "enabled",
                                                  "min_profit", "min_margin_pct")},
            "count": len(results),
            "items": results[: int(scfg.get("max_results", 50))],
            "skipped": dict(skipped),
            "notes": [
                "Precio de compra/venta, probabilidad, tiempo y riesgo son ESTIMACIONES calculadas "
                "sobre el historial guardado; el precio actual es el último dato de la fuente.",
                "Las fuentes autorizadas no publican volumen de ventas: la 'liquidez' es un proxy "
                "basado en la frecuencia de cambios de precio.",
            ],
        }

    def _candidates(self, s, player, events, enabled, time_p, now):
        r = self.rules
        cur, med = s["current"], s["median"]
        out = []
        acfg = self.acfg
        slope_l = s["slope_long_pct_day"] or 0.0
        slope_s = s["slope_short_pct_day"] or 0.0
        # Flipping: comprar en la zona baja habitual (p20) y vender en la mediana.
        # No se propone en cartas con tendencia bajista: la "zona baja" de ayer no es soporte.
        if ("flip" in enabled or "liquidity" in enabled) and s["trend"] != "bajista":
            buy = r.round_down(min(cur, s["p20"]))
            sell = r.round_down(med)
            reasons = [f"Mediana {acfg['window_hours']} h: {coins(med)} · zona baja (p20): {coins(s['p20'])}"]
            if cur <= med * (1 - acfg["undervalued_pct"] / 100):
                reasons.append(f"Infravalorado: {100 * (1 - cur / med):.1f} % bajo la mediana")
            if "flip" in enabled:
                out.append(("flip", buy, sell, list(reasons)))
            if "liquidity" in enabled and s["changes_per_day"] >= 24:
                out.append(("liquidity", buy, sell, reasons + [
                    f"Actividad alta: {s['changes_per_day']:.0f} cambios de precio/día (proxy de liquidez)"]))
        # Compra en caída
        if "dip" in enabled and cur <= med * (1 - acfg["dip_pct"] / 100) \
                and slope_l > -acfg["trend_min_pct_per_day"]:
            out.append(("dip", r.round_down(cur), r.round_down(med), [
                f"Caída: {100 * (1 - cur / med):.1f} % bajo la mediana sin tendencia bajista de fondo"]))
        # Tendencia alcista: objetivo proyectado, limitado al máximo observado.
        if "trend" in enabled and s["trend"] == "alcista" and slope_s > 0:
            horizon_days = time_p["horizon_hours"] / 24.0
            # Proyección prudente: la mitad de la pendiente observada, máximo +25 %.
            projected = cur * (1 + slope_l / 200.0) ** horizon_days
            target = min(projected, cur * 1.25)
            out.append(("trend", r.round_down(cur), r.round_down(target), [
                f"Tendencia {slope_l:+.1f} %/día (corto plazo {slope_s:+.1f} %/día)",
                f"Objetivo = proyección a {horizon_days:g} días con la mitad de la pendiente "
                "(tope +25 %); es una estimación, la tendencia puede romperse"]))
        # Previo a evento/SBC: solo con eventos que has introducido tú.
        if "pre_event" in enabled:
            for ev in events:
                if self._event_matches(ev, player):
                    days = (ev["starts_at"] - now) / 86400.0
                    out.append(("pre_event", r.round_down(cur), r.round_down(s["p80"]), [
                        f"Evento '{ev['name']}' ({ev.get('kind') or 'evento'}) en {days:.1f} días "
                        "(dato introducido por el usuario)",
                        "Objetivo = percentil 80 del precio en la ventana"]))
                    break
        return out

    @staticmethod
    def _event_matches(ev, player) -> bool:
        if player["id"] in (ev.get("player_ids") or []):
            return True
        rating = player.get("rating")
        if rating is None or ev.get("rating_min") is None:
            return False
        hi = ev.get("rating_max") or 99
        return ev["rating_min"] <= rating <= hi

    def _evaluate(self, series, s, player, plat, strat, buy, sell, reasons, budget,
                  risk_p, time_p, scfg):
        r = self.rules
        sell = r.clamp_to_range(sell, s.get("min_price_range"), s.get("max_price_range"))
        if sell <= buy:
            return "sin margen tras ajustar al rango de precios"
        calc = r.profit(buy, sell)
        if calc["profit_per_unit"] < scfg.get("min_profit", 0):
            return "beneficio por debajo del mínimo"
        if calc["margin_pct"] < scfg.get("min_margin_pct", 0):
            return "margen por debajo del mínimo"
        horizon = min(time_p["horizon_hours"], self.acfg["probability_horizon_hours"]) \
            if strat in ("flip", "dip", "liquidity") else time_p["horizon_hours"]
        prob = sell_probability(series, buy, sell, horizon, self.acfg["min_episodes"])
        if prob["probability"] is None and risk_p["require_probability"]:
            return "sin probabilidad estimable (perfil de riesgo bajo)"
        if prob["probability"] is not None and prob["probability"] < risk_p["min_probability"]:
            return "probabilidad histórica baja"
        if strat not in time_p["preferred"]:
            return "estrategia no adecuada al tiempo disponible"
        if budget and buy > budget:
            return "fuera de presupuesto"
        rscore, rnotes = risk_score(s, buy, budget, self.acfg)
        if rscore > risk_p["max_risk"]:
            return "riesgo por encima del perfil"
        qty = max(1, int((budget * risk_p["position_pct"]) // buy)) if budget else 1
        qty = min(qty, 20)
        if budget and buy * qty > budget:
            qty = max(1, int(budget // buy))
        calc = r.profit(buy, sell, qty)
        # Puntuación SOLO para ordenar: margen × probabilidad (0,5 si no es estimable) × (1 − riesgo).
        p_for_rank = prob["probability"] if prob["probability"] is not None else 0.5
        score = calc["margin_pct"] * p_for_rank * (1 - rscore / 100.0)
        return {
            "player_id": player["id"],
            "player_name": player.get("name"),
            "rating": player.get("rating"),
            "position": player.get("position"),
            "rarity": player.get("rarity"),
            "platform": plat,
            "strategy": strat,
            "strategy_label": STRATEGIES[strat],
            "data": {  # datos reales de la fuente
                "current": s["current"],
                "source": s["current_source"],
                "observed_at": s["current_observed_at"],
                "age_minutes": s["current_age_minutes"],
                "freshness": s["freshness"],
                "median": s["median"],
                "samples": s["n"],
                "span_hours": s["span_hours"],
                "trend": s["trend"],
                "price_range": [s.get("min_price_range"), s.get("max_price_range")],
                "is_demo": s["is_demo"],
            },
            "estimate": {  # todo lo calculado
                **calc,
                "risk_score": rscore,
                "risk_level": risk_level(rscore),
                "risk_notes": rnotes,
                "probability": prob["probability"],
                "probability_basis": f"{prob['successes']}/{prob['episodes']} episodios en "
                                     f"{self.acfg['probability_lookback_hours']} h, horizonte {horizon:g} h",
                "probability_reason": prob.get("reason"),
                "eta_hours": prob["eta_hours"],
                "eta_reason": prob.get("eta_reason") if prob["eta_hours"] is None else None,
                "horizon_hours": horizon,
            },
            "reasons": reasons,
            "score": round(score, 3),
        }

    # ---- otras vistas ------------------------------------------------------------
    def upcoming_events(self, now: float) -> list[dict]:
        import json as _json

        rows = self.db.query("SELECT * FROM events WHERE starts_at IS NOT NULL AND starts_at>=? "
                             "ORDER BY starts_at", (now,))
        for r in rows:
            r["player_ids"] = _json.loads(r["player_ids"] or "[]")
        return rows

    def platform_gaps(self, now: float | None = None, min_pct: float | None = None) -> list[dict]:
        """Diferencias consola/PC con precios recientes en ambas. Informativo: las monedas
        no se pueden pasar de una plataforma a otra, así que no es arbitraje directo."""
        now = now or time.time()
        min_pct = self.acfg["platform_gap_pct"] if min_pct is None else min_pct
        latest = defaultdict(dict)
        for row in self.db.latest_prices():
            latest[row["player_id"]][row["platform"]] = row
        players = {p["id"]: p for p in self.db.query("SELECT id, name, rating, position FROM players")}
        out = []
        for pid, plats in latest.items():
            if "ps" not in plats or "pc" not in plats:
                continue
            a, b = plats["ps"], plats["pc"]
            ages = [(now - x["observed_at"]) / 60.0 for x in (a, b)]
            if max(ages) > self.acfg["stale_after_minutes"]:
                continue
            lo = min(a["price"], b["price"])
            gap = abs(a["price"] - b["price"]) / lo * 100 if lo else 0
            if gap >= min_pct:
                p = players.get(pid, {})
                out.append({
                    "player_id": pid, "player_name": p.get("name"), "rating": p.get("rating"),
                    "ps": a["price"], "pc": b["price"], "gap_pct": round(gap, 1),
                    "cheaper": "ps" if a["price"] < b["price"] else "pc",
                    "observed_at": min(a["observed_at"], b["observed_at"]),
                    "sources": sorted({a["source"], b["source"]}),
                })
        out.sort(key=lambda x: x["gap_pct"], reverse=True)
        return out

    def market_index(self, platform: str = "ps", hours: float = 72, bucket_minutes: int = 60,
                     now: float | None = None) -> dict:
        """Índice de mercado: mediana, entre jugadores, del precio relativo a su primer
        precio de la ventana (=100). Solo con los jugadores que tienen datos."""
        now = now or time.time()
        grouped = self.load_series(platform, hours, now)
        buckets: dict = defaultdict(list)
        bsec = bucket_minutes * 60
        for (_pid, _plat), series in grouped.items():
            if len(series) < 2:
                continue
            base = series[0]["price"]
            last_bucket = {}
            for r in series:
                last_bucket[int(r["observed_at"] // bsec)] = r["price"] / base * 100
            for b, v in last_bucket.items():
                buckets[b].append(v)
        points = [{"t": b * bsec, "value": round(statistics.median(v), 2), "players": len(v)}
                  for b, v in sorted(buckets.items()) if len(v) >= 3]
        change = None
        if len(points) >= 2:
            change = round((points[-1]["value"] / points[0]["value"] - 1) * 100, 2)
        return {"platform": platform, "hours": hours, "points": points, "change_pct": change,
                "players": len(grouped)}

    def market_change(self, platform: str, window_hours: float, now: float | None = None) -> dict:
        """Variación mediana de precios en la ventana (para la alerta de caída de mercado)."""
        now = now or time.time()
        grouped = self.load_series(platform, window_hours, now)
        changes = []
        for series in grouped.values():
            if len(series) >= 2 and series[0]["price"]:
                changes.append(series[-1]["price"] / series[0]["price"] - 1)
        if len(changes) < 3:
            return {"change_pct": None, "players": len(changes)}
        return {"change_pct": round(statistics.median(changes) * 100, 2), "players": len(changes)}
