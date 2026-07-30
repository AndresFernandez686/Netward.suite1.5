"""Utilidades de fecha/hora para usar una zona horaria local consistente."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def get_app_timezone():
    """Devuelve la zona horaria configurada para la app.

    Configurable con APP_TIMEZONE en entorno (ej: America/Asuncion).
    """
    tz_name = (os.getenv("APP_TIMEZONE") or "America/Asuncion").strip()
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def now_local() -> datetime:
    """Datetime actual en la zona horaria local de la app."""
    return datetime.now(tz=get_app_timezone())


def today_local_iso() -> str:
    """Fecha local en formato ISO YYYY-MM-DD."""
    return now_local().date().isoformat()


def now_local_time_str(fmt: str = "%H:%M:%S") -> str:
    """Hora local formateada."""
    return now_local().strftime(fmt)


def format_utc_naive_to_local(dt: datetime | None, fmt: str = "%d/%m/%y %H:%M") -> str | None:
    """Convierte datetime UTC (naive o aware) a hora local formateada."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(get_app_timezone()).strftime(fmt)
