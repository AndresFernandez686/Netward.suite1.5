"""
Modelos de base de datos (SQLAlchemy) para el Sistema Netward.
Migracion desde el sistema Streamlit original a Flask + SQLite.
"""
from datetime import datetime, date, timezone
from typing import Any
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class BaseModel(db.Model):
    """Modelo base con constructor flexible para evitar problemas de tipado."""
    __abstract__ = True

    def __init__(self, **kwargs: Any):
        for key, value in kwargs.items():
            setattr(self, key, value)


class Tienda(BaseModel):
    """Sucursal / ubicacion del negocio (multi-tienda)."""
    __tablename__ = "tiendas"

    id = db.Column(db.String(10), primary_key=True)          # Ej: T001
    nombre = db.Column(db.String(120), nullable=False)
    direccion = db.Column(db.String(255), default="Direccion no especificada")
    activa = db.Column(db.Boolean, default=True)
    es_default = db.Column(db.Boolean, default=False)
    fecha_creacion = db.Column(db.String(20), default=lambda: date.today().isoformat())

    inventario = db.relationship("InventarioItem", backref="tienda", lazy=True,
                                 cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "nombre": self.nombre,
            "direccion": self.direccion,
            "activa": self.activa,
            "es_default": self.es_default,
            "fecha_creacion": self.fecha_creacion,
        }


class Usuario(BaseModel):
    """Usuario del sistema. En MODO BETA cualquier contrasena es valida."""
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    rol = db.Column(db.String(20), nullable=False)           # empleado | administrador
    tienda_id = db.Column(db.String(10), nullable=True)      # ALL para administradores


class Producto(BaseModel):
    """Catalogo base de productos por categoria."""
    __tablename__ = "productos"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(160), nullable=False)
    categoria = db.Column(db.String(40), nullable=False)     # Impulsivo | Por Kilos | Extras

    __table_args__ = (db.UniqueConstraint("nombre", "categoria", name="uq_producto_categoria"),)


class InventarioItem(BaseModel):
    """Stock actual de un producto en una tienda."""
    __tablename__ = "inventario_items"

    id = db.Column(db.Integer, primary_key=True)
    tienda_id = db.Column(db.String(10), db.ForeignKey("tiendas.id"), nullable=False)
    categoria = db.Column(db.String(40), nullable=False)
    producto = db.Column(db.String(160), nullable=False)
    cantidad = db.Column(db.Float, default=0)
    ume = db.Column(db.String(30), default="Unidad")
    tipo_inventario = db.Column(db.String(20), default="Diario")
    fecha = db.Column(db.String(20), default=lambda: date.today().isoformat())
    actualizado = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        db.UniqueConstraint("tienda_id", "categoria", "producto", name="uq_inv_item"),
    )


class HistorialMovimiento(BaseModel):
    """Registro detallado de cada movimiento de inventario."""
    __tablename__ = "historial"

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.String(20), nullable=False)
    hora = db.Column(db.String(20), default="")
    usuario = db.Column(db.String(80), nullable=False)
    categoria = db.Column(db.String(40), nullable=False)
    producto = db.Column(db.String(160), nullable=False)
    cantidad = db.Column(db.Float, default=0)
    modo = db.Column(db.String(30), default="")              # UME usado
    tipo_inventario = db.Column(db.String(20), default="Diario")
    detalle = db.Column(db.String(255), default="")
    tienda_id = db.Column(db.String(10), default="T001")
    creado = db.Column(db.DateTime, default=utc_now)


class InventarioSnapshot(BaseModel):
    """Resumen de una carga de inventario por fecha y tienda."""
    __tablename__ = "inventario_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.String(20), nullable=False)
    tienda_id = db.Column(db.String(10), nullable=False)
    usuario = db.Column(db.String(80), nullable=False)
    tipo_inventario = db.Column(db.String(20), default="Diario")
    total_items = db.Column(db.Integer, default=0)
    creado = db.Column(db.DateTime, default=utc_now)

    __table_args__ = (
        db.UniqueConstraint("tienda_id", "fecha", "usuario", name="uq_snapshot_fecha_usuario"),
    )


class DeliveryProducto(BaseModel):
    """Catalogo de productos disponibles para delivery."""
    __tablename__ = "delivery_productos"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(160), nullable=False, unique=True)
    precio = db.Column(db.Float, default=0)
    es_promocion = db.Column(db.Boolean, default=False)
    activo = db.Column(db.Boolean, default=True)


class DeliveryVenta(BaseModel):
    """Registro de ventas de delivery."""
    __tablename__ = "delivery_ventas"

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.String(20), nullable=False)
    hora = db.Column(db.String(20), default="")
    producto = db.Column(db.String(160), nullable=False)
    cantidad = db.Column(db.Integer, default=1)
    precio_unitario = db.Column(db.Float, default=0)
    total = db.Column(db.Float, default=0)
    usuario = db.Column(db.String(80), nullable=False)
    tienda_id = db.Column(db.String(10), default="T001")


class StockThreshold(BaseModel):
    """Umbrales del semaforo de stock por producto."""
    __tablename__ = "stock_thresholds"

    id = db.Column(db.Integer, primary_key=True)
    producto = db.Column(db.String(160), unique=True, nullable=False)
    critico = db.Column(db.Float, default=0)
    medio = db.Column(db.Float, default=0)


class ProductoPrecio(BaseModel):
    """Precio y cantidades de empaque para productos Impulsivo y Extras."""
    __tablename__ = "producto_precios"

    id = db.Column(db.Integer, primary_key=True)
    producto_nombre = db.Column(db.String(160), unique=True, nullable=False)
    categoria = db.Column(db.String(40), nullable=False)     # Impulsivo | Extras
    precio = db.Column(db.Float, nullable=True)
    precio_por_caja = db.Column(db.Float, nullable=True)
    unidades_por_caja = db.Column(db.Float, nullable=True)
    unidades_por_bulto = db.Column(db.Float, nullable=True)


class InventarioDescSnapshot(BaseModel):
    """Guarda el stock_final de cada inventario Desc. procesado (regla de continuidad por período)."""
    __tablename__ = "inventario_desc_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    tienda_id = db.Column(db.String(10), nullable=False)
    mes = db.Column(db.String(7), nullable=False)           # YYYY-MM
    fecha_proceso = db.Column(db.String(20), nullable=False)
    stock_final_json = db.Column(db.Text, nullable=False)   # JSON {nombre_lower: float}
    creado = db.Column(db.DateTime, default=utc_now)

    __table_args__ = (
        db.UniqueConstraint("tienda_id", "mes", "fecha_proceso",
                            name="uq_desc_snapshot"),
    )
