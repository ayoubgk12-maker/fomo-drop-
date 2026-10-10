/* Panel de FC 27 Trader. JavaScript sin dependencias. */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const state = { status: null, platform: "ps", players: new Map(), lastAlertId: null };

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => (n === null || n === undefined || Number.isNaN(n)) ? "—" : Math.round(n).toLocaleString("es-ES", { useGrouping: "always" });
const pct = (n, d = 1) => (n === null || n === undefined) ? "—" : `${n > 0 ? "+" : ""}${Number(n).toFixed(d)} %`;
const platLabel = (p) => (p === "pc" ? "PC" : "Consola");
const pill = (cls, text) => `<span class="pill ${esc(cls)}">${esc(text ?? cls)}</span>`;

function ago(ts) {
  if (!ts) return "nunca";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "hace segundos";
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  return `hace ${Math.round(s / 86400)} d`;
}
const dt = (ts) => (ts ? new Date(ts * 1000).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" }) : "—");

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, init);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

function table(headers, rows, opts = {}) {
  if (!rows.length) return `<div class="empty">${esc(opts.empty || "Sin datos.")}</div>`;
  const head = opts.groupRow || "";
  const th = headers.map((h) => `<th class="${h.num ? "num" : ""}">${esc(h.label)}</th>`).join("");
  return `<table>${head ? `<thead>${head}<tr>${th}</tr></thead>` : `<thead><tr>${th}</tr></thead>`}<tbody>${rows.join("")}</tbody></table>`;
}

/* ---------------- gráfico SVG ---------------- */
function lineChart(el, series, opts = {}) {
  const pts = series.flatMap((s) => s.points);
  if (pts.length < 2) {
    el.innerHTML = `<div class="empty">${esc(opts.empty || "Aún no hay suficiente historial para dibujar el gráfico.")}</div>`;
    return;
  }
  const W = 800, H = 240, L = 62, R = 12, T = 12, B = 28;
  const xs = pts.map((p) => p.t), ys = pts.map((p) => p.v);
  let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (opts.baseline !== undefined) { y0 = Math.min(y0, opts.baseline); y1 = Math.max(y1, opts.baseline); }
  if (y0 === y1) { y0 *= 0.98; y1 *= 1.02; }
  const pad = (y1 - y0) * 0.08; y0 -= pad; y1 += pad;
  if (x0 === x1) x1 = x0 + 1;
  const X = (t) => L + ((t - x0) / (x1 - x0)) * (W - L - R);
  const Y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
  let grid = "";
  for (let i = 0; i <= 4; i++) {
    const v = y0 + ((y1 - y0) * i) / 4, y = Y(v);
    grid += `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="#2a3340" stroke-width="1"/>`;
    grid += `<text x="${L - 6}" y="${y + 4}" fill="#8b98a8" font-size="11" text-anchor="end">${opts.yfmt ? opts.yfmt(v) : fmt(v)}</text>`;
  }
  for (let i = 0; i <= 4; i++) {
    const t = x0 + ((x1 - x0) * i) / 4;
    const label = new Date(t * 1000).toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    grid += `<text x="${X(t)}" y="${H - 8}" fill="#8b98a8" font-size="11" text-anchor="middle">${label}</text>`;
  }
  if (opts.baseline !== undefined) {
    grid += `<line x1="${L}" x2="${W - R}" y1="${Y(opts.baseline)}" y2="${Y(opts.baseline)}" stroke="#8b98a8" stroke-dasharray="4 4"/>`;
  }
  const lines = series.filter((s) => s.points.length).map((s) => {
    const d = s.points.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p.v).toFixed(1)}`).join("");
    return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round"><title>${esc(s.name)}</title></path>`;
  }).join("");
  const legend = series.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(opts.label || "Gráfico")}">${grid}${lines}</svg><div class="legend">${legend}</div>`;
}

/* ---------------- estado y cabecera ---------------- */
async function loadStatus() {
  const s = await api("/api/status");
  state.status = s;
  const badge = $("#modeBadge");
  badge.textContent = s.mode === "demo" ? "DEMO" : "DATOS REALES";
  badge.className = `badge ${s.mode}`;
  $("#demoBanner").classList.toggle("hidden", s.mode !== "demo");
  const active = s.sources.filter((x) => x.available && x.kind !== "unavailable");
  $("#statusLine").textContent =
    `Última actualización: ${dt(s.last_fetch_at)} (${ago(s.last_fetch_at)}) · ` +
    `cada ${s.update_interval_minutes} min · ${fmt(s.players)} jugadores · ${fmt(s.price_rows)} precios guardados · ` +
    `fuentes activas: ${active.map((x) => x.label).join(", ") || "ninguna"}`;
  const c = $("#alertCount");
  c.textContent = s.unacknowledged_alerts;
  c.classList.toggle("hidden", !s.unacknowledged_alerts);
  if (!$("#aType").options.length) {
    $("#aType").innerHTML = Object.entries(s.alert_types).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("");
    $("#aTypeHint").textContent = s.alert_types[$("#aType").value];
    $("#oStrategies").innerHTML = Object.entries(s.strategies).map(([k, v]) =>
      `<label title="${esc(v)}"><input type="checkbox" value="${esc(k)}"> ${esc(k)}</label>`).join("");
    fillProfile(s.config.strategy);
    fillSettings(s.config);
  }
  return s;
}

function sourceRows(sources, full) {
  return sources.map((x) => {
    const st = x.status || {};
    const state = x.kind === "unavailable" ? "unavailable" : (st.state || "pending");
    const label = { ok: "OK", partial: "parcial", error: "error", circuit_open: "en pausa por errores",
      auth_error: "error de autenticación", not_configured: "sin configurar", unavailable: "no disponible",
      pending: "pendiente" }[state] || state;
    const detail = x.available ? (st.last_error && state !== "ok" ? st.last_error : st.detail) : x.reason;
    return `<tr><td><b>${esc(x.label)}</b>${x.url ? `<div class="muted">${esc(x.url)}</div>` : ""}</td>
      <td>${pill(state, label)}</td>
      ${full ? `<td>${esc(x.kind)}</td><td>${dt(st.last_success)}</td><td class="num">${fmt(st.requests_made)}</td>` : ""}
      <td class="muted">${esc(detail || "")}${full && x.authorized_note ? `<div>${esc(x.authorized_note)}</div>` : ""}</td></tr>`;
  });
}

/* ---------------- panel ---------------- */
async function loadOverview() {
  const s = state.status;
  const [opps, market, trends, log, trades] = await Promise.all([
    api(`/api/opportunities?platform=${state.platform}`),
    api(`/api/market?platform=${state.platform}&hours=${s.config.analysis.window_hours}`),
    api(`/api/trends?platform=${state.platform}`),
    api("/api/alerts/log"),
    api("/api/trades"),
  ]);
  const best = opps.items[0];
  $("#kpis").innerHTML = [
    ["Oportunidades", fmt(opps.count), `${platLabel(state.platform)} · perfil ${s.config.strategy.risk}/${s.config.strategy.time}`],
    ["Mejor beneficio neto (est.)", best ? fmt(best.estimate.profit_per_unit) : "—", best ? esc(best.player_name) : "sin oportunidades"],
    ["Mercado (ventana)", pct(market.change_pct), `${market.players} jugadores con datos`],
    ["Alertas sin ver", fmt(s.unacknowledged_alerts), ""],
    ["Beneficio realizado", fmt(trades.summary.realized_profit), `${trades.summary.closed} operaciones cerradas`],
  ].map(([l, v, sub]) => `<div class="card kpi"><div class="label">${esc(l)}</div><div class="value">${v}</div><div class="sub">${sub}</div></div>`).join("");
  $("#marketNote").textContent = "mediana del precio relativo (base 100) de los jugadores seguidos";
  lineChart($("#marketChart"), [{ name: `Índice ${platLabel(state.platform)}`, color: "#38bdf8",
    points: market.points.map((p) => ({ t: p.t, v: p.value })) }], { baseline: 100, yfmt: (v) => v.toFixed(0), label: "Índice de mercado" });
  $("#sourcesMini").innerHTML = table([{ label: "Fuente" }, { label: "Estado" }, { label: "Detalle" }], sourceRows(s.sources, false));
  $("#topOpps").innerHTML = oppsTable(opps.items.slice(0, 8));
  $("#trendsMini").innerHTML = table(
    [{ label: "Jugador" }, { label: "Tendencia" }, { label: "Actual", num: true }, { label: "%/día", num: true }],
    trends.items.slice(0, 10).map((t) => `<tr class="click" data-player="${esc(t.player_id)}"><td>${esc(t.player_name)}</td>
      <td>${pill(t.trend)}</td><td class="num">${fmt(t.current)}</td><td class="num ${t.slope_long_pct_day > 0 ? "pos" : "neg"}">${pct(t.slope_long_pct_day)}</td></tr>`),
    { empty: "Sin tendencias claras con los datos actuales." });
  $("#alertsMini").innerHTML = alertLogTable(log.items.slice(0, 8));
}

/* ---------------- oportunidades ---------------- */
function oppsTable(items) {
  const group = `<tr><th colspan="3"></th><th colspan="3" class="th-group th-real">Dato real (fuente)</th>
    <th colspan="7" class="th-group th-est">Estimación (calculada)</th></tr>`;
  const headers = [{ label: "Jugador" }, { label: "Plat." }, { label: "Estrategia" },
    { label: "Precio actual", num: true }, { label: "Fuente / hora" }, { label: "Frescura" },
    { label: "Compra", num: true }, { label: "Venta", num: true }, { label: "Beneficio neto", num: true },
    { label: "Margen", num: true }, { label: "Capital", num: true }, { label: "Prob.", num: true }, { label: "Riesgo / tiempo" }];
  const rows = items.map((o) => {
    const e = o.estimate, d = o.data;
    const prob = e.probability === null ? `<span class="muted" title="${esc(e.probability_reason)}">n/d</span>`
      : `<span title="${esc(e.probability_basis)}">${(e.probability * 100).toFixed(0)} %</span>`;
    const eta = e.eta_hours === null ? "tiempo n/d" : `~${e.eta_hours} h`;
    return `<tr class="click" data-player="${esc(o.player_id)}">
      <td><b>${esc(o.player_name)}</b> <span class="muted">${esc(o.rating ?? "")} ${esc(o.position ?? "")}</span>
        ${d.is_demo ? pill("demo", "DEMO") : ""}
        <ul class="reasons">${o.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></td>
      <td>${platLabel(o.platform)}</td>
      <td>${(o.strategies || [o.strategy]).map((s) => pill("", s)).join(" ")}</td>
      <td class="num">${fmt(d.current)}</td>
      <td class="muted">${esc(d.source)}<br>${dt(d.observed_at)}</td>
      <td>${pill(d.freshness)}</td>
      <td class="num">${fmt(e.buy_price)}</td>
      <td class="num">${fmt(e.sell_price)}<div class="muted">neto ${fmt(e.net_sell)}</div></td>
      <td class="num pos">${fmt(e.profit_per_unit)}<div class="muted">×${e.quantity} = ${fmt(e.total_profit)}</div></td>
      <td class="num">${e.margin_pct.toFixed(1)} %</td>
      <td class="num">${fmt(e.capital)}</td>
      <td class="num">${prob}</td>
      <td>${pill(e.risk_level, `${e.risk_level} (${e.risk_score})`)}<div class="muted">${esc(eta)}</div>
        ${e.risk_notes.length ? `<div class="muted">${esc(e.risk_notes.join("; "))}</div>` : ""}</td></tr>`;
  });
  return table(headers, rows, { groupRow: group, empty: "Ninguna oportunidad cumple tu perfil con los datos disponibles." });
}

function fillProfile(sc) {
  $("#oBudget").value = sc.budget;
  $("#oRisk").value = sc.risk;
  $("#oTime").value = sc.time;
  $("#oMinProfit").value = sc.min_profit;
  $$("#oStrategies input").forEach((i) => { i.checked = sc.enabled.includes(i.value); });
}

function profileFromForm() {
  return {
    budget: Number($("#oBudget").value) || 0,
    risk: $("#oRisk").value,
    time: $("#oTime").value,
    min_profit: Number($("#oMinProfit").value) || 0,
    enabled: $$("#oStrategies input:checked").map((i) => i.value),
  };
}

async function loadOpps() {
  const p = profileFromForm();
  const qs = new URLSearchParams({ platform: state.platform, budget: p.budget, risk: p.risk, time: p.time,
    min_profit: p.min_profit, strategy: p.enabled.join(",") });
  const [opps, gaps] = await Promise.all([api(`/api/opportunities?${qs}`), api("/api/platform-gaps")]);
  const skipped = Object.entries(opps.skipped).map(([k, v]) => `${k}: ${v}`).join(" · ");
  $("#oNotes").innerHTML = `${opps.count} oportunidades. ${opps.notes.map(esc).join(" ")}` +
    (skipped ? `<br>Descartadas: ${esc(skipped)}` : "");
  $("#oppsTable").innerHTML = oppsTable(opps.items);
  $("#gapsTable").innerHTML = table(
    [{ label: "Jugador" }, { label: "Consola", num: true }, { label: "PC", num: true }, { label: "Diferencia", num: true }, { label: "Fuentes / hora" }],
    gaps.items.map((g) => `<tr class="click" data-player="${esc(g.player_id)}"><td>${esc(g.player_name)}</td><td class="num">${fmt(g.ps)}</td>
      <td class="num">${fmt(g.pc)}</td><td class="num">${g.gap_pct} %</td><td class="muted">${esc(g.sources.join(", "))} · ${dt(g.observed_at)}</td></tr>`),
    { empty: "No hay diferencias por encima del umbral con precios recientes en ambas plataformas." });
}

/* ---------------- jugadores ---------------- */
async function loadMeta() {
  const m = await api("/api/meta");
  for (const [key, sel] of [["position", "#pPosition"], ["league", "#pLeague"], ["nation", "#pNation"], ["rarity", "#pRarity"]]) {
    const el = $(sel), cur = el.value;
    el.innerHTML = `<option value="">Todas</option>` + m[key].map((v) => `<option>${esc(v)}</option>`).join("");
    el.value = cur;
  }
}

async function loadPlayers() {
  const qs = new URLSearchParams({ platform: state.platform, q: $("#pQ").value, position: $("#pPosition").value,
    league: $("#pLeague").value, nation: $("#pNation").value, rarity: $("#pRarity").value,
    min_rating: $("#pRating").value, min_price: $("#pMin").value, max_price: $("#pMax").value,
    only_priced: $("#pPriced").checked ? "1" : "0", limit: 300 });
  const data = await api(`/api/players?${qs}`);
  data.items.forEach((p) => state.players.set(p.id, p));
  refreshDatalist();
  $("#playersTable").innerHTML = table(
    [{ label: "Jugador" }, { label: "Val.", num: true }, { label: "Pos." }, { label: "Liga" }, { label: "Nación" }, { label: "Rareza" },
      { label: `Precio ${platLabel(state.platform)}`, num: true }, { label: "Fuente / hora" }, { label: "Frescura" },
      { label: "Mediana", num: true }, { label: "Tendencia" }, { label: "" }],
    data.items.map((p) => `<tr class="click" data-player="${esc(p.id)}">
      <td><b>${esc(p.name)}</b></td><td class="num">${esc(p.rating ?? "")}</td><td>${esc(p.position ?? "")}</td>
      <td>${esc(p.league ?? "")}</td><td>${esc(p.nation ?? "")}</td><td>${esc(p.rarity ?? "")}</td>
      <td class="num">${fmt(p.price)}</td><td class="muted">${p.price_source ? `${esc(p.price_source)} · ${ago(p.observed_at)}` : "sin precio"}</td>
      <td>${p.freshness ? pill(p.freshness) : ""}</td><td class="num">${fmt(p.median)}</td>
      <td>${p.trend ? pill(p.trend) : ""}</td><td>${p.watched ? "★" : ""}</td></tr>`),
    { empty: "No hay jugadores con esos filtros." });
}

function refreshDatalist() {
  $("#playerList").innerHTML = [...state.players.values()].slice(0, 3000)
    .map((p) => `<option value="${esc(p.name)}"></option>`).join("");
}

function findPlayerByName(name) {
  const n = (name || "").trim().toLowerCase();
  for (const p of state.players.values()) if (p.name.toLowerCase() === n) return p;
  return null;
}

async function openPlayer(pid) {
  const [d, hist] = await Promise.all([api(`/api/players/${encodeURIComponent(pid)}`),
    api(`/api/players/${encodeURIComponent(pid)}/history?hours=${Math.max(168, state.status.config.analysis.window_hours)}`)]);
  const p = d.player;
  state.players.set(p.id, p);
  const statBlock = (plat) => {
    const s = d.stats[plat];
    if (!s.n) return `<p class="muted">${platLabel(plat)}: sin precios en la ventana de análisis.</p>`;
    return `<h4>${platLabel(plat)} ${pill(s.freshness)} ${pill(s.trend)} ${s.is_demo ? pill("demo", "DEMO") : ""}</h4>
      <div class="stats">
        <div><span>Actual (dato real)</span><b>${fmt(s.current)}</b><span>${esc(s.current_source)} · ${dt(s.current_observed_at)}</span></div>
        <div><span>Mediana ventana</span><b>${fmt(s.median)}</b><span>${s.n} precios en ${s.span_hours} h</span></div>
        <div><span>Zona baja / alta (p20 / p80)</span><b>${fmt(s.p20)} / ${fmt(s.p80)}</b></div>
        <div><span>Mín. / máx. observados</span><b>${fmt(s.low)} / ${fmt(s.high)}</b></div>
        <div><span>Rango EA</span><b>${fmt(s.min_price_range)} – ${fmt(s.max_price_range)}</b></div>
        <div><span>Tendencia ventana / corto</span><b>${pct(s.slope_long_pct_day)} / ${pct(s.slope_short_pct_day)}</b><span>por día</span></div>
        <div><span>Volatilidad (CV)</span><b>${s.cv === null ? "—" : (s.cv * 100).toFixed(1) + " %"}</b></div>
        <div><span>Cambios de precio / día</span><b>${fmt(s.changes_per_day)}</b><span>proxy de actividad</span></div>
      </div>${s.sufficient ? "" : `<p class="hint">${esc(s.reason)}</p>`}`;
  };
  $("#drawerBody").innerHTML = `
    <h2>${esc(p.name)} <span class="muted">${esc(p.rating ?? "")} ${esc(p.position ?? "")}</span> ${p.is_demo ? pill("demo", "DEMO") : ""}</h2>
    <p class="muted">${esc([p.club, p.league, p.nation, p.rarity].filter(Boolean).join(" · "))} · id ${esc(p.id)}</p>
    <div class="form-row">
      <button class="btn small" id="dWatch">${d.watch ? "Quitar de seguimiento" : "Añadir a seguimiento"}</button>
      <button class="btn small ghost" id="dAlert">Alerta de precio</button>
    </div>
    <div class="card"><h3>Evolución del precio</h3><div id="dChart" class="chart"></div></div>
    ${statBlock("ps")}${statBlock("pc")}
    <div class="card"><h3>Oportunidades para este jugador</h3>${oppsTable(d.opportunities)}
      ${Object.keys(d.skipped).length ? `<p class="hint">Descartadas: ${esc(Object.entries(d.skipped).map(([k, v]) => `${k} (${v})`).join(", "))}</p>` : ""}</div>`;
  const byPlat = (plat) => hist.items.filter((r) => r.platform === plat).map((r) => ({ t: r.observed_at, v: r.price }));
  lineChart($("#dChart"), [{ name: "Consola", color: "#38bdf8", points: byPlat("ps") }, { name: "PC", color: "#a78bfa", points: byPlat("pc") }],
    { label: `Precio de ${p.name}` });
  $("#dWatch").onclick = async () => {
    if (d.watch) await api(`/api/watchlist/${encodeURIComponent(pid)}`, { method: "DELETE" });
    else await api("/api/watchlist", { method: "POST", body: { player_id: pid } });
    toast(d.watch ? "Quitado de seguimiento" : "Añadido a seguimiento");
    openPlayer(pid);
  };
  $("#dAlert").onclick = () => {
    closeDrawer();
    switchTab("alerts");
    $("#aType").value = "price_below";
    $("#aPlayer").value = p.name;
    $("#alertForm").threshold.focus();
  };
  $("#drawer").classList.remove("hidden");
}
function closeDrawer() { $("#drawer").classList.add("hidden"); }

/* ---------------- seguimiento ---------------- */
async function loadWatch() {
  const data = await api("/api/watchlist");
  $("#watchTable").innerHTML = table(
    [{ label: "Jugador" }, { label: "Consola", num: true }, { label: "PC", num: true }, { label: "Actualizado" }, { label: "Objetivo compra/venta" }, { label: "" }],
    data.items.map((w) => {
      const ps = w.prices.ps, pc = w.prices.pc;
      const latest = Math.max(ps?.observed_at || 0, pc?.observed_at || 0);
      return `<tr><td class="click" data-player="${esc(w.player_id)}"><b>${esc(w.name || w.player_id)}</b> <span class="muted">${esc(w.rating ?? "")} ${esc(w.position ?? "")}</span></td>
        <td class="num">${fmt(ps?.price)}</td><td class="num">${fmt(pc?.price)}</td>
        <td class="muted">${latest ? `${dt(latest)} · ${esc((ps || pc).source)}` : "sin precio todavía"}</td>
        <td>${fmt(w.target_buy)} / ${fmt(w.target_sell)}</td>
        <td><button class="btn small danger" data-unwatch="${esc(w.player_id)}">Quitar</button></td></tr>`;
    }), { empty: "Tu lista está vacía. Abre un jugador y pulsa 'Añadir a seguimiento'." });
}

/* ---------------- alertas ---------------- */
function alertLogTable(items) {
  return table([{ label: "Cuándo" }, { label: "Alerta" }],
    items.map((a) => `<tr><td class="muted">${dt(a.fired_at)}</td><td>${a.acknowledged ? "" : "● "}${esc(a.message)}</td></tr>`),
    { empty: "Ninguna alerta disparada todavía." });
}

async function loadAlerts() {
  const [rules, log] = await Promise.all([api("/api/alerts/rules"), api("/api/alerts/log")]);
  $("#rulesTable").innerHTML = table([{ label: "Tipo" }, { label: "Jugador" }, { label: "Plat." }, { label: "Umbral", num: true }, { label: "Última vez" }, { label: "" }],
    rules.items.map((r) => `<tr><td>${esc(r.type)}</td><td>${esc(r.player_name || "—")}</td><td>${r.platform ? platLabel(r.platform) : "ambas"}</td>
      <td class="num">${fmt(r.threshold)}${r.window_hours ? ` / ${r.window_hours} h` : ""}</td><td class="muted">${dt(r.last_fired_at)}</td>
      <td><button class="btn small danger" data-delrule="${r.id}">Borrar</button></td></tr>`),
    { empty: "No hay reglas." });
  $("#alertLog").innerHTML = alertLogTable(log.items);
  notifyNew(log.items);
}

function notifyNew(items) {
  if (!items.length) return;
  const newest = items[0].id;
  if (state.lastAlertId !== null && newest > state.lastAlertId && $("#notifToggle").checked && "Notification" in window
      && Notification.permission === "granted") {
    items.filter((a) => a.id > state.lastAlertId).slice(0, 3).forEach((a) => new Notification("FC 27 Trader", { body: a.message }));
  }
  state.lastAlertId = Math.max(state.lastAlertId ?? 0, newest);
}

/* ---------------- operaciones ---------------- */
async function loadTrades() {
  const data = await api("/api/trades");
  const s = data.summary;
  $("#tradeKpis").innerHTML = [["Beneficio realizado", fmt(s.realized_profit)], ["Capital en operaciones abiertas", fmt(s.open_capital)],
    ["Cerradas / abiertas", `${s.closed} / ${s.open}`], ["Acierto", s.win_rate === null ? "—" : `${s.win_rate} %`]]
    .map(([l, v]) => `<div class="card kpi"><div class="label">${esc(l)}</div><div class="value">${v}</div></div>`).join("");
  $("#tradesTable").innerHTML = table(
    [{ label: "Jugador" }, { label: "Plat." }, { label: "Cant.", num: true }, { label: "Compra", num: true }, { label: "Venta", num: true },
      { label: "Impuesto", num: true }, { label: "Beneficio", num: true }, { label: "Estrategia" }, { label: "Fecha" }, { label: "" }],
    data.items.map((t) => `<tr><td>${esc(t.player_name || t.player_id || "—")}</td><td>${platLabel(t.platform)}</td><td class="num">${t.quantity}</td>
      <td class="num">${fmt(t.buy_price)}</td><td class="num">${t.sell_price ? fmt(t.sell_price) : `<button class="btn small ghost" data-sell="${t.id}">Registrar venta</button>`}</td>
      <td class="num">${fmt(t.tax)}</td><td class="num ${t.profit > 0 ? "pos" : t.profit < 0 ? "neg" : ""}">${fmt(t.profit)}</td>
      <td>${esc(t.strategy || "")}</td><td class="muted">${dt(t.sell_at || t.buy_at)}</td>
      <td><button class="btn small danger" data-deltrade="${t.id}">Borrar</button></td></tr>`),
    { empty: "Aún no has registrado operaciones." });
}

/* ---------------- eventos ---------------- */
async function loadEvents() {
  const data = await api("/api/events");
  $("#eventsTable").innerHTML = table([{ label: "Evento" }, { label: "Tipo" }, { label: "Empieza" }, { label: "Valoraciones" }, { label: "Jugadores" }, { label: "" }],
    data.items.map((e) => `<tr><td><b>${esc(e.name)}</b>${e.note ? `<div class="muted">${esc(e.note)}</div>` : ""}</td><td>${esc(e.kind)}</td>
      <td>${dt(e.starts_at)} <span class="muted">(${e.starts_at > Date.now() / 1000 ? "futuro" : "pasado"})</span></td>
      <td>${e.rating_min ? `${e.rating_min}–${e.rating_max || 99}` : "—"}</td><td>${e.player_ids.length}</td>
      <td><button class="btn small danger" data-delevent="${e.id}">Borrar</button></td></tr>`),
    { empty: "Sin eventos. Añade los SBC y promociones que se anuncien." });
}

/* ---------------- fuentes y ajustes ---------------- */
function fillSettings(cfg) {
  const f = $("#settingsForm");
  f.update_interval_minutes.value = cfg.update_interval_minutes;
  f.max_tracked_players.value = cfg.tracking.max_tracked_players;
  f.min_rating.value = cfg.tracking.min_rating;
  f.window_hours.value = cfg.analysis.window_hours;
  f.stale_after_minutes.value = cfg.analysis.stale_after_minutes;
}

async function loadSources() {
  const s = await loadStatus();
  $("#sourcesTable").innerHTML = table([{ label: "Fuente" }, { label: "Estado" }, { label: "Tipo" }, { label: "Último éxito" }, { label: "Peticiones", num: true }, { label: "Detalle" }],
    sourceRows(s.sources, true));
}

/* ---------------- navegación ---------------- */
const loaders = { overview: loadOverview, opps: loadOpps, players: loadPlayers, watch: loadWatch, alerts: loadAlerts,
  trades: loadTrades, events: loadEvents, sources: loadSources };
let currentTab = "overview";

function switchTab(name) {
  currentTab = name;
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  run(loaders[name]);
}

async function run(fn) {
  try { await fn(); } catch (err) { toast(`Error: ${err.message}`, 6000); console.error(err); }
}

function bind() {
  $("#tabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) switchTab(b.dataset.tab); });
  $("#platformSel").addEventListener("change", (e) => { state.platform = e.target.value; switchTab(currentTab); });
  $("#refreshBtn").addEventListener("click", () => run(async () => {
    await api("/api/update", { method: "POST" });
    toast("Actualización solicitada. Los datos aparecerán en unos segundos.");
    setTimeout(() => run(refresh), 4000);
  }));
  document.addEventListener("click", (e) => {
    const t = e.target;
    const row = t.closest("[data-player]");
    if (row && !t.closest("button")) return run(() => openPlayer(row.dataset.player));
    if (t.dataset.unwatch) return run(async () => { await api(`/api/watchlist/${encodeURIComponent(t.dataset.unwatch)}`, { method: "DELETE" }); loadWatch(); });
    if (t.dataset.delrule) return run(async () => { await api(`/api/alerts/rules/${t.dataset.delrule}`, { method: "DELETE" }); loadAlerts(); });
    if (t.dataset.deltrade) return run(async () => { if (confirm("¿Borrar esta operación?")) { await api(`/api/trades/${t.dataset.deltrade}`, { method: "DELETE" }); loadTrades(); } });
    if (t.dataset.delevent) return run(async () => { await api(`/api/events/${t.dataset.delevent}`, { method: "DELETE" }); loadEvents(); });
    if (t.dataset.sell) return run(async () => {
      const v = prompt("Precio de venta (por unidad):");
      if (v) { await api(`/api/trades/${t.dataset.sell}`, { method: "PUT", body: { sell_price: Number(v) } }); loadTrades(); }
    });
  });
  $("#drawerClose").onclick = closeDrawer;
  $("#drawer").addEventListener("click", (e) => { if (e.target.id === "drawer") closeDrawer(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

  $("#oRun").onclick = () => run(loadOpps);
  $("#oSave").onclick = () => run(async () => { await api("/api/settings", { method: "PUT", body: { strategy: profileFromForm() } }); toast("Perfil guardado"); await loadStatus(); });
  $("#pRun").onclick = () => run(loadPlayers);
  $("#pQ").addEventListener("keydown", (e) => { if (e.key === "Enter") run(loadPlayers); });
  $("#aType").onchange = () => { $("#aTypeHint").textContent = state.status.alert_types[$("#aType").value]; };

  $("#alertForm").onsubmit = (e) => { e.preventDefault(); run(async () => {
    const f = e.target, body = { type: f.type.value, platform: f.platform.value, threshold: Number(f.threshold.value), window_hours: f.window_hours.value || null };
    if (f.player.value) {
      const p = findPlayerByName(f.player.value);
      if (!p) throw new Error("Jugador no encontrado: búscalo antes en la pestaña Jugadores");
      body.player_id = p.id;
    }
    await api("/api/alerts/rules", { method: "POST", body });
    f.reset(); toast("Alerta creada"); loadAlerts();
  }); };
  $("#ackBtn").onclick = () => run(async () => { await api("/api/alerts/log/ack", { method: "POST" }); loadAlerts(); loadStatus(); });
  $("#notifToggle").onchange = (e) => { if (e.target.checked && "Notification" in window) Notification.requestPermission(); };

  $("#tradeForm").onsubmit = (e) => { e.preventDefault(); run(async () => {
    const f = e.target, p = findPlayerByName(f.player.value);
    await api("/api/trades", { method: "POST", body: { player_id: p?.id, player_name: p ? p.name : f.player.value, platform: f.platform.value,
      quantity: Number(f.quantity.value) || 1, buy_price: Number(f.buy_price.value), sell_price: f.sell_price.value ? Number(f.sell_price.value) : null,
      strategy: f.strategy.value } });
    f.reset(); toast("Operación guardada"); loadTrades();
  }); };

  $("#eventForm").onsubmit = (e) => { e.preventDefault(); run(async () => {
    const f = e.target;
    const ids = f.players.value.split(";").map((n) => n.trim()).filter(Boolean).map((n) => {
      const p = findPlayerByName(n); if (!p) throw new Error(`Jugador no encontrado: ${n}`); return p.id; });
    await api("/api/events", { method: "POST", body: { name: f.name.value, kind: f.kind.value, starts_at: new Date(f.starts_at.value).getTime() / 1000,
      rating_min: f.rating_min.value || null, rating_max: f.rating_max.value || null, player_ids: ids } });
    f.reset(); toast("Evento añadido"); loadEvents();
  }); };

  $("#calcForm").onsubmit = (e) => { e.preventDefault(); run(async () => {
    const f = e.target;
    const r = await api(`/api/calc?buy=${f.buy.value}&sell=${f.sell.value}&quantity=${f.quantity.value || 1}`);
    $("#calcOut").innerHTML = `<div class="stats">
      <div><span>Compra / venta (ajustadas)</span><b>${fmt(r.buy_price)} / ${fmt(r.sell_price)}</b></div>
      <div><span>Impuesto EA</span><b>${fmt(r.tax)}</b></div><div><span>Recibes</span><b>${fmt(r.net_sell)}</b></div>
      <div><span>Beneficio por unidad</span><b class="${r.profit_per_unit >= 0 ? "pos" : "neg"}">${fmt(r.profit_per_unit)}</b></div>
      <div><span>Margen</span><b>${r.margin_pct} %</b></div><div><span>Total (×${r.quantity})</span><b>${fmt(r.total_profit)}</b><span>capital ${fmt(r.capital)}</span></div>
      <div><span>Venta mínima sin pérdidas</span><b>${fmt(r.breakeven_sell)}</b></div></div><p class="hint">${esc(r.note)}</p>`;
  }); };

  $("#settingsForm").onsubmit = (e) => { e.preventDefault(); run(async () => {
    const f = e.target;
    await api("/api/settings", { method: "PUT", body: {
      update_interval_minutes: Number(f.update_interval_minutes.value),
      tracking: { max_tracked_players: Number(f.max_tracked_players.value), min_rating: Number(f.min_rating.value) },
      analysis: { window_hours: Number(f.window_hours.value), stale_after_minutes: Number(f.stale_after_minutes.value) } } });
    toast("Ajustes guardados"); loadSources();
  }); };

  $("#manualForm").onsubmit = (e) => { e.preventDefault(); run(async () => {
    const f = e.target, p = findPlayerByName(f.player.value);
    const r = await api("/api/prices/manual", { method: "POST", body: { player_id: p?.id, name: p ? undefined : f.player.value,
      platform: f.platform.value, price: Number(f.price.value), source: f.source.value || "manual" } });
    f.reset(); toast(r.saved ? "Precio guardado" : "Precio duplicado, no se guardó");
  }); };

  $("#csvFile").onchange = (e) => run(async () => {
    const file = e.target.files[0]; if (!file) return;
    const r = await api("/api/import/csv", { method: "POST", body: { csv: await file.text() } });
    $("#csvOut").innerHTML = `<p>${r.saved} precios guardados de ${r.rows} filas válidas.</p>` +
      (r.errors.length ? `<ul class="reasons">${r.errors.slice(0, 20).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "");
    e.target.value = "";
  });
}

async function refresh() {
  await loadStatus();
  await loaders[currentTab]();
}

(async function init() {
  bind();
  await run(async () => {
    await loadStatus();
    await loadMeta();
    const all = await api("/api/players?only_priced=0&limit=3000&platform=ps");
    all.items.forEach((p) => state.players.set(p.id, p));
    refreshDatalist();
    await loadOverview();
  });
  // Refresco periódico del panel (no consulta fuentes externas: solo lee la base local).
  setInterval(() => run(async () => { await loadStatus(); await loadAlerts(); if (currentTab === "overview") await loadOverview(); }), 60000);
})();
