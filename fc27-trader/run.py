#!/usr/bin/env python3
"""Arranca el asistente de trading de FC 27.

    python run.py            # modo real (FUT-DB + entrada manual/CSV)
    python run.py --demo     # datos sintéticos de demostración, en otra base de datos
    python run.py --once     # un ciclo de actualización y salir (útil para cron)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import webbrowser

from trader.config import load_config
from trader.server import App, make_server


def seed_demo_event(app: App) -> None:
    if app.db.one("SELECT 1 FROM events LIMIT 1"):
        return
    app.db.execute(
        "INSERT INTO events(name, kind, starts_at, player_ids, rating_min, rating_max, note, created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        ("[DEMO] SBC ficticio de valoración 85-86", "sbc", time.time() + 2 * 86400, "[]", 85, 86,
         "Evento de demostración: no existe en el juego.", time.time()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Asistente de trading EA SPORTS FC 27 (análisis y simulación)")
    ap.add_argument("--config", help="Ruta a config.json")
    ap.add_argument("--demo", action="store_true", help="Usar datos de demostración sintéticos")
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--once", action="store_true", help="Ejecutar un ciclo de actualización y salir")
    ap.add_argument("--open", action="store_true", help="Abrir el panel en el navegador")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    app = App(cfg, demo=args.demo)
    if args.demo:
        seed_demo_event(app)

    if args.once:
        summary = app.updater.run_once()
        print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
        return 0

    host = args.host or cfg["server"]["host"]
    port = args.port or cfg["server"]["port"]
    server = make_server(app, host, port)
    app.updater.start()
    url = f"http://{host}:{port}/"
    mode = "DEMO (datos sintéticos)" if args.demo else "REAL"
    print(f"Panel en {url}  ·  modo {mode}  ·  Ctrl+C para salir")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.updater.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
