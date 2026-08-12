# Guía de Deployment — Netward suite 1.3.1

## Ejecución local (desarrollo)

### Requisitos
- Python 3.11+ (recomendado 3.14)
- [uv](https://github.com/astral-sh/uv) o pip

### Pasos

```bash
git clone https://github.com/AndresFernandez686/Netward.suite1.3.1.git
cd Netward.suite1.3.1

# Con uv (recomendado)
uv venv
uv pip install -r requirements.txt
.venv/Scripts/python app.py       # Windows
.venv/bin/python app.py           # Linux / Mac

# Con pip clásico
python -m venv .venv
pip install -r requirements.txt
python app.py
```

La aplicación estará en `http://127.0.0.1:5000`
La base de datos SQLite se crea automáticamente en `instance/netward_empleado.db`.

---

## Variables de entorno (`.env`)

| Variable              | Default                          | Descripción               |
|-----------------------|----------------------------------|---------------------------|
| `SECRET_KEY`          | `netward-secret-key-beta-2025`   | Clave de sesión Flask     |
| `DATABASE_URL`        | `sqlite:///netward_empleado.db`  | URI de base de datos      |
| `HOST`                | `0.0.0.0`                        | Host del servidor         |
| `PORT`                | `5000`                           | Puerto                    |
| `FLASK_ENV`           | `development`                    | Modo (production = no debug) |

Crear `.env` en la raíz del proyecto:
```
SECRET_KEY=mi-clave-segura
FLASK_ENV=production
PORT=5000
```

---

## Deployment en producción (VPS / servidor propio)

### Con Gunicorn + Nginx

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

Configuración Nginx mínima:
```nginx
server {
    listen 80;
    server_name mi-dominio.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Con Render.com (gratuito)

1. Push al repositorio GitHub
2. Crear nuevo **Web Service** en [render.com](https://render.com)
3. Configurar:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app`
   - **Environment:** Python 3

### Con Railway

```bash
railway login
railway init
railway up
```

---

## Notas de producción

- La base de datos SQLite es suficiente para uso en tiendas individuales.
- Para múltiples tiendas concurrentes se recomienda migrar a PostgreSQL cambiando `DATABASE_URL`.
- El modo debug (`FLASK_ENV=development`) NO debe usarse en producción.
- Los archivos `.xls/.xlsx` subidos al módulo Desc. se procesan en memoria, no se almacenan en disco.

