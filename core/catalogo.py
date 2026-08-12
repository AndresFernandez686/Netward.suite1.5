"""Lógica de catálogo compartido entre admin y empleado."""
from core.models import Producto, ProductoPrecio, StockThreshold, db
from core.seed_data import CATEGORIAS


def get_productos_db(include_hidden: bool = False):
    """Devuelve {categoria: [nombre, ...]} filtrando productos visibles para empleado."""
    result = {}
    query = Producto.query
    if not include_hidden and hasattr(Producto, "visible_empleado"):
        query = query.filter_by(visible_empleado=True)
    for categoria in CATEGORIAS:
        result[categoria] = [
            p.nombre for p in query.filter_by(categoria=categoria)
            .order_by(Producto.nombre)
            .all()
        ]
    return result


def resolver_producto_id(nombre: str) -> int | None:
    """Devuelve el id del Producto cuyo nombre coincide (case-insensitive), o None."""
    p = (Producto.query
         .filter(db.func.lower(Producto.nombre) == nombre.strip().lower())
         .first())
    return p.id if p else None


def backfill_producto_ids() -> int:
    """Rellena producto_id en producto_precios y stock_thresholds donde falte. Retorna filas actualizadas."""
    actualizados = 0
    for pp in ProductoPrecio.query.filter(ProductoPrecio.producto_id.is_(None)).all():
        pid = resolver_producto_id(pp.producto_nombre)
        if pid:
            pp.producto_id = pid
            actualizados += 1
    for st in StockThreshold.query.filter(StockThreshold.producto_id.is_(None)).all():
        pid = resolver_producto_id(st.producto)
        if pid:
            st.producto_id = pid
            actualizados += 1
    if actualizados:
        db.session.commit()
    return actualizados


def get_productos_db(include_hidden: bool = False):
    """Devuelve {categoria: [nombre, ...]} filtrando productos visibles para empleado."""
    result = {}
    query = Producto.query
    if not include_hidden and hasattr(Producto, "visible_empleado"):
        query = query.filter_by(visible_empleado=True)
    for categoria in CATEGORIAS:
        result[categoria] = [
            p.nombre for p in query.filter_by(categoria=categoria)
            .order_by(Producto.nombre)
            .all()
        ]
    return result


def activar_catalogo_pendiente_empleado():
    """Marca como visibles para empleado los productos pendientes de sincronización."""
    if not hasattr(Producto, "visible_empleado"):
        return 0
    pendientes = Producto.query.filter_by(visible_empleado=False).all()
    for producto in pendientes:
        producto.visible_empleado = True
    db.session.flush()
    return len(pendientes)