"""
scheduler.py — Cierre automático de períodos de inventario.

Usa APScheduler para revisar periódicamente qué períodos superaron su
fecha_hasta + horas_extra (configurable por cliente) y los cierra solos.
El job se registra en app.py al iniciar la aplicación.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .models import db, InventarioPeriodo, ConfiguracionSistema, ConteoDetalle, utc_now
from .time_utils import get_app_timezone, now_local

# ── Constantes ──────────────────────────────────────────────────────────────
CLAVE_AUTOCLOSE = "autoclose_horas"
DEFAULT_AUTOCLOSE_HORAS = 0          # por defecto, cierra al llegar fecha_hasta
ESTADOS_ACTIVOS = ("Abierto", "Pendiente", "Cargado", "Sincronizado")


def _horas_autoclose(cliente_id: str) -> float:
    """Lee el valor configurado de autoclose_horas para el cliente."""
    cfg = ConfiguracionSistema.query.filter_by(
        cliente_id=cliente_id, clave=CLAVE_AUTOCLOSE
    ).first()
    if cfg:
        try:
            return float(cfg.valor)
        except (ValueError, TypeError):
            pass
    return DEFAULT_AUTOCLOSE_HORAS


def actualizar_estados_periodos(
    cliente_id: str | None = None,
    tienda_id: str | None = None,
    ahora=None,
) -> tuple[int, int]:
    """Promueve cargas reales y cierra períodos que alcanzaron su fecha fin."""
    q = InventarioPeriodo.query
    if cliente_id:
        q = q.filter_by(cliente_id=cliente_id)
    if tienda_id:
        q = q.filter_by(tienda_id=tienda_id)

    periodos = q.filter(InventarioPeriodo.estado.in_(ESTADOS_ACTIVOS)).all()
    ahora_local = ahora or now_local()
    if ahora_local.tzinfo is None:
        ahora_local = ahora_local.replace(tzinfo=get_app_timezone())

    cargados = 0
    cerrados = 0
    for p in periodos:
        horas = _horas_autoclose(p.cliente_id)
        try:
            limite = datetime.fromisoformat(p.fecha_hasta).replace(
                tzinfo=get_app_timezone()
            ) + timedelta(hours=horas)
        except ValueError:
            continue

        if ahora_local >= limite:
            p.estado = "Cerrado"
            p.fecha_cierre = utc_now()
            cerrados += 1
            continue

        # Normaliza períodos antiguos que quedaron como Pendiente aunque ya
        # contienen al menos un conteo real del empleado.
        if p.estado in ("Abierto", "Pendiente", "Sincronizado"):
            tiene_carga = ConteoDetalle.query.filter_by(
                periodo_id=p.id,
                fue_cargado=True,
            ).first() is not None
            if tiene_carga:
                p.estado = "Cargado"
                cargados += 1

    if cargados or cerrados:
        db.session.commit()
    return cargados, cerrados


def job_autoclose_periodos(app) -> None:
    """
    Job que corre cada 30 minutos.
    Cierra todos los períodos cuya fecha_hasta + horas_autoclose ya pasó.
    """
    with app.app_context():
        actualizar_estados_periodos()


def get_autoclose_horas(cliente_id: str) -> float:
    return _horas_autoclose(cliente_id)


def set_autoclose_horas(cliente_id: str, horas: float) -> None:
    """Guarda o actualiza la configuración de auto-cierre para el cliente."""
    cfg = ConfiguracionSistema.query.filter_by(
        cliente_id=cliente_id, clave=CLAVE_AUTOCLOSE
    ).first()
    if cfg:
        cfg.valor = str(horas)
    else:
        cfg = ConfiguracionSistema(
            cliente_id=cliente_id,
            clave=CLAVE_AUTOCLOSE,
            valor=str(horas),
            descripcion="Horas tras fecha_hasta para cerrar el período automáticamente",
        )
        db.session.add(cfg)
    db.session.commit()
