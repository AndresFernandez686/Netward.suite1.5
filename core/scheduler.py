"""
scheduler.py — Cierre automático de períodos de inventario.

Usa APScheduler para revisar periódicamente qué períodos superaron su
fecha_hasta + horas_extra (configurable por cliente) y los cierra solos.
El job se registra en app.py al iniciar la aplicación.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .models import db, InventarioPeriodo, ConfiguracionSistema

# ── Constantes ──────────────────────────────────────────────────────────────
CLAVE_AUTOCLOSE = "autoclose_horas"
DEFAULT_AUTOCLOSE_HORAS = 24         # si no hay config, se usan 24 h
ESTADOS_ACTIVOS = ("Abierto", "Pendiente", "Sincronizado")


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


def job_autoclose_periodos(app) -> None:
    """
    Job que corre cada 30 minutos.
    Cierra todos los períodos cuya fecha_hasta + horas_autoclose ya pasó.
    """
    with app.app_context():
        ahora = datetime.utcnow()

        periodos = (
            InventarioPeriodo.query
            .filter(InventarioPeriodo.estado.in_(ESTADOS_ACTIVOS))
            .all()
        )

        cerrados = 0
        for p in periodos:
            horas = _horas_autoclose(p.cliente_id)
            try:
                limite = datetime.fromisoformat(p.fecha_hasta) + timedelta(hours=horas)
            except ValueError:
                continue   # fecha_hasta inválida, se omite

            if ahora >= limite:
                p.estado = "Cerrado"
                p.fecha_cierre = ahora
                cerrados += 1

        if cerrados:
            db.session.commit()


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
