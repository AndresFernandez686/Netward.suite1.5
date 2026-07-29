"""Lógica de catálogo compartido entre admin y empleado."""
from core.models import Producto, db
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


def activar_catalogo_pendiente_empleado():
    """Marca como visibles para empleado los productos pendientes de sincronización."""
    if not hasattr(Producto, "visible_empleado"):
        return 0
    pendientes = Producto.query.filter_by(visible_empleado=False).all()
    for producto in pendientes:
        producto.visible_empleado = True
    db.session.flush()
    return len(pendientes)