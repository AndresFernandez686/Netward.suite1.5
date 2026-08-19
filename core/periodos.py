"""Reglas de negocio para el ciclo de vida de períodos de inventario."""
from __future__ import annotations

from datetime import datetime

from .models import ConteoDetalle, InventarioPeriodo


def cerrar_periodo(
    periodo: InventarioPeriodo,
    *,
    forzar: bool = False,
) -> tuple[bool, list[str]]:
    """Cierra el período solo si no quedan productos pendientes de carga.

    Devuelve ``(cerrado, productos_pendientes)``. La transacción queda a cargo
    del llamador para que la misma regla pueda usarse desde HTTP, tareas y tests.
    """
    pendientes = [
        conteo.producto_nombre
        for conteo in ConteoDetalle.query.filter_by(
            periodo_id=periodo.id,
            fue_cargado=False,
        ).all()
    ]

    if pendientes and not forzar:
        return False, pendientes

    periodo.estado = "Cerrado"
    periodo.fecha_cierre = datetime.utcnow()
    return True, pendientes
