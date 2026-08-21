"""Reglas de negocio para el ciclo de vida de períodos de inventario."""
from __future__ import annotations

from datetime import datetime

from .models import AjusteInventario, ConteoDetalle, InventarioPeriodo, db, utc_now


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
    periodo.fecha_cierre = utc_now()
    return True, pendientes


def registrar_conteo_admin(
    periodo: InventarioPeriodo,
    *,
    producto_nombre: str,
    categoria: str,
    cantidad: float,
    usuario: str,
    observacion: str = "",
):
    """Carga en períodos abiertos; en históricos crea un ajuste trazable."""
    conteo = ConteoDetalle.query.filter_by(
        periodo_id=periodo.id,
        producto_nombre=producto_nombre,
    ).first()
    es_historico = periodo.estado in (
        "Cerrado", "Excel Importado", "Conciliado", "Auditado"
    )
    if es_historico:
        if conteo is None:
            raise ValueError("No existe un conteo histórico que pueda ajustarse.")
        ajustes_previos = db.session.query(
            db.func.coalesce(db.func.sum(AjusteInventario.cantidad_ajustada), 0)
        ).filter_by(
            periodo_id=periodo.id,
            producto_nombre=producto_nombre,
            impacta_stock=True,
        ).scalar()
        actual = float(conteo.total_unidad_base or 0) + float(ajustes_previos or 0)
        ajuste = AjusteInventario(
            periodo_id=periodo.id,
            cliente_id=periodo.cliente_id,
            producto_nombre=producto_nombre,
            usuario_admin=usuario,
            cantidad_ajustada=float(cantidad) - actual,
            motivo="Corrección de carga",
            observacion=observacion or (
                f"Corrección trazable de conteo histórico: {actual:g} → {float(cantidad):g}."
            ),
            impacta_stock=True,
        )
        db.session.add(ajuste)
        return "ajuste", ajuste

    if conteo is None:
        conteo = ConteoDetalle(
            periodo_id=periodo.id,
            cliente_id=periodo.cliente_id,
            tienda_id=periodo.tienda_id,
            usuario=usuario,
            producto_nombre=producto_nombre,
            categoria=categoria,
            cantidad_unidad=cantidad,
            total_unidad_base=cantidad,
            fue_cargado=True,
        )
        db.session.add(conteo)
    else:
        conteo.total_unidad_base = cantidad
        conteo.cantidad_unidad = cantidad
        conteo.fue_cargado = True
        conteo.fecha_carga = utc_now()
        conteo.usuario = usuario
    if periodo.estado in ("Abierto", "Pendiente"):
        periodo.estado = "Cargado"
    return "conteo", conteo
