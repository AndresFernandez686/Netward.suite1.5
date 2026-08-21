"""
Modelos de base de datos (SQLAlchemy) para el Sistema Netward.
Migracion desde el sistema Streamlit original a Flask + SQLite.
"""
from datetime import datetime, date, timezone
from typing import Any
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utc_now():
    """UTC sin zona para las columnas DateTime históricamente ingenuas."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class BaseModel(db.Model):
    """Modelo base con constructor flexible para evitar problemas de tipado."""
    __abstract__ = True

    def __init__(self, **kwargs: Any):
        for key, value in kwargs.items():
            setattr(self, key, value)


class Cliente(BaseModel):
    """Empresa dueña de una o varias sucursales (multi-tenant)."""
    __tablename__ = "clientes"

    id = db.Column(db.String(10), primary_key=True)          # Ej: C001
    nombre = db.Column(db.String(160), nullable=False, unique=True)
    plan = db.Column(db.String(40), default="basico")
    estado = db.Column(db.String(20), default="activo")     # activo | suspendido
    fecha_creacion = db.Column(db.String(20), default=lambda: date.today().isoformat())

    tiendas = db.relationship("Tienda", backref="cliente", lazy=True)
    usuarios = db.relationship("Usuario", backref="cliente", lazy=True)


class Tienda(BaseModel):
    """Sucursal / ubicacion del negocio (multi-tienda)."""
    __tablename__ = "tiendas"

    id = db.Column(db.String(10), primary_key=True)          # Ej: T001
    cliente_id = db.Column(db.String(10), db.ForeignKey("clientes.id"), nullable=False, default="C001", index=True)
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
    """Usuario del sistema con autenticacion por contrasena hasheada."""
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)  # NULL = sin contrasena (legacy beta)
    cliente_id = db.Column(db.String(10), db.ForeignKey("clientes.id"), nullable=False, default="C001", index=True)
    rol = db.Column(db.String(20), nullable=False)           # empleado | administrador
    tienda_id = db.Column(db.String(10), nullable=True)      # ALL para administradores
    ultimo_periodo_notificado_id = db.Column(db.Integer, nullable=False, default=0)


class NotificacionUsuario(BaseModel):
    """Notificaciones persistentes por usuario (campana / centro de avisos)."""
    __tablename__ = "notificaciones_usuario"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    username = db.Column(db.String(80), nullable=False, index=True)
    tipo = db.Column(db.String(40), nullable=False, default="periodo_abierto")
    referencia_id = db.Column(db.Integer, nullable=True)  # p.ej. InventarioPeriodo.id
    titulo = db.Column(db.String(160), nullable=False)
    mensaje = db.Column(db.String(300), nullable=False)
    leida = db.Column(db.Boolean, nullable=False, default=False, index=True)
    creada = db.Column(db.DateTime, default=utc_now, index=True)


class Producto(BaseModel):
    """Catalogo base de productos por categoria."""
    __tablename__ = "productos"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(160), nullable=False)
    categoria = db.Column(db.String(40), nullable=False)     # Impulsivo | Por Kilos | Extras
    visible_empleado = db.Column(db.Boolean, default=True, nullable=False)
    # Código estable del sistema externo — clave principal de vinculación con el Excel oficial
    codigo_articulo = db.Column(db.String(40), nullable=True, index=True)

    __table_args__ = (db.UniqueConstraint("nombre", "categoria", name="uq_producto_categoria"),)


class InventarioItem(BaseModel):
    """Stock actual de un producto en una tienda."""
    __tablename__ = "inventario_items"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    tienda_id = db.Column(db.String(10), db.ForeignKey("tiendas.id"), nullable=False)
    categoria = db.Column(db.String(40), nullable=False)
    producto = db.Column(db.String(160), nullable=False)
    cantidad = db.Column(db.Float, default=0)
    ume = db.Column(db.String(30), default="Unidad")
    tipo_inventario = db.Column(db.String(20), default="Diario")
    fecha = db.Column(db.String(20), default=lambda: date.today().isoformat())
    sinc_estado = db.Column(db.String(20), default="pendiente")  # pendiente | sincronizado
    periodo_id = db.Column(db.Integer, db.ForeignKey("inventario_periodos.id"), nullable=True, index=True)
    usuario_ultima_carga = db.Column(db.String(80), default="", nullable=False)
    version = db.Column(db.Integer, default=1, nullable=False)
    fue_sobreescrito = db.Column(db.Boolean, default=False, nullable=False)
    actualizado = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        db.UniqueConstraint("tienda_id", "categoria", "producto", name="uq_inv_item"),
    )


class HistorialMovimiento(BaseModel):
    """Registro detallado de cada movimiento de inventario."""
    __tablename__ = "historial"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
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
    # FK explícita al snapshot de la sesión de carga (evita ambigüedad si mismo usuario carga 2 veces/día)
    snapshot_id = db.Column(db.Integer, db.ForeignKey("inventario_snapshots.id"), nullable=True, index=True)
    periodo_id = db.Column(db.Integer, db.ForeignKey("inventario_periodos.id"), nullable=True, index=True)
    tipo_movimiento = db.Column(db.String(30), default="original", nullable=False)
    usuario_anterior = db.Column(db.String(80), default="")
    cantidad_anterior = db.Column(db.Float, nullable=True)
    version = db.Column(db.Integer, default=1, nullable=False)
    creado = db.Column(db.DateTime, default=utc_now)


class InventarioSnapshot(BaseModel):
    """Resumen de una carga de inventario por fecha y tienda."""
    __tablename__ = "inventario_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
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
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    nombre = db.Column(db.String(160), nullable=False, unique=True)
    precio = db.Column(db.Float, default=0)
    es_promocion = db.Column(db.Boolean, default=False)
    activo = db.Column(db.Boolean, default=True)


class DeliveryVenta(BaseModel):
    """Registro de ventas de delivery."""
    __tablename__ = "delivery_ventas"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    fecha = db.Column(db.String(20), nullable=False)
    hora = db.Column(db.String(20), default="")
    producto = db.Column(db.String(160), nullable=False)
    cantidad = db.Column(db.Integer, default=1)
    precio_unitario = db.Column(db.Float, default=0)
    total = db.Column(db.Float, default=0)
    usuario = db.Column(db.String(80), nullable=False)
    tienda_id = db.Column(db.String(10), default="T001")
    periodo_id = db.Column(
        db.Integer,
        db.ForeignKey("inventario_periodos.id"),
        nullable=True,
        index=True,
    )
    # en_rango | fuera_rango | sin_periodo
    estado_periodo = db.Column(db.String(20), default="sin_periodo", nullable=False)


class StockThreshold(BaseModel):
    """Umbrales del semaforo de stock por producto."""
    __tablename__ = "stock_thresholds"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    producto = db.Column(db.String(160), unique=True, nullable=False)
    # FK opcional; permite lookup por ID además del match por nombre
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=True, index=True)
    critico = db.Column(db.Float, default=0)
    medio = db.Column(db.Float, default=0)


class ProductoPrecio(BaseModel):
    """Precio y cantidades de empaque para productos Impulsivo y Extras."""
    __tablename__ = "producto_precios"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    producto_nombre = db.Column(db.String(160), unique=True, nullable=False)
    # FK opcional; permite lookup por ID además del match por nombre
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=True, index=True)
    categoria = db.Column(db.String(40), nullable=False)     # Impulsivo | Extras
    precio = db.Column(db.Float, nullable=True)
    precio_por_caja = db.Column(db.Float, nullable=True)
    unidades_por_caja = db.Column(db.Float, nullable=True)
    unidades_por_bulto = db.Column(db.Float, nullable=True)


class InventarioDescSnapshot(BaseModel):
    """Guarda el stock_final de cada Excel oficial procesado para continuidad."""
    __tablename__ = "inventario_desc_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    tienda_id = db.Column(db.String(10), nullable=False)
    mes = db.Column(db.String(7), nullable=False)           # YYYY-MM
    fecha_proceso = db.Column(db.String(20), nullable=False)
    stock_final_json = db.Column(db.Text, nullable=False)   # JSON {nombre_lower: float}
    creado = db.Column(db.DateTime, default=utc_now)

    __table_args__ = (
        db.UniqueConstraint("tienda_id", "mes", "fecha_proceso",
                            name="uq_desc_snapshot"),
    )


class RegistroAveriado(BaseModel):
    """Productos averiados registrados por el empleado."""
    __tablename__ = "registros_averiados"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    tienda_id = db.Column(db.String(10), nullable=False)
    fecha = db.Column(db.String(20), nullable=False)
    hora = db.Column(db.String(20), default="")
    usuario = db.Column(db.String(80), nullable=False)
    categoria = db.Column(db.String(40), nullable=False)
    producto = db.Column(db.String(160), nullable=False)
    cantidad = db.Column(db.Float, default=0)          # cantidad en UME original
    cantidad_unidades = db.Column(db.Float, default=0) # convertida a unidades
    ume = db.Column(db.String(30), default="Unidad")
    desc_conversion = db.Column(db.String(255), default="")
    detalle = db.Column(db.String(255), default="")
    sinc_estado = db.Column(db.String(20), default="pendiente")  # pendiente | sincronizado
    revisado = db.Column(db.Boolean, default=False)
    creado = db.Column(db.DateTime, default=utc_now)


class RegistroVencimiento(BaseModel):
    """Productos próximos a vencer registrados por el empleado."""
    __tablename__ = "registros_vencimiento"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    tienda_id = db.Column(db.String(10), nullable=False)
    fecha = db.Column(db.String(20), nullable=False)
    hora = db.Column(db.String(20), default="")
    usuario = db.Column(db.String(80), nullable=False)
    categoria = db.Column(db.String(40), nullable=False)
    producto = db.Column(db.String(160), nullable=False)
    cantidad = db.Column(db.Float, default=0)
    cantidad_unidades = db.Column(db.Float, default=0)
    ume = db.Column(db.String(30), default="Unidad")
    desc_conversion = db.Column(db.String(255), default="")
    fecha_vencimiento = db.Column(db.String(20), nullable=False)
    detalle = db.Column(db.String(255), default="")
    sinc_estado = db.Column(db.String(20), default="pendiente")  # pendiente | sincronizado
    revisado = db.Column(db.Boolean, default=False)
    creado = db.Column(db.DateTime, default=utc_now)


class SincronizacionLog(BaseModel):
    """Registro de sincronizaciones del empleado (envío y recepción)."""
    __tablename__ = "sincronizacion_log"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    tienda_id = db.Column(db.String(10), nullable=False)
    usuario = db.Column(db.String(80), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)   # "envio" | "recepcion"
    accion = db.Column(db.String(30), default="")     # "solo_enviar" | "enviar_recibir"
    timestamp = db.Column(db.DateTime, default=utc_now)


# ─────────────────────────────────────────────────────────────────────────────
#  MÓDULO DE AUDITORÍA — Nuevos modelos para inventario correlativo
# ─────────────────────────────────────────────────────────────────────────────

class InventarioPeriodo(BaseModel):
    """Período de inventario con ciclo de vida completo."""
    __tablename__ = "inventario_periodos"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    tienda_id = db.Column(db.String(10), nullable=False)
    numero = db.Column(db.Integer, nullable=False)          # correlativo por tienda
    fecha_desde = db.Column(db.String(20), nullable=False)
    fecha_hasta = db.Column(db.String(20), nullable=False)
    dias_periodo = db.Column(db.Integer, default=7)
    # Abierto | Pendiente | Cargado | Sincronizado | Cerrado | Conciliado | Auditado
    estado = db.Column(db.String(20), default="Abierto")
    usuario_creador = db.Column(db.String(80), nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=utc_now)
    fecha_cierre = db.Column(db.DateTime, nullable=True)
    observacion = db.Column(db.String(500), default="")

    conteos = db.relationship("ConteoDetalle", backref="periodo", lazy=True,
                               cascade="all, delete-orphan")
    ajustes = db.relationship("AjusteInventario", backref="periodo", lazy=True,
                               cascade="all, delete-orphan")
    excel_importados = db.relationship("ExcelImportado", backref="periodo", lazy=True,
                                        cascade="all, delete-orphan")
    auditoria = db.relationship("AuditoriaResultado", backref="periodo", lazy=True,
                                 cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("tienda_id", "numero", name="uq_periodo_tienda_numero"),
    )


class ConteoDetalle(BaseModel):
    """Conteo de un producto en un período de inventario."""
    __tablename__ = "conteo_detalle"

    id = db.Column(db.Integer, primary_key=True)
    periodo_id = db.Column(db.Integer, db.ForeignKey("inventario_periodos.id"), nullable=False)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    tienda_id = db.Column(db.String(10), nullable=False)
    usuario = db.Column(db.String(80), nullable=False)
    producto_nombre = db.Column(db.String(160), nullable=False)
    categoria = db.Column(db.String(40), nullable=False)
    cantidad_unidad = db.Column(db.Float, default=0)
    cantidad_caja = db.Column(db.Float, default=0)
    cantidad_bulto = db.Column(db.Float, default=0)
    total_unidad_base = db.Column(db.Float, default=0)  # siempre en unidades
    fue_cargado = db.Column(db.Boolean, default=True)   # False = NULL/sin cargar
    observacion = db.Column(db.String(255), default="")
    primera_carga = db.Column(db.DateTime, default=utc_now)  # jamás se sobreescribe
    fecha_carga = db.Column(db.DateTime, default=utc_now)     # última sincronización
    # Regla: último gana. Este contador registra cuántas veces se sincronizó en el período.
    veces_sincronizado = db.Column(db.Integer, default=1)
    fue_sobreescrito = db.Column(db.Boolean, default=False, nullable=False)
    version_ultima_carga = db.Column(db.Integer, default=1, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("periodo_id", "tienda_id", "producto_nombre",
                             name="uq_conteo_periodo_producto"),
    )


class InventarioBorrador(BaseModel):
    """Carrito temporal persistente de un empleado para un período abierto."""
    __tablename__ = "inventario_borradores"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    periodo_id = db.Column(db.Integer, db.ForeignKey("inventario_periodos.id"), nullable=False, index=True)
    tienda_id = db.Column(db.String(10), nullable=False, index=True)
    usuario = db.Column(db.String(80), nullable=False, index=True)
    contenido_json = db.Column(db.Text, nullable=False, default="[]")
    actualizado = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "cliente_id", "periodo_id", "tienda_id", "usuario",
            name="uq_borrador_empleado_periodo",
        ),
    )


class AjusteInventario(BaseModel):
    """Ajuste administrativo posterior al conteo del empleado."""
    __tablename__ = "ajustes_inventario"

    id = db.Column(db.Integer, primary_key=True)
    periodo_id = db.Column(db.Integer, db.ForeignKey("inventario_periodos.id"), nullable=False)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    producto_nombre = db.Column(db.String(160), nullable=False)
    usuario_admin = db.Column(db.String(80), nullable=False)
    cantidad_ajustada = db.Column(db.Float, default=0)      # puede ser negativo
    # Producto encontrado | Caja no contada | Corrección de carga | Producto mal ubicado | Otro
    motivo = db.Column(db.String(80), default="Otro")
    observacion = db.Column(db.String(500), default="")
    # False = solo trazabilidad; no modifica conteo_final (evita doble descuento con mermas/vencidos)
    impacta_stock = db.Column(db.Boolean, default=True)
    fecha_ajuste = db.Column(db.DateTime, default=utc_now)


class ExcelImportado(BaseModel):
    """Cabecera de un Excel oficial importado del sistema externo."""
    __tablename__ = "excel_importados"

    id = db.Column(db.Integer, primary_key=True)
    periodo_id = db.Column(db.Integer, db.ForeignKey("inventario_periodos.id"), nullable=False)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    nombre_archivo = db.Column(db.String(255), nullable=False)
    fecha_importacion = db.Column(db.DateTime, default=utc_now)
    usuario_importador = db.Column(db.String(80), nullable=False)
    # ok | errores | pendiente_vinculacion | fallido
    estado_validacion = db.Column(db.String(40), default="ok")
    productos_nuevos = db.Column(db.Integer, default=0)  # productos sin mapear

    detalles = db.relationship("ExcelDetalle", backref="excel_importado", lazy=True,
                                cascade="all, delete-orphan")


class ExcelDetalle(BaseModel):
    """Fila del Excel oficial (una por producto)."""
    __tablename__ = "excel_detalles"

    id = db.Column(db.Integer, primary_key=True)
    excel_id = db.Column(db.Integer, db.ForeignKey("excel_importados.id"), nullable=False)
    articulo = db.Column(db.String(40), nullable=False)     # código estable del sistema externo
    artdescrip = db.Column(db.String(255), default="")
    artcosto = db.Column(db.Float, nullable=True)
    stockinicial = db.Column(db.Float, default=0)
    compras = db.Column(db.Float, default=0)
    otrosingresos = db.Column(db.Float, default=0)
    otrassalidas = db.Column(db.Float, default=0)
    stockfinal = db.Column(db.Float, default=0)
    ventateorica = db.Column(db.Float, default=0)
    ventareal = db.Column(db.Float, default=0)
    diferencia = db.Column(db.Float, default=0)
    importedesvio = db.Column(db.Float, default=0)
    kilos = db.Column(db.Float, default=0)
    unidades = db.Column(db.Float, default=0)
    grupo = db.Column(db.String(120), default="")
    grudescrip = db.Column(db.String(120), default="")
    # Vínculo con el producto interno
    producto_nombre_interno = db.Column(db.String(160), nullable=True)  # descriptivo
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=True, index=True)
    # vinculado | pendiente | sin_producto | excluido
    estado_vinculacion = db.Column(db.String(20), default="pendiente")
    # Fila excluida de la auditoría (canjes, congelados, etc.)
    excluido_auditoria = db.Column(db.Boolean, default=False)
    motivo_exclusion = db.Column(db.String(120), nullable=True)


class ExcelDetalleEdicion(BaseModel):
    """Trazabilidad de cada fila del Excel oficial modificada por un administrador."""
    __tablename__ = "excel_detalle_ediciones"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    periodo_id = db.Column(
        db.Integer, db.ForeignKey("inventario_periodos.id"), nullable=False, index=True
    )
    excel_id = db.Column(
        db.Integer, db.ForeignKey("excel_importados.id"), nullable=False, index=True
    )
    detalle_id = db.Column(
        db.Integer, db.ForeignKey("excel_detalles.id"), nullable=False, index=True
    )
    usuario = db.Column(db.String(80), nullable=False)
    cambios_json = db.Column(db.Text, nullable=False, default="{}")
    creado = db.Column(db.DateTime, default=utc_now, nullable=False, index=True)


class AuditoriaResultado(BaseModel):
    """Resultado del motor de auditoría por producto por período."""
    __tablename__ = "auditoria_resultados"

    id = db.Column(db.Integer, primary_key=True)
    periodo_id = db.Column(db.Integer, db.ForeignKey("inventario_periodos.id"), nullable=False)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    producto_nombre = db.Column(db.String(160), nullable=False)
    categoria = db.Column(db.String(40), default="")
    articulo_codigo = db.Column(db.String(40), default="")   # código del Excel externo

    stock_inicial_anterior = db.Column(db.Float, default=0)
    stock_inicial_excel = db.Column(db.Float, default=0)
    alerta_continuidad = db.Column(db.Boolean, default=False)
    compras = db.Column(db.Float, default=0)
    promedio_compras_historico = db.Column(db.Float, default=0)
    ventas = db.Column(db.Float, default=0)
    otros_ingresos = db.Column(db.Float, default=0)
    otras_salidas = db.Column(db.Float, default=0)
    stock_final_excel = db.Column(db.Float, default=0)
    stock_esperado = db.Column(db.Float, default=0)
    conteo_empleado = db.Column(db.Float, default=0)
    ajuste_admin = db.Column(db.Float, default=0)
    conteo_final = db.Column(db.Float, default=0)
    diferencia = db.Column(db.Float, default=0)
    # faltante | sobrante | correcto | compensado
    tipo_diferencia = db.Column(db.String(20), default="correcto")
    costo_unitario = db.Column(db.Float, nullable=True)
    impacto = db.Column(db.Float, default=0)
    # Inconsistencia de continuidad | Compra mal cargada | Error de conteo |
    # Producto vencido | Merma o averiado | Canje no registrado |
    # Producto relacionado incoherente | Pendiente de revisión
    causa_sugerida = db.Column(db.String(80), default="Pendiente de revisión")
    evidencia = db.Column(db.Text, default="")
    # Alto | Medio | Bajo
    nivel_confianza = db.Column(db.String(20), default="Bajo")
    # Correcto | Observación | Revisar | Crítico
    severidad = db.Column(db.String(20), default="Correcto")
    # Pendiente | Sugerido | Justificado | Revisado | Sin diferencia | Sin diferencia real
    estado_auditoria = db.Column(db.String(20), default="Pendiente")
    # Excel oficial | Precio interno | Sin costo
    fuente_costo = db.Column(db.String(20), default="Sin costo")
    # Evidencia estructurada (datos crudos que construyen el texto de evidencia)
    factor_desvio_compra = db.Column(db.Float, default=0)            # compras / promedio
    diferencia_anterior_compensada = db.Column(db.Float, default=0)  # dif. período anterior
    cantidad_merma = db.Column(db.Float, default=0)                  # de registros_averiados
    cantidad_vencida = db.Column(db.Float, default=0)                # de registros_vencimiento
    cantidad_averiada = db.Column(db.Float, default=0)               # alias de cantidad_merma
    # Ventas del módulo delivery usadas para reemplazar ventareal cuando son mayores que cero
    ventas_delivery = db.Column(db.Float, default=0)
    usuario_conteo = db.Column(db.String(80), default="")
    usuario_ajuste = db.Column(db.String(80), default="")
    fecha_ajuste = db.Column(db.String(20), default="")
    creado = db.Column(db.DateTime, default=utc_now)

    justificaciones = db.relationship("Justificacion", backref="resultado", lazy=True,
                                       cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("periodo_id", "producto_nombre", name="uq_auditoria_periodo_producto"),
    )


class AsistenteIAConsulta(BaseModel):
    """Trazabilidad de consultas explicativas; nunca modifica la auditoría."""
    __tablename__ = "asistente_ia_consultas"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    tienda_id = db.Column(db.String(10), nullable=False, index=True)
    periodo_id = db.Column(
        db.Integer,
        db.ForeignKey("inventario_periodos.id"),
        nullable=False,
        index=True,
    )
    resultado_id = db.Column(
        db.Integer,
        db.ForeignKey("auditoria_resultados.id"),
        nullable=True,
        index=True,
    )
    usuario = db.Column(db.String(80), nullable=False)
    tipo = db.Column(db.String(20), nullable=False, default="periodo")
    pregunta = db.Column(db.String(1000), nullable=False)
    respuesta = db.Column(db.Text, nullable=False)
    proveedor = db.Column(db.String(40), nullable=False, default="local")
    modelo = db.Column(db.String(120), nullable=False, default="reglas-locales")
    contexto_json = db.Column(db.Text, nullable=False, default="{}")
    estado = db.Column(db.String(20), nullable=False, default="ok")
    error = db.Column(db.String(500), nullable=False, default="")
    creado = db.Column(db.DateTime, default=utc_now, nullable=False, index=True)


class Justificacion(BaseModel):
    """Justificación manual de una diferencia en auditoría."""
    __tablename__ = "justificaciones"

    id = db.Column(db.Integer, primary_key=True)
    resultado_id = db.Column(db.Integer, db.ForeignKey("auditoria_resultados.id"), nullable=False)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    # Error de conteo | Compra mal cargada | Canje no registrado |
    # Producto vencido | Merma o averiado | Pendiente de revisión
    causa = db.Column(db.String(80), nullable=False)
    cantidad_justificada = db.Column(db.Float, default=0)
    importe_justificado = db.Column(db.Float, default=0)
    observacion = db.Column(db.String(500), nullable=False)
    usuario = db.Column(db.String(80), nullable=False)
    fecha = db.Column(db.DateTime, default=utc_now)


class ProductoRelacionado(BaseModel):
    """Relación de consumo entre productos (para alertas de auditoría)."""
    __tablename__ = "productos_relacionados"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    producto_principal = db.Column(db.String(160), nullable=False)
    producto_relacionado = db.Column(db.String(160), nullable=False)
    ratio_esperado = db.Column(db.Float, default=1.0)   # unidades_relacionado / unidades_principal
    tolerancia = db.Column(db.Float, default=0.1)        # 10 %
    activo = db.Column(db.Boolean, default=True)


class ConfiguracionSistema(BaseModel):
    """Par clave-valor de configuración por cliente."""
    __tablename__ = "configuracion_sistema"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(10), nullable=False, default="C001", index=True)
    clave = db.Column(db.String(80), nullable=False)    # ej: autoclose_horas
    valor = db.Column(db.String(255), nullable=False)   # ej: 24
    descripcion = db.Column(db.String(255), default="")
    actualizado = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        db.UniqueConstraint("cliente_id", "clave", name="uq_config_cliente_clave"),
    )
