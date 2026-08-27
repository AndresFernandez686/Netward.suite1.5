"""Reglas de negocio para el ciclo de vida de períodos de inventario."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import or_

from .models import (
    AjusteInventario, ConteoDetalle, HistorialMovimiento, InventarioItem,
    InventarioPeriodo, InventarioSnapshot, db, utc_now,
)
from .ajustes import MOTIVOS_BAJA_NO_IMPUTABLE
from .time_utils import now_local_time_str, today_local_iso


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
    es_historico = periodo.estado in ("Cerrado", "Conciliado", "Auditado")
    if es_historico:
        if conteo is None:
            raise ValueError("No existe un conteo histórico que pueda ajustarse.")
        ajustes_previos = db.session.query(
            db.func.coalesce(db.func.sum(AjusteInventario.cantidad_ajustada), 0)
        ).filter_by(
            periodo_id=periodo.id,
            producto_nombre=producto_nombre,
            impacta_stock=True,
        ).filter(or_(
            AjusteInventario.motivo.is_(None),
            AjusteInventario.motivo.notin_(tuple(MOTIVOS_BAJA_NO_IMPUTABLE)),
        )).scalar()
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


def asegurar_conteo_admin(
    periodo: InventarioPeriodo, *, producto_nombre: str, categoria: str, usuario: str,
) -> ConteoDetalle:
    """Devuelve un conteo base; crea uno en cero si el ajuste incorpora el producto."""
    conteo = ConteoDetalle.query.filter_by(
        periodo_id=periodo.id, producto_nombre=producto_nombre,
    ).first()
    if conteo is None:
        ahora = utc_now()
        conteo = ConteoDetalle(
            periodo_id=periodo.id, cliente_id=periodo.cliente_id,
            tienda_id=periodo.tienda_id, usuario=usuario,
            producto_nombre=producto_nombre, categoria=categoria,
            cantidad_unidad=0, total_unidad_base=0, fue_cargado=True,
            primera_carga=ahora, fecha_carga=ahora,
        )
        db.session.add(conteo)
    else:
        conteo.fue_cargado = True
        conteo.categoria = categoria or conteo.categoria
        conteo.fecha_carga = utc_now()
    if periodo.estado in ("Abierto", "Pendiente"):
        periodo.estado = "Cargado"
    return conteo


def total_conteo_con_ajustes(periodo_id: int, producto_nombre: str) -> float:
    """Total efectivo usado por Auditoría y las vistas operativas."""
    conteo = ConteoDetalle.query.filter_by(
        periodo_id=periodo_id, producto_nombre=producto_nombre,
    ).first()
    base = float(conteo.total_unidad_base or 0) if conteo else 0.0
    ajustes = db.session.query(
        db.func.coalesce(db.func.sum(AjusteInventario.cantidad_ajustada), 0)
    ).filter_by(
        periodo_id=periodo_id, producto_nombre=producto_nombre, impacta_stock=True,
    ).filter(or_(
        AjusteInventario.motivo.is_(None),
        AjusteInventario.motivo.notin_(tuple(MOTIVOS_BAJA_NO_IMPUTABLE)),
    )).scalar()
    return base + float(ajustes or 0)


def registrar_estado_operativo_admin(
    periodo: InventarioPeriodo, *, producto_nombre: str, categoria: str,
    cantidad_final: float, usuario: str, detalle: str,
) -> HistorialMovimiento:
    """Refleja una carga administrativa en stock operativo y en Historial."""
    cantidad_final = float(cantidad_final)
    if cantidad_final < 0:
        raise ValueError("El ajuste dejaría el stock en negativo.")

    item = InventarioItem.query.filter_by(
        cliente_id=periodo.cliente_id, tienda_id=periodo.tienda_id,
        categoria=categoria, producto=producto_nombre,
    ).first()
    cantidad_anterior = float(item.cantidad or 0) if item else None
    usuario_anterior = item.usuario_ultima_carga if item else ""
    version = int(item.version or 1) + 1 if item else 1

    # No permitir que corregir un período antiguo pise el stock operativo de
    # un período posterior. El período elegido y su Auditoría sí se actualizan.
    ultimo_periodo = (
        InventarioPeriodo.query
        .filter_by(cliente_id=periodo.cliente_id, tienda_id=periodo.tienda_id)
        .order_by(InventarioPeriodo.numero.desc(), InventarioPeriodo.id.desc())
        .first()
    )
    if ultimo_periodo is None or ultimo_periodo.id == periodo.id:
        if item is None:
            item = InventarioItem(
                cliente_id=periodo.cliente_id, tienda_id=periodo.tienda_id,
                categoria=categoria, producto=producto_nombre,
            )
            db.session.add(item)
        item.cantidad = cantidad_final
        item.ume = "Unidad"
        item.tipo_inventario = "Diario"
        item.fecha = today_local_iso()
        item.sinc_estado = "sincronizado"
        item.periodo_id = periodo.id
        item.usuario_ultima_carga = usuario
        item.version = version
        item.fue_sobreescrito = cantidad_anterior is not None

    fecha = today_local_iso()
    snapshot = InventarioSnapshot.query.filter_by(
        cliente_id=periodo.cliente_id, tienda_id=periodo.tienda_id,
        usuario=usuario, fecha=fecha,
    ).first()
    if snapshot is None:
        snapshot = InventarioSnapshot(
            cliente_id=periodo.cliente_id, tienda_id=periodo.tienda_id,
            usuario=usuario, fecha=fecha, tipo_inventario="Diario", total_items=0,
        )
        db.session.add(snapshot)
        db.session.flush()

    movimiento = HistorialMovimiento(
        cliente_id=periodo.cliente_id, tienda_id=periodo.tienda_id,
        fecha=fecha, hora=now_local_time_str(), usuario=usuario,
        categoria=categoria, producto=producto_nombre, cantidad=cantidad_final,
        modo="Unidad", tipo_inventario="Diario", detalle=detalle[:255],
        snapshot_id=snapshot.id, periodo_id=periodo.id,
        tipo_movimiento="sobreescritura" if cantidad_anterior is not None else "original",
        usuario_anterior=usuario_anterior, cantidad_anterior=cantidad_anterior,
        version=version,
    )
    db.session.add(movimiento)
    db.session.flush()
    snapshot.total_items = db.session.query(HistorialMovimiento.producto).filter_by(
        snapshot_id=snapshot.id,
    ).distinct().count()
    return movimiento
