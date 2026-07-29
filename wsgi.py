"""
Punto de entrada WSGI para servidores de produccion (Gunicorn, uWSGI).

Uso con Gunicorn:
    gunicorn wsgi:application --workers 4 --bind 0.0.0.0:8000

Uso con uWSGI:
    uwsgi --http 0.0.0.0:8000 --module wsgi:application --processes 4
"""
import os
from dotenv import load_dotenv

# Cargar variables de entorno antes de importar la app
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"), override=True)

from app import app, init_db  # noqa: E402

# Inicializar base de datos si no existe
with app.app_context():
    init_db()

application = app
