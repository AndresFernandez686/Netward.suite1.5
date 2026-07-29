"""Lógica de negocio para el historial administrativo."""
from datetime import date

from core.models import InventarioSnapshot, HistorialMovimiento, Usuario
from core.seed_data import TIPOS_INVENTARIO


def build_admin_historial_context(*, cliente_id: str, tiendas, tienda_id: str | None,
                                  empleado: str, tipo: str, fecha_inicio: str,
                                  fecha_fin: str, fecha: str | None):
    """Calcula el contexto de la vista de historial del administrador."""
    tienda_id = tienda_id or (tiendas[0].id if tiendas else "T001")

    snapshots = InventarioSnapshot.query.filter_by(cliente_id=cliente_id, tienda_id=tienda_id)
    if empleado != "Todos":
        snapshots = snapshots.filter_by(usuario=empleado)
    snapshots = snapshots.filter(
        InventarioSnapshot.fecha >= fecha_inicio,
        InventarioSnapshot.fecha <= fecha_fin,
    )
    snapshots = snapshots.order_by(
        InventarioSnapshot.fecha.desc(),
        InventarioSnapshot.id.desc(),
    ).all()

    selected_snapshot = None
    registros = []
    if snapshots:
        if fecha:
            selected_snapshot = next((s for s in snapshots if s.fecha == fecha), None)
        if selected_snapshot is None:
            selected_snapshot = snapshots[0]

        q = HistorialMovimiento.query.filter_by(
            cliente_id=cliente_id,
            tienda_id=tienda_id,
            usuario=selected_snapshot.usuario,
            fecha=selected_snapshot.fecha,
        )
        if tipo != "Todos":
            q = q.filter_by(tipo_inventario=tipo)
        registros = q.order_by(
            HistorialMovimiento.categoria,
            HistorialMovimiento.producto,
        ).all()

    empleados = [
        u.username for u in Usuario.query.filter_by(cliente_id=cliente_id, rol="empleado").all()
    ]

    return {
        "tienda_id": tienda_id,
        "empleados": empleados,
        "empleado": empleado,
        "tipos": TIPOS_INVENTARIO,
        "tipo": tipo,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "snapshots": snapshots,
        "selected_snapshot": selected_snapshot,
        "registros": registros,
    }