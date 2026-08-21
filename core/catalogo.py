"""Lógica de catálogo compartido entre admin y empleado."""
import re
import unicodedata

from core.models import Producto, ProductoPrecio, StockThreshold, Usuario, db
from core.seed_data import CATEGORIAS


def identidad_producto(nombre: str) -> str:
    """Normaliza nombres legacy y actuales sin confundir presentaciones xN."""
    texto = unicodedata.normalize("NFKD", str(nombre or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c)).casefold()
    texto = re.sub(r"\([^)]*\)\s*$", "", texto)
    texto = re.sub(r"\b(?:n[º°o]?|num(?:ero)?)\s*(\d+)\b", r"\1", texto)
    texto = re.sub(r"\s+x\s+un(?:idad|\.)?\s*$", "", texto)
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def version_catalogo_actual() -> int:
    return int(
        db.session.query(db.func.max(Producto.catalogo_version))
        .filter(Producto.visible_empleado.is_(True))
        .scalar() or 0
    )


def catalogo_pendiente_usuario(cliente_id: str, username: str) -> tuple[bool, int]:
    usuario = Usuario.query.filter_by(cliente_id=cliente_id, username=username).first()
    recibida = int(usuario.catalogo_version_recibida or 0) if usuario else 0
    actual = version_catalogo_actual()
    cantidad = Producto.query.filter(
        Producto.visible_empleado.is_(True),
        Producto.catalogo_version > recibida,
    ).count()
    return actual > recibida, cantidad


def recibir_catalogo_usuario(cliente_id: str, username: str) -> int:
    usuario = Usuario.query.filter_by(cliente_id=cliente_id, username=username).first()
    if usuario is None:
        return 0
    pendiente, cantidad = catalogo_pendiente_usuario(cliente_id, username)
    if pendiente:
        usuario.catalogo_version_recibida = version_catalogo_actual()
        db.session.flush()
    return cantidad


def get_productos_db(include_hidden: bool = False, *, cliente_id=None, username=None):
    """Devuelve {categoria: [nombre, ...]} filtrando productos visibles para empleado."""
    result = {}
    query = Producto.query
    if not include_hidden and hasattr(Producto, "visible_empleado"):
        query = query.filter_by(visible_empleado=True)
    if username and cliente_id:
        usuario = Usuario.query.filter_by(
            cliente_id=cliente_id,
            username=username,
        ).first()
        version_recibida = int(usuario.catalogo_version_recibida or 0) if usuario else 0
        query = query.filter(Producto.catalogo_version <= version_recibida)
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
