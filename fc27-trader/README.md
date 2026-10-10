# FC 27 Trader: asistente de trading para EA SPORTS FC 27 Ultimate Team

Herramienta local de **análisis y simulación** del mercado de Ultimate Team: guarda precios de
fuentes autorizadas, construye su historial, detecta oportunidades, calcula el beneficio neto
tras el impuesto de EA y lanza alertas. **No compra, no vende, no puja y no pide credenciales
de EA**: las decisiones y las operaciones las haces tú en el juego.

- Python 3.10+ y **solo la biblioteca estándar** (sin `pip install`).
- Panel web local en `http://127.0.0.1:8027`.
- Modo real (FUT-DB + entrada manual/CSV) y modo demostración separado y etiquetado.

---

## 1. Fuentes de datos: qué se comprobó y qué se usa

Antes de programar se comprobó cada fuente (10/10/2026):

| Fuente | Resultado de la comprobación | Uso en la app |
|---|---|---|
| **FUT-DB** (`api.futdatabase.com`) | API REST pública y documentada (OpenAPI, versión "27"), autenticación con cabecera `X-AUTH-TOKEN`. Catálogo (jugadores, ligas, nacionalidades, clubes, rarezas) en el plan gratuito. **Precio actual solo en plan premium**: consola (`playstation`) y PC, con `minPrice`/`maxPrice` (rango de precios de EA) y `priceUpdate`. **No tiene endpoint de historial.** | **Fuente automática principal.** Necesita tu token; los precios necesitan plan premium. |
| **FUTBIN** | Sin API pública. La web devuelve un desafío de Cloudflare (HTTP 403 "Just a moment…") a clientes automatizados. | **No se consulta.** Consultarla exigiría eludir esa protección. |
| **FUT.GG** | Los Términos de Servicio (Stormstrike Inc., actualizados el 13/05/2026) prohíben "use any automated means (such as bots, scrapers, or crawlers) to access our Services, except where expressly permitted", y `robots.txt` bloquea `/api/*`. | **No se consulta.** |
| **Entrada manual / CSV** | Los precios que ves tú (en el juego, en la app web de EA o en cualquier web) y anotas o importas. | Fuente real, marcada como "introducida por el usuario". |

Consecuencias que conviene tener claras:

1. **Sin token de FUT-DB premium no hay precios automáticos.** La app lo indica en
   *Fuentes y ajustes* y no inventa datos: puedes trabajar con precios manuales/CSV o con el modo demo.
2. **El historial empieza el día que arrancas la app.** Ninguna fuente autorizada ofrece
   historial, así que las tendencias, la probabilidad y el tiempo de venta solo aparecen cuando
   hay datos suficientes (por defecto ≥ 12 precios en ≥ 6 h). También puedes importar un historial
   propio en CSV.
3. **No hay volumen de ventas** en ninguna fuente autorizada. La "liquidez" es un proxy (cambios
   de precio por día) y se etiqueta como tal.
4. **No hay calendario oficial de SBC y eventos** accesible de forma autorizada. Los introduces tú
   en *Eventos / SBC* y la estrategia "previa a evento" los usa.
5. **Diferencias entre plataformas**: FUT-DB da consola y PC. Se muestran como información, porque
   las monedas no se pueden pasar de una plataforma a otra.

## 2. Arquitectura

```
                    ┌─────────────────────────── trader/sources ───────────────────────────┐
                    │ FutDBSource (API, token)   ManualSource (panel/CSV)   DemoSource      │
                    │ FutbinSource / FutGGSource: registradas como "no disponibles" + motivo│
                    └───────────────┬──────────────────────────────────────────────────────┘
                                    │ PriceQuote(player, plataforma, precio, rango EA, fuente, hora)
┌──────────── updater.py ───────────▼──────────────┐
│ hilo en segundo plano cada N min                 │
│ · límite de peticiones (cubo de fichas)          │
│ · reintentos con espera exponencial (5xx, red)   │
│ · 429 → respeta Retry-After                      │
│ · cortacircuitos tras 3 fallos (máx. 6 h)        │
│ · 401/403 → detiene la fuente y lo muestra       │
│ · seguimiento primero + rotación del resto       │
└───────────────┬──────────────────────────────────┘
                ▼
        db.py (SQLite: players, prices, watchlist, alert_rules, alert_log,
               trades, events, source_status, update_runs, settings)
                │
     ┌──────────┴──────────────┐
     ▼                         ▼
analysis.py                alerts.py
· estadísticas por carta   · precio por debajo de X
· oportunidades por        · subida/caída de X % en N h
  estrategia               · diferencia consola/PC
· beneficio neto           · caída del mercado
  (market.py: impuesto,    · oportunidad con beneficio ≥ X
  tramos, rango EA)        · enfriamiento anti-spam
· riesgo, probabilidad,
  tiempo de venta
     │
     ▼
server.py (API JSON + archivos estáticos) ──► static/ (panel: index.html, app.js, styles.css)
```

| Archivo | Responsabilidad |
|---|---|
| `run.py` | Punto de entrada (`--demo`, `--once`, `--port`, `--config`). |
| `trader/config.py` | Valores por defecto, `config.json` y variable `FUTDB_TOKEN`. |
| `trader/market.py` | Reglas del mercado: impuesto del 5 %, incrementos de precio, precio mínimo, punto de equilibrio. Configurable. |
| `trader/sources/` | Una clase por fuente con la misma interfaz (`base.py`). |
| `trader/updater.py` | Actualización periódica, límites, reintentos, cortacircuitos y estado de cada fuente. |
| `trader/analysis.py` | Motor de análisis y estrategias. |
| `trader/alerts.py` | Reglas de alerta y su evaluación. |
| `trader/server.py` | API HTTP y servidor del panel. |
| `tests/` | 47 pruebas (`unittest`). |

### Añadir una fuente nueva

1. Crea `trader/sources/mi_fuente.py` con una subclase de `PriceSource`:
   `availability()`, `fetch_catalog()` (opcional) y `fetch_prices(ids)` → `PriceQuote` o `SourceError`.
2. Identifica sus jugadores como `"mi_fuente:<id>"`.
3. Añádela en `build_sources()` (`trader/sources/__init__.py`).

El actualizador, el estado en el panel, los límites y el cortacircuitos funcionan sin más cambios.

## 3. Motor de análisis: dato real frente a estimación

Para cada carta y plataforma, sobre la ventana de análisis (72 h por defecto):

- **Dato real** (columna azul en el panel): último precio, su **fuente** y su **hora**, rango de precios de EA.
- **Estadísticas**: mediana, percentiles 20/80, mínimo y máximo, volatilidad (coeficiente de
  variación), pendiente de tendencia (regresión de log-precio, en %/día) a corto plazo y en la ventana,
  y cambios de precio por día.
- **Frescura**: `reciente` (≤ 60 min), `desactualizado`, `caducado` (> 24 h). Las cartas caducadas no
  generan oportunidades.

**Estimaciones** (columna naranja), siempre etiquetadas:

| Campo | Cómo se calcula | Cuándo vale "n/d" |
|---|---|---|
| Precio de compra | Mín.(actual, p20), ajustado a un precio válido del mercado | — |
| Precio de venta | Según la estrategia (mediana, p80 o proyección prudente), ajustado al rango de EA | — |
| Beneficio neto | `venta − 5 % (redondeado a la baja) − compra` | — |
| Margen, capital | Margen sobre la compra; cantidad según presupuesto y perfil de riesgo | — |
| Probabilidad | Frecuencia histórica: de las veces que el precio estuvo ≤ compra, cuántas llegó a ≥ venta dentro del horizonte (24 h para flipping) | Menos de 5 episodios comparables |
| Tiempo de venta | Mediana del tiempo hasta alcanzar la venta en esos episodios | Menos de 3 episodios con éxito |
| Riesgo (0-100) | Volatilidad, tendencia bajista, historial corto, antigüedad del dato y peso en el presupuesto | — |

La probabilidad se basa en **precios publicados, no en ventas confirmadas**; tómala como orientativa.

### Estrategias

| Clave | Lógica |
|---|---|
| `flip` | Comprar en la zona baja habitual (p20) y vender a la mediana. No se propone con tendencia bajista. |
| `dip` | Precio actual ≥ 8 % bajo la mediana, sin tendencia bajista de fondo. |
| `trend` | Tendencia alcista sostenida; objetivo con la mitad de la pendiente observada y tope de +25 %. |
| `pre_event` | La carta encaja (por id o por valoración) con un evento futuro que has introducido; objetivo p80. |
| `liquidity` | Flipping solo en cartas con mucha actividad de precio (≥ 24 cambios/día). |

**Perfiles**: riesgo `low` / `medium` / `high` (riesgo máximo, probabilidad mínima y % del presupuesto
por operación) y tiempo `short` / `medium` / `long` (horizonte y estrategias adecuadas). El presupuesto
limita el capital por operación. Todo se ajusta en *Oportunidades* y se guarda con "Guardar perfil".

## 4. Panel

- **Panel**: indicadores, índice de mercado (base 100), estado de las fuentes, mejores oportunidades, tendencias y alertas.
- **Oportunidades**: filtros de presupuesto, riesgo, tiempo, beneficio mínimo y estrategias; motivos de
  cada propuesta, recuento de descartes y por qué; diferencias consola/PC.
- **Jugadores**: buscador con filtros de posición, liga, nacionalidad, rareza, valoración, precio y
  plataforma. Ficha con gráfico de evolución (consola y PC), estadísticas y oportunidades.
- **Seguimiento**: tu lista. Estos jugadores se consultan primero en cada ciclo.
- **Alertas**: reglas, historial y notificaciones del navegador (opcional).
- **Operaciones**: registro de compras y ventas con beneficio neto real tras impuestos y porcentaje de acierto.
- **Eventos / SBC**: calendario que alimenta la estrategia previa a evento.
- **Fuentes y ajustes**: estado de cada fuente (último éxito, errores, peticiones), calculadora de beneficio,
  ajustes, entrada manual de precios e importación CSV.

## 5. Instalación y configuración

```bash
cd fc27-trader
python3 --version            # 3.10 o superior
python3 -m unittest discover -s tests -t .   # opcional: 47 pruebas, ~2 s
```

**Probar sin datos reales (demo):**

```bash
python3 run.py --demo --open
```

Crea `data/demo.db` con 36 jugadores ficticios ("[DEMO] …") y 7 días de precios sintéticos. Un aviso
naranja permanente lo indica. Nunca se mezcla con la base de datos real.

**Modo real con FUT-DB:**

1. Crea una cuenta en <https://www.futdatabase.com> y obtén tu token de API. Los precios requieren el plan premium.
2. `cp config.example.json config.json` y pega el token en `sources.futdb.token`, o exporta
   `FUTDB_TOKEN=tu_token` (tiene prioridad y evita guardarlo en disco).
3. Ajusta `tracking.max_tracked_players` y `sources.futdb.max_requests_per_minute` a los límites de tu
   plan. La API pide **una petición por jugador**: con 150 jugadores y un ciclo de 15 min son unas
   600 peticiones por hora.
4. `python3 run.py --open`

La primera ejecución sincroniza el catálogo (se repite cada 24 h) y empieza a guardar precios.
Las oportunidades aparecen cuando cada carta acumula historial suficiente.

**Sin token**: `python3 run.py` funciona igual. Añade precios en *Fuentes y ajustes* o importa un CSV
(formato en `sample_prices.csv`).

**Ejecución programada** (sin panel): `python3 run.py --once` hace un ciclo y sale (para cron o el Programador de tareas).

Opciones principales de `config.json` (las de análisis y estrategia también se pueden cambiar en el panel):

| Clave | Por defecto | Significado |
|---|---|---|
| `update_interval_minutes` | 15 | Intervalo de actualización |
| `tracking.max_tracked_players` / `min_rating` | 150 / 84 | Qué jugadores se consultan en cada ciclo |
| `market.tax_rate` / `min_price` / `tiers` | 0.05 / 150 / tramos FUT | Reglas del mercado. Compruébalas en FC 27. |
| `analysis.window_hours` | 72 | Ventana de estadísticas |
| `analysis.min_samples` / `min_span_hours` | 12 / 6 | Mínimo de datos para analizar una carta |
| `analysis.stale_after_minutes` / `exclude_after_hours` | 60 / 24 | Frescura |
| `strategy.*` | — | Presupuesto, riesgo, tiempo, estrategias, beneficio y margen mínimos |
| `alerts.cooldown_minutes` | 60 | Tiempo mínimo entre dos avisos de la misma regla |

## 6. Pruebas

```bash
python3 -m unittest discover -s tests -t . -v
```

Cubren: reglas del mercado (impuesto, tramos, punto de equilibrio), estadísticas y frescura,
probabilidad por episodios, estrategias (incluidos los rechazos por impuesto, presupuesto, tendencia
bajista, datos insuficientes o caducados), alertas y enfriamiento, el adaptador FUT-DB con un transporte
simulado que reproduce las respuestas de su especificación (mapeo de catálogo y precios, 401/403,
429 con `Retry-After`, reintentos 5xx y errores de red), límite de peticiones, actualizador
(prioridad de seguimiento, rotación, cortacircuitos, recuperación tras reinicio), importación CSV
y la API HTTP completa.

**Con datos reales**: sin un token premium no se han podido verificar precios reales. Sí se comprobó
contra el servidor real de FUT-DB que la especificación es la versión "27" y que un token inválido
produce `HTTP 401`, que la app detecta y muestra como error de autenticación sin reintentar en bucle.

## 7. Límites y seguridad

- Solo lectura de fuentes autorizadas; no se eluden CAPTCHAs, Cloudflare ni ninguna otra protección.
- No se piden ni se guardan credenciales ni cookies de EA, y no se automatiza ninguna acción del juego
  (automatizar el mercado incumple el acuerdo de usuario de EA y puede acabar en la suspensión de la cuenta).
- El token de FUT-DB nunca se muestra en el panel ni en la API (`"configurado"`).
- El servidor escucha solo en `127.0.0.1`; no lo expongas a Internet: no tiene autenticación.
- Nada de esto es asesoramiento financiero: el mercado de FUT cambia con los contenidos de EA, y las
  estimaciones se basan en el pasado.
