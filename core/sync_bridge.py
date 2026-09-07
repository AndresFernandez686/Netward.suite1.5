"""
Puente de sincronización: propaga los InventarioItem del empleado a ConteoDetalle
del período activo. Funciona en dos sentidos:

1. Al sincronizar (tiempo real): propaga items pendientes al período activo.
2. Al crear período (retroactivo): jala items ya sincronizados dentro del rango
   de fechas, para no perder cargas que ocurrieron antes de que el período existiera.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional
from sqlalchemy import or_

from .models import (
    db, InventarioPeriodo, ConteoDetalle, InventarioItem,
    HistorialMovimiento, utc_now,
)


def sincronizar_transaccional(
    *,
    cliente_id: str,
    tienda_id: str,
    usuario: str,
    accion: str,
    periodo: Optional[InventarioPeriodo] = None,
    antes_commit: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Propaga y sincroniza como una unidad atómica; cualquier fallo revierte todo."""
    from . import empleado as empleado_service

    try:
        if periodo is not None:
            propagar_conteo_a_periodo(
                tienda_id=tienda_id,
                cliente_id=cliente_id,
                usuario=usuario,
                periodo_id=periodo.id,
            )
            db.session.flush()

        resumen = empleado_service.procesar_sincronizacion(
            cliente_id=cliente_id,
            tienda_id=tienda_id,
            usuario=usuario,
            accion=accion,
            periodo_id=periodo.id if periodo is not None else None,
        )
        db.session.flush()
        if antes_commit is not None:
            antes_commit(resumen)
        db.session.commit()
        return resumen
    except Exception:
        db.session.rollback()
        raise


def _norm(s: str) -> str:
    return s.strip().lower()


def _upsert_conteo(periodo: InventarioPeriodo, nombre: str, categoria: str,
                   total: float, usuario: str, *, fue_sobreescrito=False,
                   version_ultima_carga=1) -> None:
    """
    Regla: ÚLTIMO GANA.
    Si el empleado sincroniza más de una vez en el mismo período,
    el valor más reciente reemplaza al anterior.
    primera_carga nunca se sobreescribe; veces_sincronizado se incrementa.
    """
    cd = ConteoDetalle.query.filter_by(
        periodo_id=periodo.id, producto_nombre=nombre
    ).first()
    if cd:
        cd.total_unidad_base = total
        cd.cantidad_unidad = total
        cd.fue_cargado = True
        cd.fecha_carga = utc_now()
        cd.usuario = usuario
        cd.veces_sincronizado = (cd.veces_sincronizado or 1) + 1
        cd.fue_sobreescrito = bool(fue_sobreescrito)
        cd.version_ultima_carga = int(version_ultima_carga or 1)
        # primera_carga NO se modifica — conserva el timestamp original
    else:
        ahora = utc_now()
        cd = ConteoDetalle(
            periodo_id=periodo.id,
            cliente_id=periodo.cliente_id,
            tienda_id=periodo.tienda_id,
            usuario=usuario,
            producto_nombre=nombre,
            categoria=categoria,
            cantidad_unidad=total,
            cantidad_caja=0,
            cantidad_bulto=0,
            total_unidad_base=total,
            fue_cargado=True,
            primera_carga=ahora,
            fecha_carga=ahora,
            veces_sincronizado=1,
            fue_sobreescrito=bool(fue_sobreescrito),
            version_ultima_carga=int(version_ultima_carga or 1),
        )
        db.session.add(cd)


def propagar_conteo_a_periodo(
    tienda_id: str,
    cliente_id: str,
    usuario: str,
    periodo_id: int | None = None,
) -> int:
    """
    Al sincronizar: toma los InventarioItem en estado 'pendiente' y los copia
    al período activo (Abierto, Pendiente o Cargado) de la tienda.
    Retorna la cantidad de filas insertadas/actualizadas.
    """
    if periodo_id is not None:
        periodo = db.session.get(InventarioPeriodo, int(periodo_id))
        if not periodo:
            return 0
        if periodo.cliente_id != cliente_id or periodo.tienda_id != tienda_id:
            return 0
        if periodo.estado not in ("Abierto", "Pendiente", "Cargado"):
            return 0
    else:
        periodo = (
            InventarioPeriodo.query
            .filter_by(cliente_id=cliente_id, tienda_id=tienda_id)
            .filter(InventarioPeriodo.estado.in_(["Abierto", "Pendiente", "Cargado"]))
            .order_by(InventarioPeriodo.id.desc())
            .first()
        )
    if not periodo:
        return 0

    items = (
        InventarioItem.query
        .filter_by(
            cliente_id=cliente_id,
            tienda_id=tienda_id,
            sinc_estado="pendiente",
            periodo_id=periodo.id,
        )
        .filter(or_(
            InventarioItem.usuario_ultima_carga == usuario,
            InventarioItem.usuario_ultima_carga == "",
            InventarioItem.usuario_ultima_carga.is_(None),
        ))
        .all()
    )

    count = 0
    for item in items:
        _upsert_conteo(
            periodo,
            item.producto,
            item.categoria,
            float(item.cantidad or 0),
            item.usuario_ultima_carga or usuario,
            fue_sobreescrito=item.fue_sobreescrito,
            version_ultima_carga=item.version,
        )
        count += 1

    if count > 0 and periodo.estado in ("Abierto", "Pendiente"):
        periodo.estado = "Cargado"

    return count


def retroalimentar_periodo_desde_items(periodo: InventarioPeriodo) -> int:
    """
    Al crear un período:
    1. Crea un placeholder fue_cargado=False para TODOS los productos visibles.
    2. Sobreescribe con fue_cargado=True los que tienen historial en el rango.
    Esto garantiza que la validación de cierre pueda distinguir
    'cargado con 0' de 'nunca cargado'.
    """
    from .models import Producto

    # Paso 1: placeholder fue_cargado=False para todos los productos activos visibles
    productos_visibles = Producto.query.filter_by(visible_empleado=True).all()
    for p in productos_visibles:
        existente = ConteoDetalle.query.filter_by(
            periodo_id=periodo.id, producto_nombre=p.nombre
        ).first()
        if not existente:
            db.session.add(ConteoDetalle(
                periodo_id=periodo.id,
                cliente_id=periodo.cliente_id,
                tienda_id=periodo.tienda_id,
                usuario="sistema",
                producto_nombre=p.nombre,
                categoria=p.categoria,
                cantidad_unidad=0,
                cantidad_caja=0,
                cantidad_bulto=0,
                total_unidad_base=0,
                fue_cargado=False,   # pendiente de carga real
            ))
    db.session.flush()

    # Paso 2: llenar con datos reales del historial dentro del rango
    movimientos = (
        HistorialMovimiento.query
        .filter_by(cliente_id=periodo.cliente_id, tienda_id=periodo.tienda_id)
        .filter(HistorialMovimiento.fecha >= periodo.fecha_desde)
        .filter(HistorialMovimiento.fecha <= periodo.fecha_hasta)
        .all()
    )

    if not movimientos:
        # Fallback: InventarioItem sincronizados actuales
        items = InventarioItem.query.filter_by(
            cliente_id=periodo.cliente_id,
            tienda_id=periodo.tienda_id,
            sinc_estado="sincronizado",
        ).all()
        for item in items:
            _upsert_conteo(periodo, item.producto, item.categoria,
                           float(item.cantidad or 0), item.usuario_ultima_carga or "sistema",
                           fue_sobreescrito=item.fue_sobreescrito,
                           version_ultima_carga=item.version)
        importados = len(items)
    else:
        from collections import defaultdict
        # Agrupar por producto tomando el movimiento más reciente (último snapshot gana).
        # Se prioriza snapshot_id DESC cuando existe; si no, se usa (fecha DESC, creado DESC).
        por_producto = {}
        for m in movimientos:
            k = m.producto
            if k not in por_producto:
                por_producto[k] = m
            else:
                prev = por_producto[k]
                # Comparar: snapshot_id más alto > fecha más reciente > creado más reciente
                m_snap   = m.snapshot_id or 0
                prev_snap = prev.snapshot_id or 0
                if m_snap > prev_snap:
                    por_producto[k] = m
                elif m_snap == prev_snap and (m.fecha, m.creado) > (prev.fecha, prev.creado):
                    por_producto[k] = m

        for nombre, m in por_producto.items():
            _upsert_conteo(periodo, nombre, m.categoria,
                           float(m.cantidad or 0), m.usuario)
        importados = len(por_producto)

    if importados > 0 and periodo.estado in ("Abierto", "Pendiente"):
        periodo.estado = "Cargado"

    return importados

    count = 0
    for item in items:
        nombre = item.producto
        total = float(item.cantidad or 0)

        # Intentar desglosar en cajas/bultos usando ProductoPrecio
        cantidad_unidad = total
        cantidad_caja = 0.0
        cantidad_bulto = 0.0
        pp = (ProductoPrecio.query
              .filter(db.func.lower(ProductoPrecio.producto_nombre) == _norm(nombre))
              .first())
        # El item ya fue normalizado en add_carrito_item: kg para Por Kilos y
        # unidades para las demás categorías. Se guarda el valor tal cual.

        cd = ConteoDetalle.query.filter_by(
            periodo_id=periodo.id, producto_nombre=nombre
        ).first()
        if cd:
            cd.total_unidad_base = total
            cd.cantidad_unidad = total
            cd.fue_cargado = True
            cd.fecha_carga = utc_now()
            cd.usuario = usuario
        else:
            cd = ConteoDetalle(
                periodo_id=periodo.id,
                cliente_id=cliente_id,
                tienda_id=tienda_id,
                usuario=usuario,
                producto_nombre=nombre,
                categoria=item.categoria,
                cantidad_unidad=cantidad_unidad,
                cantidad_caja=0,
                cantidad_bulto=0,
                total_unidad_base=total,
                fue_cargado=True,
            )
            db.session.add(cd)
        count += 1

    if count > 0 and periodo.estado in ("Abierto", "Pendiente"):
        periodo.estado = "Cargado"

    return count
