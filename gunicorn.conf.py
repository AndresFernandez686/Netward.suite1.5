# gunicorn.conf.py — Configuracion de Gunicorn para produccion
# Referencia: https://docs.gunicorn.org/en/stable/settings.html

import multiprocessing
import os

# ── Binding ──────────────────────────────────────────────────────────────────
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# ── Workers ───────────────────────────────────────────────────────────────────
# Formula recomendada: (2 x CPU) + 1
workers = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "sync"          # usar "gevent" si instalas gevent
threads = 2                    # hilos por worker (solo para gthread/gevent)
worker_connections = 1000

# ── Timeouts ──────────────────────────────────────────────────────────────────
timeout = 120                  # segundos antes de reiniciar un worker bloqueado
keepalive = 5                  # segundos de keep-alive en conexiones persistentes

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog = "-"                # stdout
errorlog  = "-"                # stderr
loglevel  = os.getenv("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# ── Proceso ───────────────────────────────────────────────────────────────────
preload_app = True             # carga la app antes de hacer fork (ahorra RAM)
daemon = False                 # no daemonizar; usa systemd/supervisor para eso
