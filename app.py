"""
Sistema Netward - Gestion de Inventarios Multi-Tienda
Aplicacion Flask (migrada desde Streamlit).

Estructura:
  - app.py            -> Aplicacion principal y rutas
  - models.py         -> Modelos SQLAlchemy
  - seed_data.py      -> Datos iniciales (catalogo, usuarios, tiendas)
  - templates/        -> Vistas Jinja2
  - static/           -> CSS y JS
"""
import io
import os
import re
import sqlite3
from datetime import datetime, date, timedelta, timezone
from functools import wraps
import secrets
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, send_file, jsonify, abort, g)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

from core.models import (db, Cliente, Tienda, Usuario, Producto, InventarioItem,
                    HistorialMovimiento, InventarioSnapshot, DeliveryProducto,
                    DeliveryVenta, StockThreshold, ProductoPrecio,
                    InventarioDescSnapshot, RegistroAveriado, RegistroVencimiento,
                    SincronizacionLog,
                    InventarioPeriodo, ConteoDetalle, InventarioBorrador, AjusteInventario,
                    ExcelImportado, ExcelDetalle, ExcelDetalleEdicion,
                    FacturaCompra, FacturaCompraDetalle,
                    AuditoriaResultado,
                    Justificacion, ProductoRelacionado, ConfiguracionSistema,
                    NotificacionUsuario, AsistenteIAConversacion, AsistenteIAConsulta)
from core.auditoria import (ejecutar_auditoria, build_reporte_gerencial,
                            marcar_resultado_revisado)
from core.auditoria_causal import explicar_causa_diferencia
from core.auditoria_estado import (
    estado_actualizacion_auditoria, marcar_cambio_auditoria, marcar_cambio_catalogo,
)
from core.ajustes import ajuste_es_baja_no_imputable
from core.excel_importer import importar_excel_transaccional
from core.sync_bridge import (propagar_conteo_a_periodo, retroalimentar_periodo_desde_items,
                              sincronizar_transaccional)
from core.scheduler import (job_autoclose_periodos, actualizar_estados_periodos,
                            get_autoclose_horas, set_autoclose_horas)
from core.catalogo import (get_productos_db as catalogo_get_productos_db,
                           catalogo_pendiente_usuario,
                           producto_disponible_usuario,
                           resolver_producto_id, backfill_producto_ids)
from core.seed_data import (PRODUCTOS_BASE, CATEGORIAS, TIPOS_INVENTARIO, OPCIONES_UME,
                       ESTADOS_BALDE, CLIENTES_DEFAULT, TIENDAS_DEFAULT, USUARIOS_DEFAULT,
                       STOCK_THRESHOLDS_DEFAULT, DELIVERY_DEFAULT, stock_status)
from core.inventario import desc_bp
from core.admin_inventario import build_admin_inventory_context, _items_sincronizados, _precios_lookup
from core.admin_historial import build_admin_historial_context
from core.admin_vencimientos import build_admin_vencimientos_context, marcar_vencimientos_vistos, marcar_vencimientos_filtrados
from core import empleado as empleado_service
from core.admin_feedback import set_view_notice, pop_view_notice
from core.time_utils import today_local_iso, format_utc_naive_to_local
from core.security import rol_permitido
from core.periodos import (
    asegurar_conteo_admin, buscar_periodo_historico_solapado,
    periodo_es_retroactivo, registrar_estado_operativo_admin,
    total_conteo_con_ajustes,
)
from core.ai_assistant import (AIConfig, build_period_context,
                               build_product_context, explain,
                               refresh_period_report_markdown)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"), override=True)


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "si", "sí"}


TENANT_ISOLATION_MODE = _env_flag("TENANT_ISOLATION_MODE")
ISOLATED_TENANT_ID = os.getenv("ISOLATED_TENANT_ID", "C001").strip() or "C001"
if not re.fullmatch(r"[A-Za-z0-9_-]{1,10}", ISOLATED_TENANT_ID):
    raise RuntimeError("ISOLATED_TENANT_ID debe ser un identificador opaco de 1 a 10 caracteres.")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or "netward-dev-secret-change-me"
app.config["ASSET_VERSION"] = os.getenv(
    "ASSET_VERSION",
    datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
)
app.config["TENANT_ISOLATION_MODE"] = TENANT_ISOLATION_MODE
app.config["ISOLATED_TENANT_ID"] = ISOLATED_TENANT_ID


def utc_now():
    """UTC sin zona para columnas DateTime existentes, compatible con Python 3.14."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
# ── Seguridad de sesion ───────────────────────────────────────────────────────
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)  # Sesion expira en 8 h
app.config["SESSION_COOKIE_HTTPONLY"] = True    # JS no puede leer la cookie de sesion
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # Proteccion CSRF basica
# ─────────────────────────────────────────────────────────────────────────────
database_url = os.getenv("DATABASE_URL", "sqlite:///netward_empleado.db")
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False


@event.listens_for(Engine, "connect")
def _habilitar_claves_foraneas_sqlite(dbapi_connection, _connection_record):
    """SQLite desactiva las FK por conexion; Netward siempre las exige."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

db.init_app(app)
app.register_blueprint(desc_bp)


@app.after_request
def evitar_cache_de_sesion(response):
    """Evita caché sensible y agrega defensas que no exponen configuración interna."""
    if request.endpoint != "static" and (
        session.get("usuario") or request.endpoint in {"login", "logout"}
    ):
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0, private"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=63072000"
    return response


def _request_prefiere_json() -> bool:
    """Negocia JSON para rutas asíncronas sin depender solo de su URL."""
    return request.is_json or request.accept_mimetypes.best == "application/json"


def _respuesta_error_segura(status_code: int, title: str, message: str):
    if _request_prefiere_json():
        return jsonify(ok=False, error=message, status=status_code), status_code
    return render_template(
        "error.html",
        error_status=status_code,
        error_title=title,
        error_message=message,
    ), status_code


@app.errorhandler(403)
def forbidden_error(_error):
    return _respuesta_error_segura(
        403, "Acceso restringido", "No tienes permisos para realizar esta acción."
    )


@app.errorhandler(404)
def not_found_error(_error):
    return _respuesta_error_segura(
        404, "No encontramos esta página", "El contenido pudo cambiar de ubicación o ya no estar disponible."
    )


@app.errorhandler(500)
def internal_error(_error):
    db.session.rollback()
    return _respuesta_error_segura(
        500, "Ocurrió un problema inesperado", "Tus datos ingresados no se mostrarán en el error. Inténtalo nuevamente."
    )


@app.errorhandler(503)
def unavailable_error(_error):
    return _respuesta_error_segura(
        503, "Servicio temporalmente no disponible", "Conserva esta pantalla y vuelve a intentarlo en unos instantes."
    )

# Filtro Jinja2 para parsear JSON en templates
import json as _json
import re as _re
app.jinja_env.filters["from_json"] = _json.loads

def _strip_unidad(nombre: str) -> str:
    """Quita variantes de 'x unidad' / 'x un.' del final del nombre (solo para display al empleado)."""
    return _re.sub(r"\s+x\s+un(?:idad|\.?)\s*$", "", str(nombre), flags=_re.IGNORECASE)

app.jinja_env.filters["strip_unidad"] = _strip_unidad


def set_database_bind(bind_name):
    """Compatibilidad con llamadas antiguas; todos los roles usan una sola BD."""
    return "default"


def get_productos_db():
    """Devuelve el catálogo visible para empleado por categoria."""
    return catalogo_get_productos_db(include_hidden=False)


def get_active_bind():
    """Todos los roles comparten la base aislada de la empresa."""
    return "default"


def _periodo_abierto_mas_reciente(cliente_id: str, tienda_id: str):
    return (
        InventarioPeriodo.query
        .filter_by(cliente_id=cliente_id, tienda_id=tienda_id)
        .filter(InventarioPeriodo.estado.in_(["Abierto", "Pendiente", "Cargado"]))
        .order_by(InventarioPeriodo.id.desc())
        .first()
    )


def _nombre_tienda_periodo(periodo: InventarioPeriodo) -> str:
    """Obtiene el nombre visible de la tienda sin exponer su ID interno."""
    tienda = Tienda.query.filter_by(
        cliente_id=periodo.cliente_id,
        id=periodo.tienda_id,
    ).first()
    return tienda.nombre if tienda and tienda.nombre else "Tienda sin nombre"


def _notificar_nuevo_periodo(periodo: InventarioPeriodo) -> int:
    """Crea una notificación por empleado de la misma tienda/cliente."""
    empleados = Usuario.query.filter_by(
        cliente_id=periodo.cliente_id,
        rol="empleado",
        tienda_id=periodo.tienda_id,
    ).all()

    creadas = 0
    for u in empleados:
        existe = NotificacionUsuario.query.filter_by(
            cliente_id=periodo.cliente_id,
            username=u.username,
            tipo="periodo_abierto",
            referencia_id=periodo.id,
        ).first()
        if existe:
            continue

        db.session.add(NotificacionUsuario(
            cliente_id=periodo.cliente_id,
            username=u.username,
            tipo="periodo_abierto",
            referencia_id=periodo.id,
            titulo=f"Nuevo período abierto #{periodo.numero}",
            mensaje=f"Se abrió un nuevo período para tu tienda ({periodo.fecha_desde} a {periodo.fecha_hasta}).",
            leida=False,
        ))
        creadas += 1

    return creadas


def _notificar_admins_periodo_cargado(
    periodo: InventarioPeriodo,
    empleado: str,
    total_productos: int,
) -> int:
    """Avisa a cada administrador cuando una carga llega al período."""
    admins = Usuario.query.filter_by(
        cliente_id=periodo.cliente_id,
        rol="administrador",
    ).all()
    tienda = Tienda.query.filter_by(
        cliente_id=periodo.cliente_id,
        id=periodo.tienda_id,
    ).first()
    tienda_nombre = tienda.nombre if tienda else periodo.tienda_id

    for admin in admins:
        db.session.add(NotificacionUsuario(
            cliente_id=periodo.cliente_id,
            username=admin.username,
            tipo="periodo_cargado",
            referencia_id=periodo.id,
            titulo=f"Inventario cargado · Período #{periodo.numero}",
            mensaje=(
                f"{empleado} sincronizó {total_productos} producto(s) "
                f"de {tienda_nombre}."
            ),
            leida=False,
        ))
    return len(admins)


@app.before_request
def select_database_for_request():
    """Asigna la base de datos adecuada antes de cada peticion."""
    set_database_bind(get_active_bind())
    if app.config["TENANT_ISOLATION_MODE"] and session.get("usuario"):
        if session.get("cliente_id") != app.config["ISOLATED_TENANT_ID"]:
            session.clear()
            flash("La sesión no pertenece a esta instancia.", "error")
            return redirect(url_for("login"))
    # Selector global de tienda del admin: persiste en sesion
    if session.get("rol") == "administrador":
        tienda_arg = request.args.get("tienda")
        if tienda_arg:
            cliente_id = get_cliente_filtro()
            tiendas_validas = {t.id for t in Tienda.query.filter_by(cliente_id=cliente_id, activa=True).all()}
            if tienda_arg == "ALL" or tienda_arg in tiendas_validas:
                session["admin_tienda_id"] = tienda_arg

    if session.get("rol") == "empleado" and session.get("usuario") and session.get("tienda_id"):
        try:
            cliente_id = get_cliente_filtro()
            tienda_id = str(session.get("tienda_id") or "")
            if not tienda_id:
                return
            usuario = Usuario.query.filter_by(cliente_id=cliente_id, username=session.get("usuario")).first()
            periodo_reciente = _periodo_abierto_mas_reciente(cliente_id, tienda_id)
            if usuario and periodo_reciente and periodo_reciente.id > int(usuario.ultimo_periodo_notificado_id or 0):
                ultimo_flash = session.get("ultimo_periodo_flash_id")
                if ultimo_flash != periodo_reciente.id:
                    flash(
                        f"Nuevo período abierto para tu tienda: #{periodo_reciente.numero} ({periodo_reciente.fecha_desde} a {periodo_reciente.fecha_hasta}).",
                        "info",
                    )
                    session["ultimo_periodo_flash_id"] = periodo_reciente.id

            # Aviso de campana: mostrar una vez por notificación no leída más reciente
            notif = (
                NotificacionUsuario.query
                .filter_by(cliente_id=cliente_id, username=session.get("usuario"), leida=False)
                .order_by(NotificacionUsuario.id.desc())
                .first()
            )
            if notif is not None:
                ultimo_notif_flash = session.get("ultimo_notif_empleado_flash_id")
                if ultimo_notif_flash != notif.id:
                    flash(notif.titulo, "info")
                    session["ultimo_notif_empleado_flash_id"] = notif.id
        except Exception:
            pass


def get_tienda_filtro():
    """Tienda activa seleccionada por el admin en el topbar ('ALL' = todas)."""
    return session.get("admin_tienda_id", "ALL")


CONFIG_PRODUCT_TABS = {"tab-impulsivo", "tab-extras", "tab-kilos"}


def _safe_config_tab(tab_value):
    """Valida la pestaña activa de la sección de productos en configuración."""
    return tab_value if tab_value in CONFIG_PRODUCT_TABS else "tab-impulsivo"


def _set_admin_config_notice(section, message, category="info", tab=None):
    """Guarda un aviso local para /admin/configuracion sin usar flash global."""
    set_view_notice(
        session,
        "admin_config_notice",
        message,
        category,
        section=section,
        tab=_safe_config_tab(tab) if tab else None,
    )


def _set_admin_precios_notice(message, category="info", tab=None):
    """Guarda un aviso local para la pantalla unificada de Catálogo."""
    set_view_notice(
        session, "admin_precios_notice", message, category,
        tab=_safe_catalog_tab(tab),
    )


def _safe_catalog_tab(tab_value):
    tab_value = {
        "tab-impulsivo": "tab-0",
        "tab-kilos": "tab-1",
        "tab-extras": "tab-2",
    }.get(tab_value, tab_value)
    validas = {f"tab-{indice}" for indice in range(len(CATEGORIAS))}
    return tab_value if tab_value in validas else "tab-0"


def _catalog_tab_categoria(categoria):
    try:
        return f"tab-{CATEGORIAS.index(categoria)}"
    except ValueError:
        return "tab-0"


def get_cliente_filtro() -> str:
    """Cliente activo en sesión; usa C001 como fallback de compatibilidad."""
    if app.config["TENANT_ISOLATION_MODE"]:
        return app.config["ISOLATED_TENANT_ID"]
    return session.get("cliente_id", "C001")


def _add_column_if_missing(conn, table_name: str, column_sql: str, column_name: str):
    """Agrega una columna solo si no existe (compatible con SQLite/PostgreSQL)."""
    if conn.dialect.name == "sqlite":
        cols = conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
        # Si la tabla no existe en este bind, no intentar ALTER TABLE.
        if not cols:
            return
        existing = {c[1] for c in cols}
    else:
        inspector = inspect(conn)
        if not inspector.has_table(table_name):
            return
        existing = {c["name"] for c in inspector.get_columns(table_name)}

    if column_name not in existing:
        conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def _get_all_db_engines():
    """Retorna engines únicos (default + binds) para aplicar migraciones livianas."""
    engines = [db.engine]
    try:
        engines.extend(db.engines.values())
    except Exception:
        pass

    unique = []
    seen = set()
    for eng in engines:
        key = id(eng)
        if key in seen:
            continue
        seen.add(key)
        unique.append(eng)
    return unique


def assert_isolated_databases():
    """Impide iniciar una instancia dedicada si contiene datos de otro tenant."""
    if not app.config["TENANT_ISOLATION_MODE"]:
        return
    tenant_id = app.config["ISOLATED_TENANT_ID"]
    violations = []
    for engine in _get_all_db_engines():
        inspector = inspect(engine)
        preparer = engine.dialect.identifier_preparer
        with engine.connect() as conn:
            for table_name in inspector.get_table_names():
                columns = {column["name"] for column in inspector.get_columns(table_name)}
                tenant_column = "id" if table_name == "clientes" else "cliente_id"
                if tenant_column not in columns:
                    continue
                table_sql = preparer.quote(table_name)
                column_sql = preparer.quote(tenant_column)
                statement = text(
                    f"SELECT {column_sql} FROM {table_sql} "
                    f"WHERE {column_sql} IS NULL OR {column_sql} <> :tenant_id LIMIT 1"
                )
                if conn.execute(statement, {"tenant_id": tenant_id}).first() is not None:
                    violations.append(f"{engine.url.database}:{table_name}")
    if violations:
        raise RuntimeError(
            "TENANT_ISOLATION_MODE no puede activarse: existen datos de otro tenant en "
            + ", ".join(violations)
        )


def ensure_multitenant_schema():
    """Migración liviana para multi-tenant sin depender de Alembic."""
    for engine in _get_all_db_engines():
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS clientes (
                    id VARCHAR(10) PRIMARY KEY,
                    nombre VARCHAR(160) NOT NULL UNIQUE,
                    plan VARCHAR(40) DEFAULT 'basico',
                    estado VARCHAR(20) DEFAULT 'activo',
                    fecha_creacion VARCHAR(20)
                )
                """
            )

            tenant_targets = [
                "tiendas", "usuarios", "inventario_items", "historial",
                "inventario_snapshots", "delivery_productos", "delivery_ventas",
                "stock_thresholds", "producto_precios", "inventario_desc_snapshots",
                "registros_averiados", "registros_vencimiento", "sincronizacion_log",
            ]
            for table_name in tenant_targets:
                _add_column_if_missing(conn, table_name,
                                       "cliente_id VARCHAR(10) NOT NULL DEFAULT 'C001'", "cliente_id")

            _add_column_if_missing(conn, "registros_averiados",
                                   "sinc_estado VARCHAR(20) NOT NULL DEFAULT 'pendiente'", "sinc_estado")
            _add_column_if_missing(conn, "registros_averiados",
                                   "periodo_id INTEGER", "periodo_id")
            _add_column_if_missing(conn, "registros_vencimiento",
                                   "sinc_estado VARCHAR(20) NOT NULL DEFAULT 'pendiente'", "sinc_estado")
            _add_column_if_missing(conn, "usuarios",
                                   "password_hash VARCHAR(256)", "password_hash")
            _add_column_if_missing(conn, "usuarios",
                           "ultimo_periodo_notificado_id INTEGER NOT NULL DEFAULT 0", "ultimo_periodo_notificado_id")
            _add_column_if_missing(conn, "usuarios",
                           "catalogo_version_recibida INTEGER NOT NULL DEFAULT 0", "catalogo_version_recibida")
            _add_column_if_missing(conn, "productos",
                           "visible_empleado BOOLEAN NOT NULL DEFAULT 1", "visible_empleado")
            _add_column_if_missing(conn, "productos",
                           "catalogo_version INTEGER NOT NULL DEFAULT 0", "catalogo_version")
            _add_column_if_missing(conn, "delivery_ventas",
                                   "periodo_id INTEGER", "periodo_id")
            _add_column_if_missing(conn, "delivery_ventas",
                                   "estado_periodo VARCHAR(20) NOT NULL DEFAULT 'sin_periodo'", "estado_periodo")

            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_tiendas_cliente_id ON tiendas(cliente_id)")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_usuarios_cliente_id ON usuarios(cliente_id)")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_productos_catalogo_version ON productos(catalogo_version)")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_registros_averiados_periodo_id ON registros_averiados(periodo_id)")

            # Nuevas tablas del módulo de auditoría (creadas por SQLAlchemy en init_db,
            # aquí solo migramos columnas faltantes si la tabla ya existía)
            audit_tables = [
                "inventario_periodos", "conteo_detalle", "ajustes_inventario",
                "excel_importados", "excel_detalles", "excel_detalle_ediciones", "auditoria_resultados",
                "justificaciones", "productos_relacionados", "configuracion_sistema",
            ]
            for tbl in audit_tables:
                _add_column_if_missing(conn, tbl, "cliente_id VARCHAR(10) NOT NULL DEFAULT 'C001'", "cliente_id")
            _add_column_if_missing(conn, "inventario_periodos",
                                   "informe_ia_markdown TEXT", "informe_ia_markdown")
            _add_column_if_missing(conn, "inventario_periodos",
                                   "informe_ia_generado TIMESTAMP", "informe_ia_generado")
            _add_column_if_missing(conn, "ajustes_inventario",
                                   "impacta_stock BOOLEAN NOT NULL DEFAULT 1", "impacta_stock")
            for col_sql, col_name in [
                ("primera_carga TIMESTAMP",                      "primera_carga"),
                ("veces_sincronizado INTEGER NOT NULL DEFAULT 1", "veces_sincronizado"),
            ]:
                _add_column_if_missing(conn, "conteo_detalle", col_sql, col_name)
            _add_column_if_missing(conn, "stock_thresholds",
                                   "producto_id INTEGER REFERENCES productos(id)", "producto_id")
            _add_column_if_missing(conn, "producto_precios",
                                   "producto_id INTEGER REFERENCES productos(id)", "producto_id")
            _add_column_if_missing(conn, "producto_precios",
                                   "precio_por_caja REAL", "precio_por_caja")
            _add_column_if_missing(conn, "productos",
                                   "codigo_articulo VARCHAR(40)", "codigo_articulo")
            _add_column_if_missing(conn, "historial",
                                   "snapshot_id INTEGER REFERENCES inventario_snapshots(id)", "snapshot_id")
            for col_sql, col_name in [
                ("periodo_id INTEGER", "periodo_id"),
                ("tipo_movimiento VARCHAR(30) NOT NULL DEFAULT 'original'", "tipo_movimiento"),
                ("usuario_anterior VARCHAR(80) NOT NULL DEFAULT ''", "usuario_anterior"),
                ("cantidad_anterior REAL", "cantidad_anterior"),
                ("version INTEGER NOT NULL DEFAULT 1", "version"),
                ("origen_carga VARCHAR(40) NOT NULL DEFAULT 'carga_manual'", "origen_carga"),
            ]:
                _add_column_if_missing(conn, "historial", col_sql, col_name)
            for col_sql, col_name in [
                ("periodo_id INTEGER", "periodo_id"),
                ("usuario_ultima_carga VARCHAR(80) NOT NULL DEFAULT ''", "usuario_ultima_carga"),
                ("version INTEGER NOT NULL DEFAULT 1", "version"),
                ("fue_sobreescrito BOOLEAN NOT NULL DEFAULT 0", "fue_sobreescrito"),
                ("origen_carga VARCHAR(40) NOT NULL DEFAULT 'carga_manual'", "origen_carga"),
            ]:
                _add_column_if_missing(conn, "inventario_items", col_sql, col_name)
            for col_sql, col_name in [
                ("fue_sobreescrito BOOLEAN NOT NULL DEFAULT 0", "fue_sobreescrito"),
                ("version_ultima_carga INTEGER NOT NULL DEFAULT 1", "version_ultima_carga"),
                ("origen_carga VARCHAR(40) NOT NULL DEFAULT 'carga_manual'", "origen_carga"),
            ]:
                _add_column_if_missing(conn, "conteo_detalle", col_sql, col_name)
            for col_sql, col_name in [
                ("producto_id INTEGER REFERENCES productos(id)", "producto_id"),
                ("estado_vinculacion VARCHAR(20) NOT NULL DEFAULT 'pendiente'", "estado_vinculacion"),
                ("excluido_auditoria BOOLEAN NOT NULL DEFAULT 0",            "excluido_auditoria"),
                ("motivo_exclusion VARCHAR(120)",                            "motivo_exclusion"),
            ]:
                _add_column_if_missing(conn, "excel_detalles", col_sql, col_name)
            _add_column_if_missing(conn, "auditoria_resultados",
                                   "fuente_costo VARCHAR(20) NOT NULL DEFAULT 'Sin costo'", "fuente_costo")
            for col_sql, col_name in [
                ("factor_desvio_compra REAL NOT NULL DEFAULT 0",           "factor_desvio_compra"),
                ("diferencia_anterior_compensada REAL NOT NULL DEFAULT 0", "diferencia_anterior_compensada"),
                ("cantidad_merma REAL NOT NULL DEFAULT 0",                 "cantidad_merma"),
                ("cantidad_vencida REAL NOT NULL DEFAULT 0",               "cantidad_vencida"),
                ("cantidad_averiada REAL NOT NULL DEFAULT 0",              "cantidad_averiada"),
                ("ventas_delivery REAL NOT NULL DEFAULT 0",                "ventas_delivery"),
                ("venta_teorica REAL NOT NULL DEFAULT 0",                  "venta_teorica"),
            ]:
                _add_column_if_missing(conn, "auditoria_resultados", col_sql, col_name)
            for col_sql, col_name in [
                ("orden_carga INTEGER NOT NULL DEFAULT 0", "orden_carga"),
                ("analisis_json TEXT", "analisis_json"),
                ("analisis_motor VARCHAR(40)", "analisis_motor"),
                ("analisis_precision REAL", "analisis_precision"),
                ("analisis_estado VARCHAR(30)", "analisis_estado"),
                ("analisis_fecha TIMESTAMP", "analisis_fecha"),
            ]:
                _add_column_if_missing(conn, "facturas_compra", col_sql, col_name)

            # Renombre de categoría conservando instalaciones existentes.
            # Se actualizan todas las tablas que almacenan la categoría como texto.
            tablas_categoria = {
                "productos", "inventario_items", "historial", "producto_precios",
                "registros_averiados", "registros_vencimiento", "conteo_detalle",
                "auditoria_resultados",
            }
            tablas_existentes = set(inspect(conn).get_table_names())
            for tabla in sorted(tablas_categoria & tablas_existentes):
                columnas = {columna["name"] for columna in inspect(conn).get_columns(tabla)}
                if "categoria" in columnas:
                    conn.exec_driver_sql(
                        f"UPDATE {tabla} SET categoria = 'Fanee' WHERE categoria = 'Extras'"
                    )
            if "inventario_borradores" in tablas_existentes:
                if conn.dialect.name == "postgresql":
                    conn.exec_driver_sql(
                        "UPDATE inventario_borradores "
                        "SET contenido_json = REPLACE(contenido_json::text, "
                        "'\"Extras\"', '\"Fanee\"')::jsonb "
                        "WHERE contenido_json::text LIKE '%\"Extras\"%'"
                    )
                else:
                    conn.exec_driver_sql(
                        "UPDATE inventario_borradores "
                        "SET contenido_json = REPLACE(contenido_json, '\"Extras\"', '\"Fanee\"') "
                        "WHERE contenido_json LIKE '%\"Extras\"%'"
                    )


# --------------------------------------------------------------------------- #
#  Inicializacion / seed de base de datos
# --------------------------------------------------------------------------- #
def init_db():
    """Crea las tablas e inserta los datos iniciales si la BD esta vacia."""
    # En SQLite se conserva compatibilidad con instalaciones locales existentes.
    if db.engine.dialect.name == "postgresql":
        inspector = inspect(db.engine)
        if "alembic_version" not in inspector.get_table_names():
            raise RuntimeError(
                "PostgreSQL no esta migrado. Ejecuta `alembic upgrade head` antes de iniciar Netward."
            )
        with db.engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if version != "20260906_08":
            raise RuntimeError(
                f"Esquema PostgreSQL desactualizado ({version or 'sin version'}). "
                "Ejecuta `alembic upgrade head`."
            )
    else:
        # SQLite conserva arranque automatico para desarrollo e instalaciones locales.
        db.metadata.create_all(bind=db.engine, checkfirst=True)
        ensure_multitenant_schema()
    assert_isolated_databases()

    if Cliente.query.count() == 0:
        for c in CLIENTES_DEFAULT:
            db.session.add(Cliente(id=c["id"], nombre=c["nombre"],
                                   plan=c.get("plan", "basico"),
                                   estado=c.get("estado", "activo")))

    if Tienda.query.count() == 0:
        for t in TIENDAS_DEFAULT:
            db.session.add(Tienda(id=t["id"], cliente_id=t.get("cliente_id", "C001"),
                                  nombre=t["nombre"],
                                  es_default=t["es_default"], activa=True))
    else:
        for t in Tienda.query.filter((Tienda.cliente_id.is_(None)) | (Tienda.cliente_id == "")).all():
            t.cliente_id = "C001"

    if Usuario.query.count() == 0:
        for u in USUARIOS_DEFAULT:
            db.session.add(Usuario(username=u["username"],
                                   password_hash=generate_password_hash(u["password"]),
                                   cliente_id=u.get("cliente_id", "C001"),
                                   rol=u["rol"],
                                   tienda_id=u["tienda_id"]))
    else:
        for u in Usuario.query.filter((Usuario.cliente_id.is_(None)) | (Usuario.cliente_id == "")).all():
            u.cliente_id = "C001"
        # Asignar contrasena a usuarios existentes que no la tienen
        pwd_map = {u["username"]: u["password"] for u in USUARIOS_DEFAULT}
        for u in Usuario.query.filter(Usuario.password_hash.is_(None)).all():
            raw = pwd_map.get(u.username, "netward2025")
            u.password_hash = generate_password_hash(raw)

    if Producto.query.count() == 0:
        for categoria, productos in PRODUCTOS_BASE.items():
            for nombre in productos:
                db.session.add(Producto(nombre=nombre, categoria=categoria, visible_empleado=True))

    if StockThreshold.query.count() == 0:
        for producto, th in STOCK_THRESHOLDS_DEFAULT.items():
            db.session.add(StockThreshold(producto=producto,
                                          critico=th["critico"], medio=th["medio"]))

    if DeliveryProducto.query.count() == 0:
        for d in DELIVERY_DEFAULT:
            db.session.add(DeliveryProducto(nombre=d["nombre"], precio=d["precio"],
                                            es_promocion=d["es_promocion"], activo=d["activo"]))

    # Versiones anteriores usaban "Excel Importado" como estado operativo.
    # Importar el archivo es un dato asociado, no una transición del período.
    # Reparamos esos registros para que vuelvan a ser visibles al empleado.
    for periodo in InventarioPeriodo.query.filter_by(estado="Excel Importado").all():
        tiene_auditoria = AuditoriaResultado.query.filter_by(
            periodo_id=periodo.id
        ).first() is not None
        tiene_carga = ConteoDetalle.query.filter_by(
            periodo_id=periodo.id,
            fue_cargado=True,
        ).first() is not None
        periodo.estado = "Auditado" if tiene_auditoria else ("Cargado" if tiene_carga else "Abierto")

    db.session.commit()
    # Rellena producto_id FK donde falte (silencioso si no hay registros)
    backfill_producto_ids()


def get_thresholds():
    """Devuelve los umbrales de stock como diccionario."""
    set_database_bind(get_active_bind())
    return {t.producto: {"critico": t.critico, "medio": t.medio}
            for t in StockThreshold.query.all()}


# --------------------------------------------------------------------------- #
#  Autenticacion (MODO BETA)
# --------------------------------------------------------------------------- #
def login_required(rol=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "usuario" not in session:
                return redirect(url_for("login"))
            if not rol_permitido(session.get("rol"), rol):
                flash("No tienes permisos para acceder a esa seccion.", "error")
                return redirect(url_for("index"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


NEXA_SECCIONES = {
    "resumen": {
        "titulo": "Resumen administrativo",
        "contexto": "Indicadores generales y prioridades",
        "orientacion": "Prioriza alertas, cargas pendientes y períodos que requieren revisión.",
        "preguntas": [
            ("¿Qué debería revisar primero hoy?", "Prioridades de hoy"),
            ("Resume las alertas y pendientes actuales.", "Resumir pendientes"),
            ("¿Qué indicador merece atención y por qué?", "Revisar indicadores"),
        ],
    },
    "inventario": {
        "titulo": "Inventario",
        "contexto": "Stock, productos y cargas por tienda",
        "orientacion": "Contrasta stock, productos sin carga y registros pendientes de sincronización.",
        "preguntas": [
            ("¿Qué productos o cargas de inventario debería revisar?", "Qué revisar"),
            ("¿Hay registros pendientes de sincronización?", "Pendientes de envío"),
            ("¿Cómo interpreto el estado actual del inventario?", "Explicar inventario"),
        ],
    },
    "historial": {
        "titulo": "Historial",
        "contexto": "Movimientos y cambios registrados",
        "orientacion": "Busca cambios recientes, repeticiones y movimientos que necesiten trazabilidad.",
        "preguntas": [
            ("Resume los movimientos registrados recientemente.", "Resumen reciente"),
            ("¿Qué cambios conviene verificar en el historial?", "Cambios a verificar"),
            ("¿Cómo puedo rastrear quién modificó un producto?", "Rastrear cambios"),
        ],
    },
    "delivery": {
        "titulo": "Delivery",
        "contexto": "Ventas y catálogo de delivery",
        "orientacion": "Revisa ventas registradas, productos activos y su relación con Auditoría.",
        "preguntas": [
            ("¿Qué debería validar en las ventas de Delivery?", "Validar ventas"),
            ("¿Cómo impacta Delivery en la venta real?", "Impacto en auditoría"),
            ("Resume el estado del módulo Delivery.", "Resumen de Delivery"),
        ],
    },
    "averiados": {
        "titulo": "Averiados",
        "contexto": "Bajas por productos dañados",
        "orientacion": "Verifica cantidades, evidencia, sincronización y que no se imputen al empleado.",
        "preguntas": [
            ("¿Qué registros averiados requieren revisión?", "Pendientes de revisión"),
            ("¿Cómo impactan los averiados en Auditoría?", "Impacto en auditoría"),
            ("¿Qué evidencia debería solicitar para un averiado?", "Evidencia necesaria"),
        ],
    },
    "vencimientos": {
        "titulo": "Vencimientos",
        "contexto": "Productos vencidos o próximos a vencer",
        "orientacion": "Prioriza fechas cercanas, cantidades y bajas todavía no revisadas.",
        "preguntas": [
            ("¿Qué vencimientos debería atender primero?", "Priorizar vencimientos"),
            ("¿Cómo impactan los vencidos en Auditoría?", "Impacto en auditoría"),
            ("¿Qué registros aún necesitan revisión?", "Pendientes de revisión"),
        ],
    },
    "documentacion": {
        "titulo": "Documentación oficial",
        "contexto": "Excel oficial y facturas PDF por período",
        "orientacion": "Confirma que Excel y PDF pertenezcan al mismo período y completa vínculos pendientes.",
        "preguntas": [
            ("¿Qué documentación está incompleta o pendiente?", "Documentos pendientes"),
            ("¿El Excel y las facturas pertenecen al mismo período?", "Validar período"),
            ("¿Qué productos de las facturas necesitan vinculación?", "Vínculos pendientes"),
        ],
    },
    "auditoria": {
        "titulo": "Auditoría",
        "contexto": "Períodos, diferencias y evidencia",
        "orientacion": "Empieza por resultados críticos, pendientes y diferencias de mayor impacto.",
        "preguntas": [
            ("Proporciona la información principal de este período y destaca lo más importante.", "Proporcionar la información principal"),
            ("Resume todo el informe de este período, sus resultados y pendientes.", "Resumir mi período"),
            ("Analicemos este período: explícame qué ocurrió y qué debería revisar.", "Analizar mi período"),
        ],
    },
    "relaciones": {
        "titulo": "Productos relacionados",
        "contexto": "Relaciones de consumo y alertas",
        "orientacion": "Revisa relaciones duplicadas, ratios y productos que suelen consumirse juntos.",
        "preguntas": [
            ("¿Qué relaciones de productos debería revisar?", "Revisar relaciones"),
            ("¿Cómo ayudan estas relaciones a detectar diferencias?", "Explicar alertas"),
            ("¿Qué buenas prácticas debo usar al crear una relación?", "Buenas prácticas"),
        ],
    },
    "catalogo": {
        "titulo": "Catálogo",
        "contexto": "Productos, precios y conversiones",
        "orientacion": "Revisa productos sin precio, conversiones incompletas y cambios sin publicar.",
        "preguntas": [
            ("¿Qué productos tienen datos incompletos?", "Datos incompletos"),
            ("¿Qué precios o conversiones debería verificar?", "Revisar precios"),
            ("¿Hay cambios de catálogo pendientes de enviar?", "Cambios pendientes"),
        ],
    },
    "tiendas": {
        "titulo": "Tiendas",
        "contexto": "Configuración y estado de sucursales",
        "orientacion": "Confirma tiendas activas, asignaciones y configuración operativa.",
        "preguntas": [
            ("¿Qué configuración de tiendas debería revisar?", "Revisar configuración"),
            ("¿Cuántas tiendas están activas o inactivas?", "Estado de tiendas"),
            ("¿Qué puede impedir que una tienda sincronice?", "Problemas de sincronización"),
        ],
    },
    "usuarios": {
        "titulo": "Usuarios",
        "contexto": "Administradores, empleados y asignaciones",
        "orientacion": "Verifica roles, tiendas asignadas y usuarios que aún no recibieron el catálogo.",
        "preguntas": [
            ("¿Qué asignaciones de usuarios debería revisar?", "Revisar asignaciones"),
            ("¿Hay empleados pendientes de recibir el catálogo?", "Recepción pendiente"),
            ("¿Cómo comprobar roles y permisos?", "Roles y permisos"),
        ],
    },
    "sincronizacion": {
        "titulo": "Sincronización",
        "contexto": "Envíos, recepciones y catálogo",
        "orientacion": "Distingue registros pendientes de envío de cambios de catálogo pendientes de recepción.",
        "preguntas": [
            ("¿Qué tiendas o empleados están pendientes de sincronizar?", "Pendientes"),
            ("¿Cuál es la diferencia entre enviar y recibir?", "Explicar sincronización"),
            ("¿Hay productos nuevos pendientes de recepción?", "Catálogo pendiente"),
        ],
    },
}


def _nexa_seccion_actual(endpoint=None):
    endpoint = endpoint or request.endpoint or ""
    if endpoint.startswith("desc."):
        return "documentacion"
    if "auditoria" in endpoint or "periodo" in endpoint or endpoint == "admin_reporte_gerencial":
        return "auditoria"
    return {
        "admin_dashboard": "resumen", "admin_inventario": "inventario",
        "admin_historial": "historial", "admin_delivery": "delivery",
        "admin_averiados": "averiados", "admin_vencimientos": "vencimientos",
        "admin_productos_relacionados": "relaciones", "admin_precios": "catalogo",
        "admin_configuracion": "tiendas", "admin_usuarios": "usuarios",
        "admin_sincronizacion": "sincronizacion",
    }.get(endpoint, "resumen")


def _nexa_contexto_seccion(seccion, cliente_id):
    definicion = NEXA_SECCIONES.get(seccion, NEXA_SECCIONES["resumen"])
    resumen = {}
    if seccion in {"resumen", "inventario", "sincronizacion"}:
        resumen["inventario_pendiente"] = InventarioItem.query.filter_by(
            cliente_id=cliente_id, sinc_estado="pendiente"
        ).count()
        resumen["inventario_sincronizado"] = InventarioItem.query.filter_by(
            cliente_id=cliente_id, sinc_estado="sincronizado"
        ).count()
    if seccion in {"resumen", "auditoria"}:
        resumen["periodos_abiertos"] = InventarioPeriodo.query.filter_by(
            cliente_id=cliente_id, estado="Abierto"
        ).count()
        resumen["periodos_cerrados"] = InventarioPeriodo.query.filter_by(
            cliente_id=cliente_id, estado="Cerrado"
        ).count()
        resumen["resultados_criticos"] = AuditoriaResultado.query.filter_by(
            cliente_id=cliente_id, severidad="Crítico"
        ).filter(AuditoriaResultado.estado_auditoria != "Archivado").count()
    if seccion == "historial":
        resumen["movimientos_registrados"] = HistorialMovimiento.query.filter_by(
            cliente_id=cliente_id
        ).count()
    if seccion == "delivery":
        resumen["productos_delivery"] = DeliveryProducto.query.filter_by(
            cliente_id=cliente_id
        ).count()
        resumen["ventas_delivery"] = DeliveryVenta.query.filter_by(
            cliente_id=cliente_id
        ).count()
    if seccion in {"resumen", "averiados"}:
        resumen["averiados_sin_revisar"] = RegistroAveriado.query.filter_by(
            cliente_id=cliente_id, revisado=False
        ).count()
    if seccion in {"resumen", "vencimientos"}:
        resumen["vencimientos_sin_revisar"] = RegistroVencimiento.query.filter_by(
            cliente_id=cliente_id, revisado=False
        ).count()
    if seccion == "documentacion":
        resumen["excel_importados"] = ExcelImportado.query.filter_by(cliente_id=cliente_id).count()
        resumen["facturas_pdf"] = FacturaCompra.query.filter_by(cliente_id=cliente_id).count()
        resumen["lineas_pdf_pendientes"] = (
            FacturaCompraDetalle.query.join(FacturaCompra)
            .filter(
                FacturaCompra.cliente_id == cliente_id,
                ~FacturaCompraDetalle.estado_vinculacion.in_(("vinculado", "aplicado", "fuera_rango")),
            ).count()
        )
    if seccion == "relaciones":
        resumen["relaciones_registradas"] = ProductoRelacionado.query.filter_by(
            cliente_id=cliente_id
        ).count()
    if seccion == "catalogo":
        resumen["productos"] = Producto.query.count()
        resumen["productos_sin_publicar"] = Producto.query.filter_by(visible_empleado=False).count()
        resumen["precios_configurados"] = ProductoPrecio.query.filter_by(cliente_id=cliente_id).count()
    if seccion == "tiendas":
        resumen["tiendas_activas"] = Tienda.query.filter_by(cliente_id=cliente_id, activa=True).count()
        resumen["tiendas_inactivas"] = Tienda.query.filter_by(cliente_id=cliente_id, activa=False).count()
    if seccion in {"usuarios", "sincronizacion"}:
        usuarios = Usuario.query.filter_by(cliente_id=cliente_id).all()
        resumen["administradores"] = sum(u.rol == "administrador" for u in usuarios)
        resumen["empleados"] = sum(u.rol == "empleado" for u in usuarios)
        if seccion == "sincronizacion":
            resumen["empleados_con_catalogo_pendiente"] = sum(
                catalogo_pendiente_usuario(cliente_id, u.username)[0]
                for u in usuarios if u.rol == "empleado"
            )
    return {
        "alcance": "seccion",
        "seccion": {"clave": seccion, "titulo": definicion["titulo"]},
        "resumen": resumen,
        "orientacion": definicion["orientacion"],
    }


@app.context_processor
def inject_globals():
    """Variables disponibles en todas las plantillas."""
    ctx = {
        "app_nombre": "Netward",
        "anio": date.today().year,
        "asset_v": app.config.get("ASSET_VERSION", "1"),
        "sesion_usuario": session.get("usuario"),
        "sesion_rol": session.get("rol"),
        "sesion_tienda": session.get("tienda_nombre"),
        "sync_ultimo_envio": None,
        "sync_ultima_recepcion": None,
        "notif_averiados": 0,
        "notif_vencimientos": 0,
        "notif_admin_unread": 0,
        "notif_sincronizacion": 0,
        "sync_pendientes": 0,
        "notif_catalogo_pendiente": False,
        "notif_catalogo_cambios": 0,
        "notif_periodo_abierto": 0,
        "notif_empleado_unread": 0,
        "nexa_seccion": "resumen",
        "nexa_titulo": "Resumen administrativo",
        "nexa_contexto": "Indicadores generales y prioridades",
        "nexa_preguntas": NEXA_SECCIONES["resumen"]["preguntas"],
        "nexa_estado": AIConfig.from_env().public_status(),
        "nexa_periodo_id": None,
    }
    if session.get("rol") == "empleado" and session.get("usuario"):
        cliente_id = get_cliente_filtro()
        u = session["usuario"]
        t = session.get("tienda_id", "")
        def _last(tipo):
            r = (SincronizacionLog.query
                 .filter_by(cliente_id=cliente_id, usuario=u, tienda_id=t, tipo=tipo)
                 .order_by(SincronizacionLog.timestamp.desc())
                 .first())
            if r:
                return r.timestamp.strftime("%d/%m/%y %H:%M")
            return None
        try:
            ctx["sync_ultimo_envio"]      = _last("envio")
            ctx["sync_ultima_recepcion"]  = _last("recepcion")
            ctx["sync_pendientes"] = InventarioItem.query.filter_by(
                cliente_id=cliente_id, tienda_id=t, sinc_estado="pendiente").count()
            catalogo_pendiente, catalogo_cambios = catalogo_pendiente_usuario(cliente_id, u)
            ctx["notif_catalogo_pendiente"] = catalogo_pendiente
            ctx["notif_catalogo_cambios"] = catalogo_cambios
            usuario = Usuario.query.filter_by(cliente_id=cliente_id, username=u).first()
            periodo_reciente = _periodo_abierto_mas_reciente(cliente_id, t)
            if usuario and periodo_reciente and periodo_reciente.id > int(usuario.ultimo_periodo_notificado_id or 0):
                ctx["notif_periodo_abierto"] = 1

            unread = NotificacionUsuario.query.filter_by(
                cliente_id=cliente_id,
                username=u,
                leida=False,
            ).count()
            ctx["notif_empleado_unread"] = unread
            ctx["notif_periodo_abierto"] = NotificacionUsuario.query.filter_by(
                cliente_id=cliente_id,
                username=u,
                tipo="periodo_abierto",
                leida=False,
            ).count()
        except Exception:
            pass
    # Solo consultar notificaciones si hay sesion activa de administrador
    if session.get("rol") == "administrador" and session.get("usuario"):
        cliente_id = get_cliente_filtro()
        username_actual = str(session.get("usuario") or "")
        nexa_seccion = _nexa_seccion_actual()
        nexa_definicion = NEXA_SECCIONES[nexa_seccion]
        ctx.update(
            nexa_seccion=nexa_seccion,
            nexa_titulo=nexa_definicion["titulo"],
            nexa_contexto=nexa_definicion["contexto"],
            nexa_preguntas=nexa_definicion["preguntas"],
            nexa_estado=AIConfig.from_env().public_status(),
            nexa_periodo_id=(request.view_args or {}).get("periodo_id"),
        )
        try:
            ctx["notif_averiados"]    = RegistroAveriado.query.filter_by(cliente_id=cliente_id, sinc_estado="sincronizado", revisado=False).count()
            ctx["notif_vencimientos"] = RegistroVencimiento.query.filter_by(cliente_id=cliente_id, sinc_estado="sincronizado", revisado=False).count()
            ctx["notif_admin_unread"] = NotificacionUsuario.query.filter_by(
                cliente_id=cliente_id,
                username=username_actual,
                leida=False,
            ).count()
            from core.inventario import estado_sincronizacion_catalogo
            ctx["notif_sincronizacion"] = estado_sincronizacion_catalogo(
                cliente_id,
                detallado=True,
            )["total"]
            ctx["notif_admin_unread"] = len(_construir_alertas_admin(
                cliente_id,
                username_actual,
                session.get("admin_tienda_id", "ALL"),
            ))
        except Exception:
            ctx["notif_averiados"]    = 0
            ctx["notif_vencimientos"] = 0
            ctx["notif_sincronizacion"] = 0
            ctx["notif_admin_unread"] = 0
        try:
            ctx["tiendas_topbar"] = Tienda.query.filter_by(cliente_id=cliente_id, activa=True).all()
        except Exception:
            ctx["tiendas_topbar"] = []
        ctx["tienda_filtro"] = session.get("admin_tienda_id", "ALL")
        ctx["hoy_es"] = _fecha_es(date.today())
    return ctx


@app.route("/")
def index():
    if "usuario" not in session:
        return redirect(url_for("login"))
    if session.get("rol") == "administrador":
        return redirect(url_for("admin_inventario"))
    return redirect(url_for("empleado_inventario"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("usuario") or "").strip()
        contrasena = request.form.get("contrasena") or ""

        if not username or not contrasena:
            flash("Por favor, completa todos los campos.", "warning")
            return redirect(url_for("login"))

        usuario_query = Usuario.query.filter_by(username=username)
        if app.config["TENANT_ISOLATION_MODE"]:
            usuario_query = usuario_query.filter_by(
                cliente_id=app.config["ISOLATED_TENANT_ID"]
            )
        usuario = usuario_query.first()
        if not usuario:
            flash(f"Usuario '{username}' no reconocido.", "error")
            return redirect(url_for("login"))

        if not usuario.password_hash or not check_password_hash(usuario.password_hash, contrasena):
            flash("Contrasena incorrecta.", "error")
            return redirect(url_for("login"))

        session.clear()          # Eliminar cualquier sesion anterior antes de crear una nueva
        session.permanent = True # Aplicar PERMANENT_SESSION_LIFETIME
        session["usuario"] = usuario.username
        session["cliente_id"] = get_cliente_filtro() if app.config["TENANT_ISOLATION_MODE"] else (usuario.cliente_id or "C001")
        session["rol"] = usuario.rol
        session["tienda_id"] = usuario.tienda_id
        session["admin_tienda_id"] = "ALL"
        if usuario.rol == "empleado":
            tienda = Tienda.query.filter_by(id=usuario.tienda_id, cliente_id=session["cliente_id"]).first()
            session["tienda_nombre"] = tienda.nombre if tienda else usuario.tienda_id
        else:
            session["tienda_nombre"] = "Todas las tiendas"

        flash(f"Bienvenido, {usuario.username}.", "success")
        return redirect(url_for("index"))

    usuarios_query = Usuario.query
    if app.config["TENANT_ISOLATION_MODE"]:
        usuarios_query = usuarios_query.filter_by(
            cliente_id=app.config["ISOLATED_TENANT_ID"]
        )
    usuarios = usuarios_query.order_by(Usuario.username).all()
    return render_template("login.html", usuarios=usuarios)


@app.route("/logout")
def logout():
    session.clear()
    flash("Sesion cerrada correctamente.", "success")
    return redirect(url_for("login"))


# --------------------------------------------------------------------------- #
#  Empleado - Inventario
# --------------------------------------------------------------------------- #
def _borrador_query(periodo_id):
    return InventarioBorrador.query.filter_by(
        cliente_id=get_cliente_filtro(),
        periodo_id=periodo_id,
        tienda_id=session.get("tienda_id"),
        usuario=session.get("usuario"),
    )


def get_carrito(periodo_id=None):
    """Recupera el borrador persistente del empleado para el período activo."""
    periodo_id = periodo_id or session.get("empleado_periodo_id")
    if not periodo_id or not session.get("usuario"):
        return []

    borrador = _borrador_query(periodo_id).first()
    if borrador:
        try:
            contenido = _json.loads(borrador.contenido_json or "[]")
            return contenido if isinstance(contenido, list) else []
        except (TypeError, ValueError):
            return []

    # Migra una carga que pudiera seguir en la sesión desde la versión anterior.
    legado = session.pop("carrito", None)
    if isinstance(legado, list) and legado:
        set_carrito(legado, periodo_id)
        return legado
    return []


def set_carrito(carrito, periodo_id=None, *, commit=True):
    """Guarda o elimina el borrador sin depender de la sesión del navegador."""
    periodo_id = periodo_id or session.get("empleado_periodo_id")
    if not periodo_id or not session.get("usuario"):
        return

    borrador = _borrador_query(periodo_id).first()
    if carrito:
        contenido = _json.dumps(carrito, ensure_ascii=False)
        if borrador:
            borrador.contenido_json = contenido
            borrador.actualizado = utc_now()
        else:
            db.session.add(InventarioBorrador(
                cliente_id=get_cliente_filtro(),
                periodo_id=periodo_id,
                tienda_id=session.get("tienda_id"),
                usuario=session.get("usuario"),
                contenido_json=contenido,
            ))
    elif borrador:
        db.session.delete(borrador)

    # El carrito completo ya no se guarda en la cookie de sesión.
    session.pop("carrito", None)
    session.modified = True
    if commit:
        db.session.commit()


def _safe_inv_tab(tab_value):
    return tab_value if tab_value in CATEGORIAS else CATEGORIAS[0]


def _redirect_inventario_context(default_anchor="sec-carga", *, allow_pending=True):
    active_tab = _safe_inv_tab(request.form.get("active_tab"))
    anchor = (request.form.get("anchor") or default_anchor).strip() or default_anchor
    periodo_id = request.form.get("periodo_id", type=int) or session.get("empleado_periodo_id")
    if allow_pending and request.form.get("return_to") == "productos_no_cargados":
        return redirect(url_for(
            "empleado_productos_no_cargados",
            periodo_id=periodo_id,
            tab=active_tab,
        ))
    return redirect(
        url_for("empleado_periodo_abierto", tab=active_tab, periodo_id=periodo_id)
        + f"#{anchor}"
    )


def _periodos_abiertos_empleado(cliente_id: str, tienda_id: str):
    actualizar_estados_periodos(cliente_id=cliente_id, tienda_id=tienda_id)
    return (
        InventarioPeriodo.query
        .filter_by(cliente_id=cliente_id, tienda_id=tienda_id)
        .filter(InventarioPeriodo.estado.in_(["Abierto", "Pendiente", "Cargado"]))
        .order_by(InventarioPeriodo.id.desc())
        .all()
    )


def _resolve_periodo_seleccionado_empleado(cliente_id: str, tienda_id: str):
    abiertos = _periodos_abiertos_empleado(cliente_id, tienda_id)
    if not abiertos:
        session.pop("empleado_periodo_id", None)
        return None, []

    # En POST manda el período incrustado en el formulario: evita que otra
    # pestaña del navegador cambie la sesión y desvíe una carga de período.
    selected_id = (
        request.form.get("periodo_id", type=int)
        or request.args.get("periodo_id", type=int)
        or session.get("empleado_periodo_id")
    )
    seleccionado = next((p for p in abiertos if p.id == selected_id), None)
    if seleccionado is None:
        seleccionado = abiertos[0]
    session["empleado_periodo_id"] = seleccionado.id
    return seleccionado, abiertos


@app.route("/empleado/inventario")
@login_required(rol="empleado")
def empleado_inventario():
    return redirect(url_for("empleado_periodo_abierto", tab=request.args.get("tab") or CATEGORIAS[0]))


@app.route("/empleado/periodo-abierto")
@login_required(rol="empleado")
def empleado_periodo_abierto():
    cliente_id = get_cliente_filtro()
    tienda_id = session["tienda_id"]
    periodo_activo, periodos_abiertos = _resolve_periodo_seleccionado_empleado(cliente_id, tienda_id)

    # El clic explícito en "Período abierto" reconoce los avisos del menú.
    if request.args.get("marcar_visto") == "1":
        NotificacionUsuario.query.filter_by(
            cliente_id=cliente_id,
            username=session.get("usuario"),
            tipo="periodo_abierto",
            leida=False,
        ).update({"leida": True}, synchronize_session=False)
        db.session.commit()

    if periodo_activo is None:
        flash("No hay período abierto asignado para tu tienda. Solicita al administrador crear uno.", "warning")
    else:
        usuario = Usuario.query.filter_by(cliente_id=cliente_id, username=session.get("usuario")).first()
        if usuario and int(usuario.ultimo_periodo_notificado_id or 0) < int(periodo_activo.id):
            usuario.ultimo_periodo_notificado_id = periodo_activo.id
            db.session.commit()
        session["ultimo_periodo_flash_id"] = periodo_activo.id

    carrito = get_carrito(periodo_activo.id) if periodo_activo else []
    cargas_periodo = (
        empleado_service.listar_cargas_periodo(
            cliente_id=cliente_id,
            tienda_id=tienda_id,
            periodo_id=periodo_activo.id,
        ) if periodo_activo else []
    )
    productos_cargados = empleado_service.combinar_cargas_para_vista(
        carrito=carrito,
        cargas_periodo=cargas_periodo,
        usuario=session.get("usuario") or "",
    )
    conflicto_carga = session.pop("conflicto_carga", None)
    periodos_vistos = session.get("borradores_vistos", [])
    borrador_recuperado = (
        bool(carrito)
        and periodo_activo is not None
        and periodo_activo.id not in periodos_vistos
    )
    if periodo_activo and periodo_activo.id not in periodos_vistos:
        session["borradores_vistos"] = periodos_vistos + [periodo_activo.id]
        session.modified = True

    return render_template(
        "empleado_inventario.html",
        **empleado_service.build_empleado_inventario_context(
            active_tab=request.args.get("tab") or CATEGORIAS[0],
            carrito=carrito,
            hoy=today_local_iso(),
            productos_cargados=productos_cargados,
            conflicto_carga=conflicto_carga,
        ),
        periodo_activo=periodo_activo,
        periodos_abiertos=periodos_abiertos,
        borrador_recuperado=borrador_recuperado,
    )


@app.route("/empleado/periodo-abierto/productos-no-cargados")
@login_required(rol="empleado")
def empleado_productos_no_cargados():
    cliente_id = get_cliente_filtro()
    tienda_id = session["tienda_id"]
    periodo_activo, _ = _resolve_periodo_seleccionado_empleado(cliente_id, tienda_id)
    if periodo_activo is None:
        flash("No hay un período abierto disponible para cargar productos.", "warning")
        return redirect(url_for("empleado_periodo_abierto"))

    carrito = get_carrito(periodo_activo.id)
    cargas_periodo = empleado_service.listar_cargas_periodo(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        periodo_id=periodo_activo.id,
    )
    productos_cargados = empleado_service.combinar_cargas_para_vista(
        carrito=carrito,
        cargas_periodo=cargas_periodo,
        usuario=session.get("usuario") or "",
    )
    contexto = empleado_service.build_empleado_inventario_context(
        active_tab=request.args.get("tab") or CATEGORIAS[0],
        carrito=carrito,
        hoy=today_local_iso(),
        productos_cargados=productos_cargados,
        conflicto_carga=None,
    )
    pendientes_todos = contexto["productos_no_cargados"]
    contexto["pendientes_por_categoria"] = {
        categoria: sum(
            1 for item in pendientes_todos if item["categoria"] == categoria
        )
        for categoria in CATEGORIAS
    }
    contexto["total_productos_no_cargados"] = len(pendientes_todos)
    contexto["productos_no_cargados"] = [
        item for item in pendientes_todos
        if item["categoria"] == contexto["active_tab"]
    ]
    contexto["hide_global_flash"] = False
    return render_template(
        "empleado_productos_no_cargados.html",
        **contexto,
        periodo_activo=periodo_activo,
    )


@app.route("/empleado/periodo-abierto/seleccionar", methods=["POST"])
@login_required(rol="empleado")
def empleado_periodo_seleccionar():
    cliente_id = get_cliente_filtro()
    tienda_id = session["tienda_id"]
    periodo_id = request.form.get("periodo_id", type=int)
    abiertos = _periodos_abiertos_empleado(cliente_id, tienda_id)
    seleccionado = next((p for p in abiertos if p.id == periodo_id), None)
    if not seleccionado:
        flash("El período seleccionado no está disponible o ya fue cerrado.", "warning")
        return redirect(url_for("empleado_periodo_abierto"))

    session["empleado_periodo_id"] = seleccionado.id
    usuario = Usuario.query.filter_by(cliente_id=cliente_id, username=session.get("usuario")).first()
    if usuario and int(usuario.ultimo_periodo_notificado_id or 0) < int(seleccionado.id):
        usuario.ultimo_periodo_notificado_id = seleccionado.id
        db.session.commit()
    session["ultimo_periodo_flash_id"] = seleccionado.id
    flash(f"Período #{seleccionado.numero} seleccionado.", "success")
    return redirect(url_for("empleado_periodo_abierto", periodo_id=seleccionado.id))


@app.route("/empleado/notificaciones")
@login_required(rol="empleado")
def empleado_notificaciones():
    cliente_id = get_cliente_filtro()
    username = session.get("usuario")
    # Abrir la campana equivale a ver el centro de notificaciones.
    NotificacionUsuario.query.filter_by(
        cliente_id=cliente_id,
        username=username,
        leida=False,
    ).update({"leida": True}, synchronize_session=False)
    db.session.commit()
    notificaciones = (
        NotificacionUsuario.query
        .filter_by(cliente_id=cliente_id, username=username)
        .order_by(NotificacionUsuario.id.desc())
        .limit(120)
        .all()
    )
    return render_template("empleado_notificaciones.html", notificaciones=notificaciones)


@app.route("/empleado/notificaciones/marcar-todas", methods=["POST"])
@login_required(rol="empleado")
def empleado_notificaciones_marcar_todas():
    cliente_id = get_cliente_filtro()
    username = session.get("usuario")
    marcadas = (
        NotificacionUsuario.query
        .filter_by(cliente_id=cliente_id, username=username, leida=False)
        .update({"leida": True}, synchronize_session=False)
    )
    db.session.commit()
    if marcadas:
        flash(f"Se marcaron {marcadas} notificaciones como leídas.", "success")
    else:
        flash("No había notificaciones nuevas para marcar.", "info")
    return redirect(url_for("empleado_notificaciones"))


@app.route("/empleado/notificaciones/<int:notif_id>/ir")
@login_required(rol="empleado")
def empleado_notificacion_ir(notif_id):
    cliente_id = get_cliente_filtro()
    username = session.get("usuario")
    tienda_id = session.get("tienda_id")

    notif = NotificacionUsuario.query.filter_by(
        id=notif_id,
        cliente_id=cliente_id,
        username=username,
    ).first()
    if notif is None:
        abort(404)

    notif.leida = True
    db.session.flush()

    if notif.tipo == "periodo_abierto" and notif.referencia_id:
        periodo = db.session.get(InventarioPeriodo, int(notif.referencia_id))
        if periodo and periodo.cliente_id == cliente_id and periodo.tienda_id == tienda_id:
            if periodo.estado in ("Abierto", "Pendiente", "Cargado"):
                session["empleado_periodo_id"] = periodo.id
                db.session.commit()
                return redirect(url_for("empleado_periodo_abierto", periodo_id=periodo.id))

            snapshot = (
                InventarioSnapshot.query
                .filter_by(cliente_id=cliente_id, tienda_id=tienda_id, usuario=username)
                .filter(InventarioSnapshot.fecha >= periodo.fecha_desde)
                .filter(InventarioSnapshot.fecha <= periodo.fecha_hasta)
                .order_by(InventarioSnapshot.fecha.desc(), InventarioSnapshot.id.desc())
                .first()
            )
            db.session.commit()
            if snapshot:
                return redirect(url_for("empleado_historial", fecha=snapshot.fecha))
            flash("Ese período ya está cerrado y no se encontraron cargas en tu historial para ese rango.", "info")
            return redirect(url_for("empleado_historial"))

    db.session.commit()
    return redirect(url_for("empleado_notificaciones"))


@app.route("/empleado/carrito/agregar", methods=["POST"])
@login_required(rol="empleado")
def carrito_agregar():
    cliente_id = get_cliente_filtro()
    tienda_id = session["tienda_id"]
    periodo_activo, _ = _resolve_periodo_seleccionado_empleado(cliente_id, tienda_id)
    if periodo_activo is None:
        flash("No puedes cargar inventario sin un período abierto activo.", "error")
        return _redirect_inventario_context("sec-carga")

    categoria = request.form.get("categoria")
    producto = (request.form.get("producto") or "").strip()
    cantidad_texto = (request.form.get("cantidad") or "").strip()
    ume = request.form.get("ume", "Unidad")
    estado_balde = (request.form.get("estado_balde") or "").strip()
    cantidad_baldes = (request.form.get("cantidad_baldes") or "").strip()
    peso_kg = (request.form.get("peso_kg") or "").strip()
    tipo_inventario = request.form.get("tipo_inventario", "Diario")
    if tipo_inventario not in TIPOS_INVENTARIO:
        tipo_inventario = "Diario"
    fecha = request.form.get("fecha", today_local_iso())
    detalle = request.form.get("detalle", "")
    usuario = session["usuario"]

    if not producto:
        flash("Selecciona un producto antes de agregar.", "warning")
        return _redirect_inventario_context("sec-carga")
    if producto_disponible_usuario(
        cliente_id, usuario, producto, categoria or CATEGORIAS[0]
    ) is None:
        flash(
            "Ese producto todavía no fue recibido en tu catálogo. "
            "Usa Enviar y recibir antes de cargarlo.",
            "warning",
        )
        return _redirect_inventario_context("sec-carga")

    if categoria == "Por Kilos":
        try:
            conteo_kilos = empleado_service.normalizar_conteo_kilos(
                estado_balde=estado_balde,
                cantidad_baldes=cantidad_baldes,
                peso_kg=peso_kg,
            )
            cantidad = conteo_kilos["cantidad"]
            ume = "kg"
        except ValueError as exc:
            flash(str(exc), "warning")
            return _redirect_inventario_context("sec-carga")
    else:
        if cantidad_texto == "":
            flash("Ingresa una cantidad antes de agregar.", "warning")
            return _redirect_inventario_context("sec-carga")
        try:
            cantidad = float(cantidad_texto)
        except ValueError:
            flash("Ingresa una cantidad válida.", "warning")
            return _redirect_inventario_context("sec-carga")
        if cantidad < 0:
            flash("La cantidad no puede ser negativa.", "warning")
            return _redirect_inventario_context("sec-carga")

    confirmar = request.form.get("confirmar_sobreescritura") == "1"
    version_esperada = request.form.get("version_esperada", type=int)
    carga_actual = empleado_service.obtener_carga_actual(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        periodo_id=periodo_activo.id,
        categoria=categoria or CATEGORIAS[0],
        producto=producto,
        excluir_usuario=usuario,
    )
    if carga_actual:
        version_vigente = carga_actual["version"]
        requiere_confirmacion = carga_actual["usuario"] != usuario
        confirmacion_vigente = confirmar and version_esperada == version_vigente
        if requiere_confirmacion and not confirmacion_vigente:
            session["conflicto_carga"] = {
                "accion": "agregar",
                "mensaje": f"Este producto ya fue cargado por {carga_actual['usuario']}. ¿Desea sobreescribir?",
                "usuario": carga_actual["usuario"],
                "cantidad_actual": carga_actual["cantidad"],
                "version": version_vigente,
                "categoria": categoria or CATEGORIAS[0],
                "producto": producto,
                "cantidad": cantidad,
                "ume": ume,
                "tipo_inventario": tipo_inventario,
                "fecha": fecha,
                "detalle": detalle,
                "estado_balde": estado_balde,
                "cantidad_baldes": cantidad_baldes,
                "peso_kg": peso_kg,
            }
            session.modified = True
            return _redirect_inventario_context("sec-carga", allow_pending=False)
        if carga_actual.get("origen") == "borrador":
            retirado = empleado_service.retirar_producto_de_otros_borradores(
                cliente_id=cliente_id,
                tienda_id=tienda_id,
                periodo_id=periodo_activo.id,
                usuario=usuario,
                categoria=categoria or CATEGORIAS[0],
                producto=producto,
                version_esperada=version_vigente,
            )
            if not retirado:
                flash("La carga cambió mientras confirmabas. Intenta nuevamente.", "warning")
                return _redirect_inventario_context("sec-carga")
            carga_base = empleado_service.obtener_carga_actual(
                cliente_id=cliente_id,
                tienda_id=tienda_id,
                periodo_id=periodo_activo.id,
                categoria=categoria or CATEGORIAS[0],
                producto=producto,
                excluir_usuario=usuario,
            )
            version_esperada = carga_base["version"] if carga_base else 0
            confirmar = bool(carga_base and carga_base["usuario"] != usuario)
        else:
            version_esperada = version_vigente
    else:
        version_esperada = 0

    carrito = get_carrito(periodo_activo.id)
    carrito, msg = empleado_service.add_carrito_item(
        carrito=carrito,
        categoria=categoria or CATEGORIAS[0],
        producto=producto,
        cantidad=cantidad,
        ume=ume,
        tipo_inventario=tipo_inventario,
        fecha=fecha,
        detalle=detalle,
        version_esperada=version_esperada,
        confirmar_sobreescritura=confirmar,
        estado_balde=estado_balde,
        cantidad_baldes=cantidad_baldes,
        peso_kg=peso_kg,
    )
    set_carrito(carrito, periodo_activo.id)
    flash(msg, "success")
    return _redirect_inventario_context("sec-carga")


@app.route("/empleado/carrito/eliminar/<int:idx>", methods=["POST"])
@login_required(rol="empleado")
def carrito_eliminar(idx):
    cliente_id = get_cliente_filtro()
    periodo_activo, _ = _resolve_periodo_seleccionado_empleado(cliente_id, session["tienda_id"])
    if periodo_activo is None:
        flash("El período del borrador ya no está abierto.", "warning")
        return _redirect_inventario_context("sec-carrito")
    carrito = get_carrito(periodo_activo.id)
    carrito, msg = empleado_service.remove_carrito_item(carrito, idx)
    if msg:
        set_carrito(carrito, periodo_activo.id)
        flash(msg, "info")
    return _redirect_inventario_context("sec-carrito")


@app.route("/empleado/carrito/limpiar", methods=["POST"])
@login_required(rol="empleado")
def carrito_limpiar():
    cliente_id = get_cliente_filtro()
    periodo_activo, _ = _resolve_periodo_seleccionado_empleado(cliente_id, session["tienda_id"])
    if periodo_activo:
        set_carrito([], periodo_activo.id)
    flash("Carrito limpiado.", "info")
    return _redirect_inventario_context("sec-carrito")


@app.route("/empleado/carrito/guardar", methods=["POST"])
@login_required(rol="empleado")
def carrito_guardar():
    cliente_id = get_cliente_filtro()
    tienda_id = session["tienda_id"]
    periodo_activo, _ = _resolve_periodo_seleccionado_empleado(cliente_id, tienda_id)
    if periodo_activo is None:
        flash("No puedes guardar inventario fuera de un período abierto.", "error")
        return _redirect_inventario_context("sec-carrito")

    carrito = get_carrito(periodo_activo.id)
    usuario = session["usuario"]
    cargas_periodo = empleado_service.listar_cargas_periodo(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        periodo_id=periodo_activo.id,
    )
    productos_cargados = empleado_service.combinar_cargas_para_vista(
        carrito=carrito,
        cargas_periodo=cargas_periodo,
        usuario=usuario,
    )
    productos = catalogo_get_productos_db(cliente_id=cliente_id, username=usuario)
    pendientes = empleado_service.obtener_productos_no_cargados(
        productos=productos,
        productos_cargados=productos_cargados,
    )
    if pendientes:
        flash(
            f"Quedan {len(pendientes)} producto(s) sin cargar. "
            "Revísalos o confirma todos en 0 antes de guardar.",
            "warning",
        )
        return redirect(url_for(
            "empleado_productos_no_cargados",
            periodo_id=periodo_activo.id,
            tab=pendientes[0]["categoria"],
        ))
    if not carrito:
        flash("No hay productos en el carrito para guardar.", "warning")
        return _redirect_inventario_context("sec-carrito")

    try:
        def limpiar_borrador(_guardados):
            set_carrito([], periodo_activo.id, commit=False)

        guardados = empleado_service.guardar_carrito_transaccional(
            carrito,
            tienda_id,
            usuario,
            cliente_id=cliente_id,
            periodo_id=periodo_activo.id,
            antes_commit=limpiar_borrador,
        )
    except empleado_service.ConflictoCarga as conflicto:
        db.session.rollback()
        categoria = next(
            (i.get("categoria") for i in carrito if i.get("producto") == conflicto.producto),
            CATEGORIAS[0],
        )
        session["conflicto_carga"] = {
            "accion": "guardar",
            "mensaje": f"Este producto ya fue cargado por {conflicto.usuario}. ¿Desea sobreescribir?",
            "usuario": conflicto.usuario,
            "cantidad_actual": conflicto.cantidad,
            "version": conflicto.version,
            "categoria": categoria,
            "producto": conflicto.producto,
        }
        session.modified = True
        return _redirect_inventario_context("sec-carrito")
    except IntegrityError:
        # Dos altas nuevas pueden superar la validación al mismo tiempo; la
        # restricción única decide cuál prevalece y la perdedora vuelve como conflicto.
        db.session.rollback()
        entrada = carrito[0]
        vigente = empleado_service.obtener_carga_actual(
            cliente_id=cliente_id,
            tienda_id=tienda_id,
            periodo_id=periodo_activo.id,
            categoria=entrada.get("categoria", CATEGORIAS[0]),
            producto=entrada.get("producto", ""),
        ) or {
            "usuario": "otro empleado",
            "cantidad": 0,
            "version": 0,
        }
        session["conflicto_carga"] = {
            "accion": "guardar",
            "mensaje": f"Este producto ya fue cargado por {vigente['usuario']}. ¿Desea sobreescribir?",
            "usuario": vigente["usuario"],
            "cantidad_actual": vigente["cantidad"],
            "version": vigente["version"],
            "categoria": entrada.get("categoria", CATEGORIAS[0]),
            "producto": entrada.get("producto", ""),
        }
        session.modified = True
        return _redirect_inventario_context("sec-carrito")
    except Exception:
        app.logger.exception("Fallo al guardar el inventario de %s", usuario)
        flash(
            "No se pudo guardar el inventario por un problema de conexión. "
            "El carrito se conserva sin cambios; puedes reintentar.",
            "error",
        )
        return _redirect_inventario_context("sec-carrito")

    flash(f"{guardados} producto(s) guardado(s) exitosamente.", "success")
    return _redirect_inventario_context("sec-carrito")


@app.route("/empleado/carrito/confirmar-faltantes-cero", methods=["POST"])
@login_required(rol="empleado")
def carrito_confirmar_faltantes_cero():
    cliente_id = get_cliente_filtro()
    tienda_id = session["tienda_id"]
    usuario = session["usuario"]
    periodo_activo, _ = _resolve_periodo_seleccionado_empleado(cliente_id, tienda_id)
    if periodo_activo is None:
        flash("No puedes confirmar productos fuera de un período abierto.", "error")
        return _redirect_inventario_context("sec-carrito")

    carrito = get_carrito(periodo_activo.id)
    cargas_periodo = empleado_service.listar_cargas_periodo(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        periodo_id=periodo_activo.id,
    )
    productos_cargados = empleado_service.combinar_cargas_para_vista(
        carrito=carrito,
        cargas_periodo=cargas_periodo,
        usuario=usuario,
    )
    productos = catalogo_get_productos_db(cliente_id=cliente_id, username=usuario)
    entradas_cero = empleado_service.construir_entradas_confirmacion_cero(
        productos=productos,
        productos_cargados=productos_cargados,
        fecha=today_local_iso(),
    )
    if not entradas_cero:
        flash("Ya no quedan productos pendientes. Revisa el inventario antes de guardar.", "info")
        return _redirect_inventario_context("sec-carrito")

    try:
        def limpiar_borrador(_guardados):
            set_carrito([], periodo_activo.id, commit=False)

        guardados = empleado_service.guardar_carrito_transaccional(
            carrito + entradas_cero,
            tienda_id,
            usuario,
            cliente_id=cliente_id,
            periodo_id=periodo_activo.id,
            antes_commit=limpiar_borrador,
        )
    except (empleado_service.ConflictoCarga, IntegrityError):
        db.session.rollback()
        flash(
            "Las cargas cambiaron mientras confirmabas. No se guardó ningún cambio; "
            "revisa nuevamente los productos pendientes.",
            "warning",
        )
        return redirect(url_for(
            "empleado_productos_no_cargados",
            periodo_id=periodo_activo.id,
        ))
    except Exception:
        app.logger.exception("Fallo al confirmar faltantes en cero de %s", usuario)
        flash(
            "No se pudo guardar la confirmación. El carrito se conserva sin cambios; "
            "puedes reintentar.",
            "error",
        )
        return redirect(url_for(
            "empleado_productos_no_cargados",
            periodo_id=periodo_activo.id,
        ))

    flash(
        f"Inventario guardado: {len(entradas_cero)} faltante(s) confirmado(s) sin stock "
        f"y {guardados - len(entradas_cero)} carga(s) manual(es).",
        "success",
    )
    return _redirect_inventario_context("sec-carrito")


@app.route("/empleado/carrito/confirmar-conflicto", methods=["POST"])
@login_required(rol="empleado")
def carrito_confirmar_conflicto():
    cliente_id = get_cliente_filtro()
    tienda_id = session["tienda_id"]
    periodo_activo, _ = _resolve_periodo_seleccionado_empleado(cliente_id, tienda_id)
    if periodo_activo is None:
        flash("El período ya no está abierto.", "warning")
        return _redirect_inventario_context("sec-carrito")

    categoria = request.form.get("categoria", CATEGORIAS[0])
    producto = (request.form.get("producto") or "").strip()
    actual = empleado_service.obtener_carga_actual(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        periodo_id=periodo_activo.id,
        categoria=categoria,
        producto=producto,
        excluir_usuario=session["usuario"],
    )
    if not actual:
        flash("La carga en conflicto ya no existe. Revisa el carrito antes de guardar.", "warning")
        return _redirect_inventario_context("sec-carrito")

    carrito = get_carrito(periodo_activo.id)
    if actual.get("origen") == "borrador":
        retirado = empleado_service.retirar_producto_de_otros_borradores(
            cliente_id=cliente_id,
            tienda_id=tienda_id,
            periodo_id=periodo_activo.id,
            usuario=session["usuario"],
            categoria=categoria,
            producto=producto,
            version_esperada=actual["version"],
        )
        if not retirado:
            flash("La carga cambió mientras confirmabas. Intenta nuevamente.", "warning")
            return _redirect_inventario_context("sec-carrito")
        carga_base = empleado_service.obtener_carga_actual(
            cliente_id=cliente_id,
            tienda_id=tienda_id,
            periodo_id=periodo_activo.id,
            categoria=categoria,
            producto=producto,
            excluir_usuario=session["usuario"],
        )
        version_confirmada = carga_base["version"] if carga_base else 0
        confirmar_sobreescritura = bool(
            carga_base and carga_base["usuario"] != session["usuario"]
        )
    else:
        version_confirmada = actual["version"]
        confirmar_sobreescritura = True
    encontrados = 0
    for item in carrito:
        if item.get("categoria") == categoria and item.get("producto") == producto:
            item["version_esperada"] = version_confirmada
            item["confirmar_sobreescritura"] = confirmar_sobreescritura
            encontrados += 1
    if encontrados:
        set_carrito(carrito, periodo_activo.id)
        flash(f"Sobreescritura de {producto} confirmada. Ya puedes guardar el inventario.", "info")
    else:
        flash("El producto en conflicto ya no está en el carrito.", "warning")
    return _redirect_inventario_context("sec-carrito")


# --------------------------------------------------------------------------- #
#  Helper: conversión de UME a unidades individuales
# --------------------------------------------------------------------------- #
def _convertir_ume(producto: str, ume: str, cantidad: float):
    """Retorna (cantidad_unidades, desc_conversion)."""
    if ume not in ("Caja", "Bulto", "Tira"):
        return cantidad, ""
    pp = ProductoPrecio.query.filter(
        db.func.lower(ProductoPrecio.producto_nombre) == producto.strip().lower()
    ).first()
    if not pp:
        return cantidad, ""
    u_caja  = float(pp.unidades_por_caja  or 0)
    u_bulto = float(pp.unidades_por_bulto or 0)
    if ume == "Caja" and u_caja > 0:
        cu = cantidad * u_caja
        return cu, f"{cantidad:g} Caja × {u_caja:g} unid/caja = {cu:g} unid."
    if ume in ("Bulto", "Tira") and u_bulto > 0 and u_caja > 0:
        cu = cantidad * u_bulto * u_caja
        return cu, (f"{cantidad:g} {ume} × {u_bulto:g} cajas/{ume.lower()} "
                    f"× {u_caja:g} unid/caja = {cu:g} unid.")
    return cantidad, ""


# --------------------------------------------------------------------------- #
#  Empleado - Averiados
# --------------------------------------------------------------------------- #
@app.route("/empleado/averiado", methods=["GET", "POST"])
@login_required(rol="empleado")
def empleado_averiado():
    cliente_id = get_cliente_filtro()
    tienda_id = session["tienda_id"]
    usuario   = session["usuario"]
    periodo_post_id = request.form.get("periodo_id", type=int) if request.method == "POST" else None
    periodo_activo, periodos_abiertos = _resolve_periodo_seleccionado_empleado(
        cliente_id, tienda_id,
    )
    context = empleado_service.build_averiado_context(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        periodo_id=periodo_activo.id if periodo_activo else None,
    )
    context.update(
        periodo_activo=periodo_activo,
        periodos_abiertos=periodos_abiertos,
        fecha_averiado=(
            min(max(today_local_iso(), periodo_activo.fecha_desde), periodo_activo.fecha_hasta)
            if periodo_activo else today_local_iso()
        ),
    )

    if request.method == "POST":
        categoria = request.form.get("categoria", "")
        producto  = (request.form.get("producto") or "").strip()
        cantidad_raw = (request.form.get("cantidad") or "").strip()
        cantidad_es_invalida = False
        error_cantidad = ""
        try:
            cantidad, ume_categoria = empleado_service.normalizar_cantidad_categoria(
                categoria, cantidad_raw
            )
        except ValueError as exc:
            cantidad = 0
            cantidad_es_invalida = True
            error_cantidad = str(exc)
            ume_categoria = "Unidad"
        ume = "kg" if categoria == "Por Kilos" else request.form.get("ume", ume_categoria)
        detalle   = (request.form.get("detalle") or "").strip()
        fecha     = request.form.get("fecha", today_local_iso())

        if (
            periodo_post_id is None
            or periodo_activo is None
            or periodo_activo.id != periodo_post_id
        ):
            flash("No hay un período contable abierto para registrar el averiado.", "warning")
        elif not producto:
            flash("Selecciona un producto.", "warning")
        elif producto_disponible_usuario(
            cliente_id, usuario, producto, categoria
        ) is None:
            flash(
                "Ese producto todavía no fue recibido en tu catálogo. "
                "Usa Enviar y recibir antes de registrarlo.",
                "warning",
            )
        elif cantidad_es_invalida:
            flash(error_cantidad or "Ingresa una cantidad válida.", "warning")
        elif cantidad <= 0:
            flash("Ingresa una cantidad válida.", "warning")
        else:
            try:
                cu, desc = empleado_service.registrar_averiado(
                    tienda_id=tienda_id, usuario=usuario,
                    categoria=categoria, producto=producto,
                    cantidad=cantidad, ume=ume,
                    detalle=detalle, fecha=fecha,
                    periodo_id=periodo_post_id,
                )
            except ValueError as exc:
                flash(str(exc), "warning")
                return render_template("empleado_averiado.html", **context)
            db.session.commit()
            nombre_d = _re.sub(r"\s+x\s+un(?:idad|\.?)\s*$", "", producto, flags=_re.IGNORECASE)
            msg = f"Averiado registrado: {nombre_d} — {cantidad:g} {ume}"
            if desc:
                msg += f" → {desc}"
            msg += " (pendiente de sincronización)"
            flash(msg, "success")
            return redirect(url_for("empleado_averiado", periodo_id=periodo_activo.id))

    return render_template("empleado_averiado.html", **context)


@app.route("/empleado/averiado/<int:reg_id>/eliminar", methods=["POST"])
@login_required(rol="empleado")
def averiado_eliminar(reg_id):
    reg = db.session.get(RegistroAveriado, reg_id)
    if (
        reg
        and reg.cliente_id == get_cliente_filtro()
        and reg.tienda_id == session["tienda_id"]
        and reg.usuario == session["usuario"]
        and reg.sinc_estado == "pendiente"
    ):
        periodo_id = reg.periodo_id
        db.session.delete(reg)
        db.session.commit()
        flash("Registro eliminado.", "info")
        return redirect(url_for("empleado_averiado", periodo_id=periodo_id))
    flash("Solo puedes eliminar tus averiados pendientes de sincronización.", "warning")
    return redirect(url_for("empleado_averiado"))


# --------------------------------------------------------------------------- #
#  Empleado - Stock próximo a vencer
# --------------------------------------------------------------------------- #
@app.route("/empleado/vencimiento", methods=["GET", "POST"])
@login_required(rol="empleado")
def empleado_vencimiento():
    cliente_id = get_cliente_filtro()
    tienda_id = session["tienda_id"]
    usuario   = session["usuario"]
    context = empleado_service.build_vencimiento_context(tienda_id=tienda_id)

    if request.method == "POST":
        categoria        = request.form.get("categoria", "")
        producto         = (request.form.get("producto") or "").strip()
        cantidad_raw     = (request.form.get("cantidad") or "").strip()
        cantidad_es_invalida = False
        error_cantidad = ""
        try:
            cantidad, ume_categoria = empleado_service.normalizar_cantidad_categoria(
                categoria, cantidad_raw
            )
        except ValueError as exc:
            cantidad = 0
            cantidad_es_invalida = True
            error_cantidad = str(exc)
            ume_categoria = "Unidad"
        ume = "kg" if categoria == "Por Kilos" else request.form.get("ume", ume_categoria)
        fecha_venc       = (request.form.get("fecha_vencimiento") or "").strip()
        detalle          = (request.form.get("detalle") or "").strip()
        fecha            = request.form.get("fecha", today_local_iso())

        if not producto:
            flash("Selecciona un producto.", "warning")
        elif producto_disponible_usuario(
            cliente_id, usuario, producto, categoria
        ) is None:
            flash(
                "Ese producto todavía no fue recibido en tu catálogo. "
                "Usa Enviar y recibir antes de registrarlo.",
                "warning",
            )
        elif cantidad_es_invalida:
            flash(error_cantidad or "Ingresa una cantidad válida.", "warning")
        elif cantidad <= 0:
            flash("Ingresa una cantidad válida.", "warning")
        elif not fecha_venc:
            flash("Ingresa la fecha de vencimiento.", "warning")
        else:
            cu, desc = empleado_service.registrar_vencimiento(
                tienda_id=tienda_id, usuario=usuario,
                categoria=categoria, producto=producto,
                cantidad=cantidad, ume=ume,
                fecha_vencimiento=fecha_venc, detalle=detalle,
                fecha=fecha,
            )
            db.session.commit()
            nombre_d = _re.sub(r"\s+x\s+un(?:idad|\.?)\s*$", "", producto, flags=_re.IGNORECASE)
            flash(f"Vencimiento registrado: {nombre_d} — vence {fecha_venc} (pendiente de sincronización)", "success")
            return redirect(url_for("empleado_vencimiento"))

    return render_template("empleado_vencimiento.html", **context)


@app.route("/empleado/vencimiento/<int:reg_id>/eliminar", methods=["POST"])
@login_required(rol="empleado")
def vencimiento_eliminar(reg_id):
    reg = db.session.get(RegistroVencimiento, reg_id)
    if reg and reg.tienda_id == session["tienda_id"]:
        db.session.delete(reg)
        db.session.commit()
        flash("Registro eliminado.", "info")
    return redirect(url_for("empleado_vencimiento"))


# --------------------------------------------------------------------------- #
#  Empleado - Página de Sincronización
# --------------------------------------------------------------------------- #
@app.route("/empleado/sincronizar-page")
@login_required(rol="empleado")
def empleado_sincronizar_page():
    cliente_id = get_cliente_filtro()
    tienda_id = session["tienda_id"]
    periodo_activo, _ = _resolve_periodo_seleccionado_empleado(cliente_id, tienda_id)
    return render_template(
        "empleado_sincronizar.html",
        **empleado_service.build_sincronizacion_context(
            cliente_id=cliente_id,
            tienda_id=tienda_id,
            periodo_id=periodo_activo.id if periodo_activo else None,
        ),
        periodo_activo=periodo_activo,
    )


def sync_ultimo_envio_empleado():
    return empleado_service.sync_ultimo_envio_empleado()


def sync_ultima_recepcion_empleado():
    return empleado_service.sync_ultima_recepcion_empleado()


# --------------------------------------------------------------------------- #
#  Empleado - Sincronizar (POST)
# --------------------------------------------------------------------------- #
@app.route("/empleado/sincronizar", methods=["POST"])
@login_required(rol="empleado")
def empleado_sincronizar():
    accion    = request.form.get("accion", "solo_enviar")
    if accion not in ("solo_enviar", "enviar_recibir"):
        accion = "solo_enviar"
    cliente_id = get_cliente_filtro()
    tienda_id = session["tienda_id"]
    usuario   = session["usuario"]

    # El período viaja dentro del formulario y prevalece sobre la sesión.
    periodo_activo, _ = _resolve_periodo_seleccionado_empleado(cliente_id, tienda_id)

    # 1. Comprobar las tres fuentes; ninguna debe quedar fuera del envío.
    pend_inv = empleado_service._pendientes_inventario_usuario(
        cliente_id,
        tienda_id,
        usuario,
        periodo_id=periodo_activo.id if periodo_activo else None,
    ).count()
    pend_aver = RegistroAveriado.query.filter_by(
        cliente_id=cliente_id, tienda_id=tienda_id, usuario=usuario, sinc_estado="pendiente"
    ).count()
    pend_venc = RegistroVencimiento.query.filter_by(
        cliente_id=cliente_id, tienda_id=tienda_id, usuario=usuario, sinc_estado="pendiente"
    ).count()
    pendientes = pend_inv + pend_aver + pend_venc
    catalogo_pendiente, _ = catalogo_pendiente_usuario(cliente_id, usuario)
    recibe_catalogo = accion == "enviar_recibir" and catalogo_pendiente
    if pendientes == 0 and not recibe_catalogo:
        flash("No hay datos pendientes de sincronización.", "warning")
        return redirect(url_for("empleado_sincronizar_page"))

    # 2. ¿El período activo (seleccionado por empleado) está disponible?
    if periodo_activo is None:
        # No hay período abierto — la sincronización de inventario operativo sigue funcionando
        # pero el empleado debe saberlo
        flash("No hay un período de auditoría activo. Los datos se sincronizan normalmente pero no se registrarán en ningún período de inventario.", "info")

    # Propagar y sincronizar en una sola transacción. Si algo falla, ningún
    # registro cambia de estado y queda disponible para reintentar.
    try:
        def notificar_carga(resumen_sync):
            if periodo_activo is not None and resumen_sync["n_inv"] > 0:
                _notificar_admins_periodo_cargado(
                    periodo_activo,
                    usuario,
                    resumen_sync["n_inv"],
                )

        resumen = sincronizar_transaccional(
            cliente_id=cliente_id,
            tienda_id=tienda_id,
            usuario=usuario,
            accion=accion,
            periodo=periodo_activo,
            antes_commit=notificar_carga,
        )
    except Exception:
        app.logger.exception("Fallo la sincronización del empleado %s", usuario)
        flash("No se pudo completar la sincronización. Ningún dato fue marcado como enviado; puedes reintentar.", "error")
        return redirect(url_for("empleado_sincronizar_page"))

    if accion == "enviar_recibir":
        flash((
            f"Sincronización completada: {resumen['n_total']} registro(s) enviado(s) "
            f"(Inventario: {resumen['n_inv']}, Averiados: {resumen['n_aver']}, Vencimientos: {resumen['n_venc']}) "
            "y catálogo consultado. Los productos nuevos se publican desde Documentación Oficial."
        ), "success")
    else:
        flash(
            f"Datos enviados: {resumen['n_total']} registro(s) (Inventario: {resumen['n_inv']}, Averiados: {resumen['n_aver']}, Vencimientos: {resumen['n_venc']}).",
            "success",
        )
    return redirect(url_for("empleado_sincronizar_page"))


@app.route("/empleado/historial")
@login_required(rol="empleado")
def empleado_historial():
    tienda_id = session["tienda_id"]
    usuario = session["usuario"]
    context = empleado_service.build_historial_context(tienda_id=tienda_id, usuario=usuario)
    selected_fecha = request.args.get("fecha")
    if selected_fecha and context["snapshots"]:
        selected_snapshot = next((s for s in context["snapshots"] if s.fecha == selected_fecha), None)
        if selected_snapshot is not None:
            context["selected_snapshot"] = selected_snapshot
            context["detalle"] = HistorialMovimiento.query.filter_by(
                tienda_id=tienda_id, usuario=usuario, fecha=selected_snapshot.fecha
            ).order_by(HistorialMovimiento.categoria, HistorialMovimiento.producto).all()

    return render_template("empleado_historial.html", **context)


# --------------------------------------------------------------------------- #
#  Empleado - Delivery
# --------------------------------------------------------------------------- #
@app.route("/empleado/delivery", methods=["GET", "POST"])
@login_required(rol="empleado")
def empleado_delivery():
    if request.method == "POST":
        producto_id = request.form.get("producto_id", type=int)
        cantidad = request.form.get("cantidad", type=int) or 1
        fecha = request.form.get("fecha", today_local_iso())
        if producto_id is None:
            flash("Selecciona un producto antes de registrar la venta.", "warning")
            return redirect(url_for("empleado_delivery"))
        resultado = empleado_service.registrar_venta_delivery(
            tienda_id=session["tienda_id"],
            usuario=session["usuario"],
            producto_id=producto_id,
            cantidad=cantidad,
            fecha=fecha,
        )
        if resultado:
            nombre_producto, total = resultado
            db.session.commit()
            flash(f"Venta registrada: {cantidad}x {nombre_producto} = ${total:g}", "success")
        return redirect(url_for("empleado_delivery"))

    return render_template(
        "empleado_delivery.html",
        **empleado_service.build_delivery_context(tienda_id=session["tienda_id"]),
    )


def _dias_hasta(fecha_iso):
    """Dias desde hoy hasta una fecha ISO (None si es invalida)."""
    try:
        return (date.fromisoformat(str(fecha_iso)[:10]) - date.today()).days
    except (ValueError, TypeError):
        return None


_MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _fecha_es(d):
    """Fecha en formato '27 de julio de 2026'."""
    return f"{d.day} de {_MESES_ES[d.month - 1]} de {d.year}"


def _hace_texto(dt):
    """'Hace 2 horas' / 'Ayer' / 'Hace 3 dias' a partir de un datetime UTC."""
    if not dt:
        return ""
    delta = utc_now() - dt
    if delta.days == 0:
        horas = delta.seconds // 3600
        if horas == 0:
            minutos = max(1, delta.seconds // 60)
            return f"Hace {minutos} min"
        return f"Hace {horas} hora{'s' if horas != 1 else ''}"
    if delta.days == 1:
        return "Ayer"
    return f"Hace {delta.days} dias"


# --------------------------------------------------------------------------- #
#  Admin - Dashboard (Resumen)
# --------------------------------------------------------------------------- #
@app.route("/admin/")
@app.route("/admin/dashboard")
@login_required(rol="administrador")
def admin_dashboard():
    cliente_id = get_cliente_filtro()
    tiendas = Tienda.query.filter_by(cliente_id=cliente_id, activa=True).all()
    tienda_sel = get_tienda_filtro()

    items = _items_sincronizados(tienda_sel)
    precios = _precios_lookup()
    hay_precios = len(precios) > 0

    # --- KPIs ---
    categorias_activas = {c for (c,) in db.session.query(Producto.categoria).distinct().all()}
    total_categorias = len(categorias_activas)
    total_productos = Producto.query.count()
    total_unidades = sum(i.cantidad or 0 for i in items)

    valor_total = 0.0
    for i in items:
        pp = precios.get(i.producto.strip().lower())
        if pp and pp.precio:
            valor_total += (i.cantidad or 0) * pp.precio

    # --- Inventario por categoria (dona) ---
    por_categoria = {}
    for i in items:
        por_categoria[i.categoria] = por_categoria.get(i.categoria, 0) + (i.cantidad or 0)
    inventario_categoria = [
        {"categoria": c, "unidades": round(u, 2),
         "porcentaje": round(u / total_unidades * 100, 1) if total_unidades else 0}
        for c, u in sorted(por_categoria.items(), key=lambda x: -x[1]) if u > 0
    ]

    # --- Producto con mayor stock por categoria ---
    top_por_categoria = []
    for cat in CATEGORIAS:
        cat_items = [i for i in items if i.categoria == cat and (i.cantidad or 0) > 0]
        if not cat_items:
            continue
        top = max(cat_items, key=lambda i: i.cantidad or 0)
        top_por_categoria.append({"categoria": cat, "producto": top.producto,
                                  "cantidad": top.cantidad, "ume": top.ume})

    # --- Valor por categoria + Top 5 por valor (solo con precios) ---
    valor_categoria = {}
    valores_producto = []
    if hay_precios:
        for i in items:
            pp = precios.get(i.producto.strip().lower())
            if pp and pp.precio and (i.cantidad or 0) > 0:
                v = (i.cantidad or 0) * pp.precio
                valor_categoria[i.categoria] = valor_categoria.get(i.categoria, 0) + v
                valores_producto.append({"producto": i.producto, "categoria": i.categoria,
                                         "valor": v})
    valor_por_categoria = [
        {"categoria": c, "valor": round(v, 2),
         "porcentaje": round(v / valor_total * 100, 1) if valor_total else 0}
        for c, v in sorted(valor_categoria.items(), key=lambda x: -x[1])
    ]
    top_valor = sorted(valores_producto, key=lambda x: -x["valor"])[:5]

    # --- Productos proximos a vencer (30 dias) ---
    q_venc = RegistroVencimiento.query.filter_by(cliente_id=cliente_id, sinc_estado="sincronizado")
    if tienda_sel != "ALL":
        q_venc = q_venc.filter_by(tienda_id=tienda_sel)
    tiendas_map = {t.id: t.nombre for t in Tienda.query.all()}
    proximos_vencer = []
    for r in q_venc.all():
        dias = _dias_hasta(r.fecha_vencimiento)
        if dias is not None and 0 <= dias <= 30:
            proximos_vencer.append({
                "producto": r.producto, "categoria": r.categoria,
                "tienda": tiendas_map.get(r.tienda_id, r.tienda_id),
                "dias": dias,
                "nivel": "danger" if dias < 7 else ("warning" if dias < 15 else "success"),
            })
    proximos_vencer.sort(key=lambda x: x["dias"])

    # --- Actividad reciente ---
    q_hist = HistorialMovimiento.query.filter_by(cliente_id=cliente_id)
    if tienda_sel != "ALL":
        q_hist = q_hist.filter_by(tienda_id=tienda_sel)
    actividad = [
        {"producto": m.producto, "categoria": m.categoria,
         "tienda": tiendas_map.get(m.tienda_id, m.tienda_id),
         "usuario": m.usuario, "cantidad": m.cantidad, "modo": m.modo,
         "hace": _hace_texto(m.creado)}
        for m in q_hist.order_by(HistorialMovimiento.creado.desc()).limit(10).all()
    ]

    # --- Alertas de stock bajo (para tarjeta lateral) ---
    thresholds = get_thresholds()
    stock_bajo = 0
    for i in items:
        nivel, _ = stock_status(i.producto, i.cantidad or 0, thresholds)
        if nivel == "critico":
            stock_bajo += 1

    return render_template(
        "admin_dashboard.html",
        tiendas=tiendas, tienda_sel=tienda_sel,
        total_categorias=total_categorias, total_productos=total_productos,
        total_unidades=total_unidades, valor_total=valor_total,
        hay_precios=hay_precios,
        inventario_categoria=inventario_categoria,
        top_por_categoria=top_por_categoria,
        valor_por_categoria=valor_por_categoria,
        top_valor=top_valor,
        proximos_vencer=proximos_vencer[:8],
        actividad=actividad,
        stock_bajo=stock_bajo,
        hoy=_fecha_es(date.today()),
    )


# --------------------------------------------------------------------------- #
#  Admin - Precios (seccion explicita)
# --------------------------------------------------------------------------- #
@app.route("/admin/precios", methods=["GET", "POST"])
@login_required(rol="administrador")
def admin_precios():
    active_tab = _safe_catalog_tab(request.args.get("tab"))
    if request.method == "POST":
        active_tab = _safe_catalog_tab(request.form.get("active_tab"))
        ids = request.form.getlist("ids")
        hubo_cambios = False
        for pid in ids:
            try:
                pid_int = int(pid)
            except ValueError:
                continue
            producto = db.session.get(Producto, pid_int)
            if producto is None:
                continue
            precio_val = request.form.get(f"precio_{pid}") or None
            precio_caja_val = request.form.get(f"precio_caja_{pid}") or None
            caja_val = request.form.get(f"caja_{pid}") or None
            bulto_val = request.form.get(f"bulto_{pid}") or None
            try:
                precio_val = float(str(precio_val).replace(".", "").replace(",", ".")) if precio_val else None
                precio_caja_val = float(str(precio_caja_val).replace(".", "").replace(",", ".")) if precio_caja_val else None
                caja_val = float(caja_val) if caja_val else None
                bulto_val = float(bulto_val) if bulto_val else None
            except ValueError:
                continue
            rec = ProductoPrecio.query.filter_by(producto_nombre=producto.nombre).first()
            if rec is None:
                rec = ProductoPrecio(producto_nombre=producto.nombre, categoria=producto.categoria,
                                     producto_id=producto.id)
                db.session.add(rec)
            elif rec.producto_id is None:
                rec.producto_id = producto.id
            anterior = (
                rec.precio, rec.precio_por_caja, rec.unidades_por_caja,
                rec.unidades_por_bulto,
            )
            rec.precio = precio_val
            if producto.categoria in ("Impulsivo", "Fanee", "Extras"):
                rec.precio_por_caja = precio_caja_val
                rec.unidades_por_caja = caja_val
                rec.unidades_por_bulto = bulto_val
            hubo_cambios = hubo_cambios or anterior != (
                rec.precio, rec.precio_por_caja, rec.unidades_por_caja,
                rec.unidades_por_bulto,
            )
        if hubo_cambios:
            marcar_cambio_catalogo(
                get_cliente_filtro(), "Precios o conversiones del catálogo actualizados",
            )
        db.session.commit()
        _set_admin_precios_notice("Precios actualizados correctamente.", "success", active_tab)
        return redirect(url_for("admin_precios", tab=active_tab) + "#precios-tabs")

    local_notice = pop_view_notice(session, "admin_precios_notice")
    if local_notice and local_notice.get("tab"):
        active_tab = local_notice["tab"]

    productos_por_cat = {
        c: Producto.query.filter_by(categoria=c).order_by(Producto.nombre).all()
        for c in CATEGORIAS
    }
    precios_map = {p.producto_nombre: p for p in ProductoPrecio.query.all()}

    return render_template("admin_precios.html",
                           productos_por_cat=productos_por_cat,
                           categorias=CATEGORIAS,
                           precios_map=precios_map,
                           active_tab=active_tab,
                           local_notice=local_notice,
                           hide_global_flash=True)


# --------------------------------------------------------------------------- #
#  Admin - Usuarios
# --------------------------------------------------------------------------- #
@app.route("/admin/usuarios")
@login_required(rol="administrador")
def admin_usuarios():
    cliente_id = get_cliente_filtro()
    usuarios = Usuario.query.filter_by(cliente_id=cliente_id).order_by(Usuario.rol, Usuario.username).all()
    tiendas = Tienda.query.filter_by(cliente_id=cliente_id, activa=True).all()
    tiendas_map = {t.id: t.nombre for t in Tienda.query.filter_by(cliente_id=cliente_id).all()}
    local_notice = pop_view_notice(session, "admin_usuarios_notice")
    return render_template("admin_usuarios.html", usuarios=usuarios,
                           tiendas=tiendas, tiendas_map=tiendas_map,
                           local_notice=local_notice,
                           hide_global_flash=True)


@app.route("/admin/usuarios/crear", methods=["POST"])
@login_required(rol="administrador")
def usuario_crear():
    cliente_id = get_cliente_filtro()
    username = (request.form.get("username") or "").strip()
    contrasena = request.form.get("contrasena") or ""
    rol = (request.form.get("rol") or "empleado").strip()
    tienda_id = (request.form.get("tienda_id") or "").strip()

    if not username:
        set_view_notice(session, "admin_usuarios_notice", "El nombre de usuario es obligatorio.", "error")
        return redirect(url_for("admin_usuarios") + "#usuarios-crear")
    if len(contrasena) < 6:
        set_view_notice(session, "admin_usuarios_notice", "La contrasena debe tener al menos 6 caracteres.", "error")
        return redirect(url_for("admin_usuarios") + "#usuarios-crear")
    if rol not in ("empleado", "administrador"):
        set_view_notice(session, "admin_usuarios_notice", "Rol no valido.", "error")
        return redirect(url_for("admin_usuarios") + "#usuarios-crear")
    if Usuario.query.filter_by(username=username, cliente_id=cliente_id).first():
        set_view_notice(session, "admin_usuarios_notice", f"Ya existe el usuario '{username}'.", "warning")
        return redirect(url_for("admin_usuarios") + "#usuarios-crear")

    if rol == "administrador":
        tienda_id = "ALL"
    elif not tienda_id:
        set_view_notice(session, "admin_usuarios_notice", "Selecciona una tienda para el empleado.", "error")
        return redirect(url_for("admin_usuarios") + "#usuarios-crear")

    db.session.add(Usuario(
        username=username,
        password_hash=generate_password_hash(contrasena),
        cliente_id=cliente_id,
        rol=rol,
        tienda_id=tienda_id,
    ))
    db.session.commit()
    set_view_notice(session, "admin_usuarios_notice", f"Usuario '{username}' creado correctamente.", "success")
    return redirect(url_for("admin_usuarios") + "#usuarios-list")


@app.route("/admin/usuarios/<int:usuario_id>/eliminar", methods=["POST"])
@login_required(rol="administrador")
def usuario_eliminar(usuario_id):
    cliente_id = get_cliente_filtro()
    usuario = db.session.get(Usuario, usuario_id)
    if usuario is None:
        abort(404)
    if usuario.cliente_id != cliente_id:
        abort(403)
    if usuario.username == session.get("usuario"):
        set_view_notice(session, "admin_usuarios_notice", "No puedes eliminar tu propio usuario activo.", "error")
        return redirect(url_for("admin_usuarios") + "#usuarios-list")
    db.session.delete(usuario)
    db.session.commit()
    set_view_notice(session, "admin_usuarios_notice", f"Usuario '{usuario.username}' eliminado.", "info")
    return redirect(url_for("admin_usuarios") + "#usuarios-list")


@app.route("/admin/usuarios/<int:usuario_id>/editar", methods=["POST"])
@login_required(rol="administrador")
def usuario_editar(usuario_id):
    cliente_id = get_cliente_filtro()
    usuario = db.session.get(Usuario, usuario_id)
    if usuario is None:
        abort(404)
    if usuario.cliente_id != cliente_id:
        abort(403)

    username = (request.form.get("username") or "").strip()
    rol = (request.form.get("rol") or "empleado").strip()
    tienda_id = (request.form.get("tienda_id") or "").strip()
    nueva_contrasena = request.form.get("contrasena") or ""

    if not username:
        set_view_notice(session, "admin_usuarios_notice", "El nombre de usuario es obligatorio.", "error")
        return redirect(url_for("admin_usuarios") + "#usuarios-list")

    if rol not in ("empleado", "administrador"):
        set_view_notice(session, "admin_usuarios_notice", "Rol no valido.", "error")
        return redirect(url_for("admin_usuarios") + "#usuarios-list")

    if rol == "administrador":
        tienda_id = "ALL"
    elif not tienda_id:
        set_view_notice(session, "admin_usuarios_notice", "Selecciona una tienda para el empleado.", "error")
        return redirect(url_for("admin_usuarios") + "#usuarios-list")

    if nueva_contrasena and len(nueva_contrasena) < 6:
        set_view_notice(session, "admin_usuarios_notice", "La contrasena debe tener al menos 6 caracteres.", "error")
        return redirect(url_for("admin_usuarios") + "#usuarios-list")

    existente = Usuario.query.filter_by(cliente_id=cliente_id, username=username).filter(Usuario.id != usuario.id).first()
    if existente:
        set_view_notice(session, "admin_usuarios_notice", f"Ya existe el usuario '{username}'.", "warning")
        return redirect(url_for("admin_usuarios") + "#usuarios-list")

    if usuario.username == session.get("usuario") and rol != "administrador":
        set_view_notice(session, "admin_usuarios_notice", "No puedes quitar privilegios de administrador a tu usuario activo.", "error")
        return redirect(url_for("admin_usuarios") + "#usuarios-list")

    usuario.username = username
    usuario.rol = rol
    usuario.tienda_id = tienda_id
    if nueva_contrasena:
        usuario.password_hash = generate_password_hash(nueva_contrasena)

    db.session.commit()
    set_view_notice(session, "admin_usuarios_notice", f"Usuario '{usuario.username}' actualizado correctamente.", "success")
    return redirect(url_for("admin_usuarios") + "#usuarios-list")


# --------------------------------------------------------------------------- #
#  Admin - Alertas centralizadas
# --------------------------------------------------------------------------- #
@app.route("/admin/alertas")
@login_required(rol="administrador")
def admin_alertas():
    cliente_id = get_cliente_filtro()
    tienda_sel = get_tienda_filtro()
    username_actual = str(session.get("usuario") or "")
    alertas = _construir_alertas_admin(
        cliente_id, username_actual, tienda_sel,
    )
    resumen = {}
    for alerta in alertas:
        resumen[alerta["tipo"]] = resumen.get(alerta["tipo"], 0) + 1
    return render_template("admin_alertas.html", alertas=alertas, resumen_alertas=resumen)


def _tipos_alerta_leidos(cliente_id: str, username: str) -> set[tuple[str, int]]:
    filas = NotificacionUsuario.query.filter(
        NotificacionUsuario.cliente_id == cliente_id,
        NotificacionUsuario.username == username,
        NotificacionUsuario.leida.is_(True),
        NotificacionUsuario.tipo.like("alerta_%"),
    ).with_entities(NotificacionUsuario.tipo, NotificacionUsuario.referencia_id).all()
    return {(tipo, int(ref or 0)) for tipo, ref in filas}


def _resolver_notificaciones_de_carga(cliente_id: str, username: str) -> list:
    """Retira cargas pendientes cuando el período ya fue auditado o ya no existe."""
    cargas = (
        NotificacionUsuario.query
        .filter_by(cliente_id=cliente_id, username=username, tipo="periodo_cargado", leida=False)
        .order_by(NotificacionUsuario.id.desc()).limit(80).all()
    )
    activas = []
    hubo_cambios = False
    for notificacion in cargas:
        periodo = (
            db.session.get(InventarioPeriodo, notificacion.referencia_id)
            if notificacion.referencia_id else None
        )
        resuelta = periodo is None
        if periodo is not None:
            estado = estado_actualizacion_auditoria(periodo)
            resuelta = estado["ejecutada"] and not estado["desactualizada"]
        if resuelta:
            notificacion.leida = True
            hubo_cambios = True
        else:
            activas.append(notificacion)
    if hubo_cambios:
        db.session.commit()
    return activas


def _construir_alertas_admin(cliente_id: str, username: str, tienda_sel: str) -> list[dict]:
    """Unifica notificaciones persistentes y condiciones operativas activas."""
    cache_key = (cliente_id, username, tienda_sel)
    if getattr(g, "_alertas_admin_key", None) == cache_key:
        return g._alertas_admin
    tiendas_map = {
        t.id: t.nombre for t in Tienda.query.filter_by(cliente_id=cliente_id).all()
    }
    leidas = _tipos_alerta_leidos(cliente_id, username)
    alertas = []

    from core.inventario import estado_sincronizacion_catalogo
    estado_catalogo = estado_sincronizacion_catalogo(cliente_id, detallado=True)
    ultima_edicion_excel = db.session.query(db.func.max(ExcelDetalleEdicion.id)).filter_by(
        cliente_id=cliente_id,
    ).scalar() or 0
    version_catalogo = db.session.query(db.func.max(Producto.catalogo_version)).scalar() or 0
    tipo_catalogo = (
        f"alerta_catalogo_{int(version_catalogo)}_{int(ultima_edicion_excel)}_"
        f"{int(estado_catalogo['total'])}"
    )[:40]
    if estado_catalogo["total"] and (tipo_catalogo, 0) not in leidas:
        alertas.append({
            "tipo": "catalogo", "tono": "danger", "icono": "↻",
            "titulo": "Catálogo pendiente de revisar y sincronizar",
            "detalle": (
                f"{estado_catalogo['total']} cambio(s) aplicable(s): productos nuevos, "
                "renombres o vínculos del Excel."
            ),
            "meta": "Documentación oficial",
            "destino": url_for("admin_alerta_ir", tipo="catalogo", referencia_id=0),
            "orden": datetime.now(),
        })

    cargas = _resolver_notificaciones_de_carga(cliente_id, username)
    for n in cargas:
        alertas.append({
            "tipo": "carga", "tono": "success", "icono": "✓",
            "titulo": n.titulo, "detalle": n.mensaje,
            "meta": n.creada.strftime("%d/%m/%Y %H:%M") if n.creada else "",
            "destino": url_for("admin_notificacion_ir", notif_id=n.id),
            "orden": n.creada or datetime(1970, 1, 1),
        })

    thresholds = get_thresholds()
    for item in _items_sincronizados(tienda_sel):
        nivel, etiqueta = stock_status(item.producto, item.cantidad or 0, thresholds)
        tipo_lectura = f"alerta_stock_bajo_v{int(item.version or 1)}"
        if nivel != "critico" or (tipo_lectura, item.id) in leidas:
            continue
        alertas.append({
            "tipo": "stock", "tono": "danger", "icono": "!",
            "titulo": f"Stock bajo · {item.producto}",
            "detalle": f"Quedan {float(item.cantidad or 0):g} {item.ume or 'unidades'} · {etiqueta}",
            "meta": tiendas_map.get(item.tienda_id, item.tienda_id),
            "destino": url_for("admin_alerta_ir", tipo="stock", referencia_id=item.id),
            "orden": item.actualizado or datetime(1970, 1, 1),
        })

    q_venc = RegistroVencimiento.query.filter_by(
        cliente_id=cliente_id, sinc_estado="sincronizado",
    )
    if tienda_sel != "ALL":
        q_venc = q_venc.filter_by(tienda_id=tienda_sel)
    for registro in q_venc.all():
        dias = _dias_hasta(registro.fecha_vencimiento)
        if dias is None or dias > 15 or ("alerta_vencimiento", registro.id) in leidas:
            continue
        cuando = (
            f"Vencido hace {-dias} día(s)" if dias < 0 else
            "Vence hoy" if dias == 0 else f"Vence en {dias} día(s)"
        )
        alertas.append({
            "tipo": "vencimiento", "tono": "danger" if dias < 7 else "warning",
            "icono": "⌛", "titulo": f"{cuando} · {registro.producto}",
            "detalle": f"{float(registro.cantidad or 0):g} {registro.ume} · vence {registro.fecha_vencimiento}",
            "meta": tiendas_map.get(registro.tienda_id, registro.tienda_id),
            "destino": url_for("admin_alerta_ir", tipo="vencimiento", referencia_id=registro.id),
            "orden": registro.creado or datetime(1970, 1, 1),
        })

    q_aver = RegistroAveriado.query.filter_by(
        cliente_id=cliente_id, sinc_estado="sincronizado", revisado=False,
    )
    if tienda_sel != "ALL":
        q_aver = q_aver.filter_by(tienda_id=tienda_sel)
    for registro in q_aver.order_by(RegistroAveriado.creado.desc()).all():
        if ("alerta_averiado", registro.id) in leidas:
            continue
        alertas.append({
            "tipo": "averiado", "tono": "warning", "icono": "!",
            "titulo": f"Averiado sin revisar · {registro.producto}",
            "detalle": f"{float(registro.cantidad or 0):g} {registro.ume} · {registro.detalle or 'Sin detalle'}",
            "meta": f"{tiendas_map.get(registro.tienda_id, registro.tienda_id)} · {registro.fecha}",
            "destino": url_for("admin_alerta_ir", tipo="averiado", referencia_id=registro.id),
            "orden": registro.creado or datetime(1970, 1, 1),
        })

    periodos_auditados = (
        InventarioPeriodo.query
        .filter_by(cliente_id=cliente_id)
        .filter(InventarioPeriodo.estado.in_(("Cerrado", "Conciliado", "Auditado")))
        .order_by(InventarioPeriodo.id.desc()).limit(20).all()
    )
    for periodo in periodos_auditados:
        if tienda_sel != "ALL" and periodo.tienda_id != tienda_sel:
            continue
        estado = estado_actualizacion_auditoria(
            periodo, catalogo_pendiente=bool(estado_catalogo["total"]),
        )
        if not estado["desactualizada"] or not estado["ultima_ejecucion"]:
            continue
        version_alerta = estado["ultima_actualizacion"] or estado["ultima_ejecucion"]
        version_id = int(version_alerta.timestamp() * 1_000_000)
        tipo_auditoria = f"alerta_auditoria_{version_id}"
        if (tipo_auditoria, periodo.id) in leidas:
            continue
        alertas.append({
            "tipo": "auditoria", "tono": "danger", "icono": "↻",
            "titulo": f"Re-ejecutar auditoría · Período #{periodo.numero}",
            "detalle": (
                "; ".join(estado["motivos"][:3])
                + ". Abre la auditoría y pulsa el botón rojo «Re-ejecutar auditoría»."
            ),
            "meta": tiendas_map.get(periodo.tienda_id, periodo.tienda_id),
            "destino": url_for("admin_alerta_ir", tipo="auditoria", referencia_id=periodo.id),
            "orden": estado["ultima_ejecucion"],
        })

    prioridad = {"danger": 0, "warning": 1, "success": 2}
    alertas = sorted(
        alertas,
        key=lambda a: (prioridad.get(a["tono"], 3), -a["orden"].timestamp()),
    )
    g._alertas_admin_key = cache_key
    g._alertas_admin = alertas
    return alertas


@app.route("/admin/alertas/<tipo>/<int:referencia_id>/ir")
@login_required(rol="administrador")
def admin_alerta_ir(tipo, referencia_id):
    cliente_id = get_cliente_filtro()
    username = session.get("usuario")
    destino = None
    tipo_guardado = None
    titulo = "Alerta revisada"

    if tipo == "stock":
        registro = InventarioItem.query.filter_by(id=referencia_id, cliente_id=cliente_id).first()
        if registro:
            tipo_guardado = f"alerta_stock_bajo_v{int(registro.version or 1)}"
            titulo = f"Stock bajo · {registro.producto}"
            destino = url_for(
                "admin_inventario", tienda=registro.tienda_id, categoria="Todas",
                estado="Todos", busqueda=registro.producto, alerta="Bajo stock",
            ) + "#inventario-detalle"
    elif tipo == "vencimiento":
        registro = RegistroVencimiento.query.filter_by(id=referencia_id, cliente_id=cliente_id).first()
        if registro:
            tipo_guardado = "alerta_vencimiento"
            titulo = f"Vencimiento · {registro.producto}"
            destino = url_for("admin_vencimientos", tienda=registro.tienda_id) + "#vencimientos-lista"
    elif tipo == "averiado":
        registro = RegistroAveriado.query.filter_by(id=referencia_id, cliente_id=cliente_id).first()
        if registro:
            tipo_guardado = "alerta_averiado"
            titulo = f"Averiado · {registro.producto}"
            destino = url_for(
                "admin_averiados", periodo_id=registro.periodo_id,
            ) + "#averiados-lista"
    elif tipo == "catalogo" and referencia_id == 0:
        from core.inventario import estado_sincronizacion_catalogo
        estado = estado_sincronizacion_catalogo(cliente_id, detallado=True)
        ultima_edicion = db.session.query(db.func.max(ExcelDetalleEdicion.id)).filter_by(
            cliente_id=cliente_id,
        ).scalar() or 0
        version = db.session.query(db.func.max(Producto.catalogo_version)).scalar() or 0
        tipo_guardado = f"alerta_catalogo_{int(version)}_{int(ultima_edicion)}_{int(estado['total'])}"[:40]
        titulo = "Catálogo pendiente de sincronizar"
        destino = url_for("desc.desc_sincronizar")
    elif tipo == "auditoria":
        registro = InventarioPeriodo.query.filter_by(
            id=referencia_id, cliente_id=cliente_id,
        ).first()
        if registro:
            from core.inventario import estado_sincronizacion_catalogo
            estado = estado_actualizacion_auditoria(
                registro,
                catalogo_pendiente=bool(
                    estado_sincronizacion_catalogo(cliente_id, detallado=True)["total"]
                ),
            )
            version_alerta = estado["ultima_actualizacion"] or estado["ultima_ejecucion"]
            if version_alerta:
                version_id = int(version_alerta.timestamp() * 1_000_000)
                tipo_guardado = f"alerta_auditoria_{version_id}"
                titulo = f"Re-ejecutar auditoría · Período #{registro.numero}"
                destino = url_for("admin_auditoria", periodo_id=registro.id)

    if not destino or not tipo_guardado:
        abort(404)
    lectura = NotificacionUsuario.query.filter_by(
        cliente_id=cliente_id, username=username,
        tipo=tipo_guardado, referencia_id=referencia_id,
    ).first()
    if lectura is None:
        db.session.add(NotificacionUsuario(
            cliente_id=cliente_id, username=username, tipo=tipo_guardado,
            referencia_id=referencia_id, titulo=titulo,
            mensaje="Abierta desde el centro unificado de alertas.", leida=True,
        ))
    else:
        lectura.leida = True
    db.session.commit()
    return redirect(destino)


@app.route("/admin/notificaciones/<int:notif_id>/ir")
@login_required(rol="administrador")
def admin_notificacion_ir(notif_id):
    cliente_id = get_cliente_filtro()
    notif = NotificacionUsuario.query.filter_by(
        id=notif_id,
        cliente_id=cliente_id,
        username=session.get("usuario"),
        tipo="periodo_cargado",
    ).first()
    if notif is None:
        abort(404)

    notif.leida = True
    periodo = db.session.get(InventarioPeriodo, notif.referencia_id) if notif.referencia_id else None
    db.session.commit()
    if periodo and periodo.cliente_id == cliente_id:
        return redirect(url_for("admin_periodo_detalle", periodo_id=periodo.id))

    flash("La carga fue reconocida, pero el período ya no está disponible.", "info")
    return redirect(url_for("admin_alertas"))


# --------------------------------------------------------------------------- #
#  Admin - Estado de sincronizacion
# --------------------------------------------------------------------------- #
@app.route("/admin/sincronizar")
@login_required(rol="administrador")
def admin_sincronizacion():
    cliente_id = get_cliente_filtro()
    tiendas = Tienda.query.filter_by(cliente_id=cliente_id).all()
    local_notice = pop_view_notice(session, "admin_sync_notice")
    filas = []
    total_pendientes = 0
    recepciones_catalogo_pendientes = 0
    for t in tiendas:
        ultimo_envio = (SincronizacionLog.query
                        .filter_by(cliente_id=cliente_id, tienda_id=t.id, tipo="envio")
                        .order_by(SincronizacionLog.timestamp.desc()).first())
        ultima_recepcion = (SincronizacionLog.query
                            .filter_by(cliente_id=cliente_id, tienda_id=t.id, tipo="recepcion")
                            .order_by(SincronizacionLog.timestamp.desc()).first())
        pendientes = InventarioItem.query.filter_by(
            cliente_id=cliente_id, tienda_id=t.id, sinc_estado="pendiente").count()
        empleados_tienda = Usuario.query.filter_by(
            cliente_id=cliente_id,
            tienda_id=t.id,
            rol="empleado",
        ).all()
        catalogo_usuarios_pendientes = 0
        catalogo_cambios = 0
        for empleado in empleados_tienda:
            pendiente_catalogo, cambios = catalogo_pendiente_usuario(
                cliente_id, empleado.username
            )
            if pendiente_catalogo:
                catalogo_usuarios_pendientes += 1
                catalogo_cambios = max(catalogo_cambios, cambios)
        recepciones_catalogo_pendientes += catalogo_usuarios_pendientes
        total_pendientes += pendientes
        filas.append({
            "tienda": t.nombre, "tienda_id": t.id, "activa": t.activa,
            "ultimo_envio": format_utc_naive_to_local(ultimo_envio.timestamp) if ultimo_envio else None,
            "ultima_recepcion": format_utc_naive_to_local(ultima_recepcion.timestamp) if ultima_recepcion else None,
            "pendientes": pendientes,
            "catalogo_usuarios_pendientes": catalogo_usuarios_pendientes,
            "catalogo_cambios": catalogo_cambios,
        })
    catalogo_por_publicar = Producto.query.filter_by(visible_empleado=False).count()
    return render_template("admin_sync_estado.html", filas=filas,
                           total_pendientes=total_pendientes,
                           catalogo_por_publicar=catalogo_por_publicar,
                           recepciones_catalogo_pendientes=recepciones_catalogo_pendientes,
                           local_notice=local_notice,
                           hide_global_flash=True)


@app.route("/admin/sincronizar/forzar", methods=["POST"])
@login_required(rol="administrador")
def admin_sincronizar_forzar():
    cliente_id = get_cliente_filtro()
    pendientes = InventarioItem.query.filter_by(cliente_id=cliente_id, sinc_estado="pendiente").all()
    tiendas_afectadas = set()
    for item in pendientes:
        item.sinc_estado = "sincronizado"
        tiendas_afectadas.add(item.tienda_id)
    for tid in tiendas_afectadas:
        db.session.add(SincronizacionLog(
            cliente_id=cliente_id, tienda_id=tid, usuario=session["usuario"],
            tipo="envio", accion="forzada_admin"))
        db.session.add(SincronizacionLog(
            cliente_id=cliente_id, tienda_id=tid, usuario=session["usuario"],
            tipo="recepcion", accion="forzada_admin"))
    db.session.commit()
    set_view_notice(session, "admin_sync_notice",
                    f"Sincronizacion forzada: {len(pendientes)} item(s) sincronizado(s).", "success")
    return redirect(url_for("admin_sincronizacion") + "#sync-estado")


# --------------------------------------------------------------------------- #
#  Admin - Inventario
# --------------------------------------------------------------------------- #
@app.route("/admin/inventario")
@login_required(rol="administrador")
def admin_inventario():
    cliente_id = get_cliente_filtro()
    tiendas = Tienda.query.filter_by(cliente_id=cliente_id, activa=True).all()
    tienda_id = request.args.get("tienda") or get_tienda_filtro() or (tiendas[0].id if tiendas else "T001")
    categoria_filtro = request.args.get("categoria", "Todas")
    busqueda = (request.args.get("busqueda") or "").strip().lower()
    estado_filtro = request.args.get("estado", "Todos")
    alerta_filtro = request.args.get("alerta", "Todos") or "Todos"
    context = build_admin_inventory_context(
        cliente_id=cliente_id,
        tiendas=tiendas,
        tienda_id=tienda_id,
        categoria_filtro=categoria_filtro,
        busqueda=busqueda,
        estado_filtro=estado_filtro,
        alerta_filtro=alerta_filtro,
    )

    return render_template(
        "admin_inventario.html",
        tiendas=tiendas,
        tienda_id=tienda_id,
        categoria_filtro=categoria_filtro,
        busqueda=request.args.get("busqueda", ""),
        estado_filtro=estado_filtro,
        alerta_filtro=alerta_filtro,
        categorias=CATEGORIAS,
        **context,
    )


# --------------------------------------------------------------------------- #
#  Admin - Historial
# --------------------------------------------------------------------------- #
@app.route("/admin/historial")
@login_required(rol="administrador")
def admin_historial():
    cliente_id = get_cliente_filtro()
    tiendas = Tienda.query.filter_by(cliente_id=cliente_id).all()
    tienda_id = request.args.get("tienda") or (tiendas[0].id if tiendas else "T001")
    empleado = request.args.get("empleado", "Todos")
    tipo = request.args.get("tipo", "Todos")
    fecha_inicio = request.args.get("fecha_inicio", date.today().replace(day=1).isoformat())
    fecha_fin = request.args.get("fecha_fin", date.today().isoformat())
    selected_fecha = request.args.get("fecha")

    context = build_admin_historial_context(
        cliente_id=cliente_id,
        tiendas=tiendas,
        tienda_id=tienda_id,
        empleado=empleado,
        tipo=tipo,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        fecha=selected_fecha,
    )
    return render_template("admin_historial.html", tiendas=tiendas, **context)


# --------------------------------------------------------------------------- #
#  Admin - Configuracion de tiendas
# --------------------------------------------------------------------------- #
@app.route("/admin/configuracion")
@login_required(rol="administrador")
def admin_configuracion():
    if (request.args.get("section") or "productos").strip().lower() != "tiendas":
        return redirect(url_for("admin_precios", tab=request.args.get("tab")))
    cliente_id = get_cliente_filtro()
    tiendas = Tienda.query.filter_by(cliente_id=cliente_id).all()
    default = next((t.id for t in tiendas if t.es_default), None)
    local_notice = session.pop("admin_config_notice", None)
    active_section = (request.args.get("section") or ((local_notice or {}).get("section")) or "productos").strip().lower()
    if active_section not in ("productos", "tiendas"):
        active_section = "productos"
    active_tab = _safe_config_tab(
        request.args.get("tab")
        or ((local_notice or {}).get("tab"))
        or "tab-impulsivo"
    )
    productos_impulsivo = Producto.query.filter_by(categoria="Impulsivo").order_by(Producto.nombre).all()
    productos_extras = Producto.query.filter(
        Producto.categoria.in_(("Fanee", "Extras"))
    ).order_by(Producto.nombre).all()
    productos_kilos = Producto.query.filter_by(categoria="Por Kilos").order_by(Producto.nombre).all()
    precios_map = {p.producto_nombre: p for p in ProductoPrecio.query.all()}
    return render_template("admin_configuracion.html",
                           tiendas=tiendas, default=default,
                           productos_impulsivo=productos_impulsivo,
                           productos_extras=productos_extras,
                           productos_kilos=productos_kilos,
                           precios_map=precios_map,
                           active_tab=active_tab,
                           active_section=active_section,
                           local_notice=local_notice,
                           hide_global_flash=True)


@app.route("/admin/configuracion/precios", methods=["POST"])
@login_required(rol="administrador")
def producto_precio_guardar():
    ids = request.form.getlist("ids")
    hubo_cambios = False
    for pid in ids:
        try:
            pid_int = int(pid)
        except ValueError:
            continue
        producto = db.session.get(Producto, pid_int)
        if producto is None or producto.categoria not in ("Impulsivo", "Fanee", "Extras"):
            continue
        precio_val = request.form.get(f"precio_{pid}") or None
        precio_caja_val = request.form.get(f"precio_caja_{pid}") or None
        caja_val = request.form.get(f"caja_{pid}") or None
        bulto_val = request.form.get(f"bulto_{pid}") or None
        try:
            # precio llega sin puntos de miles (el JS los quita antes de submit)
            precio_val = int(precio_val) if precio_val else None
            precio_caja_val = int(precio_caja_val) if precio_caja_val else None
            caja_val = float(caja_val) if caja_val else None
            bulto_val = float(bulto_val) if bulto_val else None
        except ValueError:
            continue
        rec = ProductoPrecio.query.filter_by(producto_nombre=producto.nombre).first()
        if rec is None:
            rec = ProductoPrecio(producto_nombre=producto.nombre, categoria=producto.categoria,
                                 producto_id=producto.id)
            db.session.add(rec)
        elif rec.producto_id is None:
            rec.producto_id = producto.id
        anterior = (
            rec.precio, rec.precio_por_caja, rec.unidades_por_caja,
            rec.unidades_por_bulto,
        )
        rec.precio = precio_val
        rec.precio_por_caja = precio_caja_val
        rec.unidades_por_caja = caja_val
        rec.unidades_por_bulto = bulto_val
        hubo_cambios = hubo_cambios or anterior != (
            rec.precio, rec.precio_por_caja, rec.unidades_por_caja,
            rec.unidades_por_bulto,
        )
    if hubo_cambios:
        marcar_cambio_catalogo(
            get_cliente_filtro(), "Precios o conversiones del catálogo actualizados",
        )
    db.session.commit()
    flash("Precios y cantidades actualizados correctamente.", "success")
    return redirect(url_for("admin_precios"))


@app.route("/admin/producto/crear", methods=["POST"])
@login_required(rol="administrador")
def producto_crear():
    nombre = (request.form.get("nombre") or "").strip()
    categoria = (request.form.get("categoria") or "").strip()
    active_tab = _catalog_tab_categoria(categoria)

    if not nombre:
        _set_admin_precios_notice("El nombre del producto es obligatorio.", "error", active_tab)
        return redirect(url_for("admin_precios", tab=active_tab) + "#catalogo-alta")
    if categoria not in ("Impulsivo", "Por Kilos", "Fanee"):
        _set_admin_precios_notice("Categoría no válida.", "error", active_tab)
        return redirect(url_for("admin_precios", tab=active_tab) + "#catalogo-alta")
    if Producto.query.filter_by(nombre=nombre, categoria=categoria).first():
        _set_admin_precios_notice(f"Ya existe '{nombre}' en {categoria}.", "warning", active_tab)
        return redirect(url_for("admin_precios", tab=active_tab) + "#catalogo-alta")

    def numero_opcional(campo, *, moneda=False):
        valor = (request.form.get(campo) or "").strip()
        if not valor:
            return None
        normalizado = valor.replace(".", "") if moneda else valor
        numero = float(normalizado.replace(",", "."))
        if numero < 0:
            raise ValueError
        return numero

    try:
        precio = numero_opcional("precio", moneda=True)
        precio_caja = numero_opcional("precio_caja", moneda=True)
        unidades_caja = numero_opcional("unidades_por_caja")
        cajas_bulto = numero_opcional("cajas_por_bulto")
    except ValueError:
        _set_admin_precios_notice("Los precios y cantidades deben ser números positivos.", "error", active_tab)
        return redirect(url_for("admin_precios", tab=active_tab) + "#catalogo-alta")

    producto = Producto(
        nombre=nombre, categoria=categoria, visible_empleado=False,
        codigo_articulo=(request.form.get("codigo_articulo") or "").strip() or None,
    )
    db.session.add(producto)
    db.session.flush()
    if any(valor is not None for valor in (precio, precio_caja, unidades_caja, cajas_bulto)):
        db.session.add(ProductoPrecio(
            cliente_id=get_cliente_filtro(), producto_id=producto.id,
            producto_nombre=producto.nombre, categoria=producto.categoria,
            precio=precio,
            precio_por_caja=precio_caja if categoria != "Por Kilos" else None,
            unidades_por_caja=unidades_caja if categoria != "Por Kilos" else None,
            unidades_por_bulto=cajas_bulto if categoria != "Por Kilos" else None,
        ))
    db.session.commit()
    _set_admin_precios_notice(
        f"Producto '{nombre}' agregado a {categoria}. Aplica la sincronización para vincularlo con el Excel.",
        "success",
        active_tab,
    )
    return redirect(url_for("admin_precios", tab=active_tab) + "#precios-tabs")


@app.route("/admin/producto/<int:producto_id>/editar", methods=["POST"])
@login_required(rol="administrador")
def producto_editar(producto_id):
    active_tab = _safe_catalog_tab(request.form.get("active_tab"))
    producto = db.session.get(Producto, producto_id)
    if producto is None:
        abort(404)

    nombre_nuevo = (request.form.get("nombre") or "").strip()
    nombre_anterior = producto.nombre
    if not nombre_nuevo:
        _set_admin_precios_notice("El nombre del producto es obligatorio.", "error", active_tab)
        return redirect(url_for("admin_precios", tab=active_tab) + "#precios-tabs")
    if len(nombre_nuevo) > 160:
        _set_admin_precios_notice("El nombre no puede superar 160 caracteres.", "error", active_tab)
        return redirect(url_for("admin_precios", tab=active_tab) + "#precios-tabs")

    duplicado = (
        Producto.query
        .filter(
            Producto.id != producto.id,
            Producto.categoria == producto.categoria,
            db.func.lower(Producto.nombre) == nombre_nuevo.lower(),
        )
        .first()
    )
    if duplicado:
        _set_admin_precios_notice(
            f"Ya existe '{nombre_nuevo}' en {producto.categoria}.", "warning", active_tab
        )
        return redirect(url_for("admin_precios", tab=active_tab) + "#precios-tabs")

    if nombre_nuevo == nombre_anterior:
        _set_admin_precios_notice("El producto ya tiene ese nombre.", "info", active_tab)
        return redirect(url_for("admin_precios", tab=active_tab) + "#precios-tabs")

    # Las tablas operativas conservan algunos nombres descriptivos aunque ya
    # tengan una FK estable. Mantenerlos alineados evita que el producto
    # aparezca duplicado tras editarlo.
    InventarioItem.query.filter_by(
        producto=nombre_anterior, categoria=producto.categoria
    ).update({"producto": nombre_nuevo}, synchronize_session=False)

    precio = ProductoPrecio.query.filter_by(producto_id=producto.id).first()
    if precio is None:
        precio = ProductoPrecio.query.filter_by(producto_nombre=nombre_anterior).first()
    if precio is not None:
        precio.producto_id = producto.id
        precio.producto_nombre = nombre_nuevo

    StockThreshold.query.filter(
        (StockThreshold.producto_id == producto.id)
        | (StockThreshold.producto == nombre_anterior)
    ).update(
        {"producto_id": producto.id, "producto": nombre_nuevo},
        synchronize_session=False,
    )
    ExcelDetalle.query.filter_by(producto_id=producto.id).update(
        {"producto_nombre_interno": nombre_nuevo}, synchronize_session=False
    )
    FacturaCompraDetalle.query.filter_by(producto_id=producto.id).update(
        {"producto_nombre": nombre_nuevo}, synchronize_session=False
    )
    ProductoRelacionado.query.filter_by(producto_principal=nombre_anterior).update(
        {"producto_principal": nombre_nuevo}, synchronize_session=False
    )
    ProductoRelacionado.query.filter_by(producto_relacionado=nombre_anterior).update(
        {"producto_relacionado": nombre_nuevo}, synchronize_session=False
    )

    producto.nombre = nombre_nuevo
    producto.catalogo_version = int(
        db.session.query(db.func.max(Producto.catalogo_version)).scalar() or 0
    ) + 1
    marcar_cambio_catalogo(
        get_cliente_filtro(), f"Producto renombrado: {nombre_anterior} → {nombre_nuevo}",
    )
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        _set_admin_precios_notice(
            "No se pudo cambiar el nombre porque ya está usado en datos del inventario.",
            "error",
            active_tab,
        )
        return redirect(url_for("admin_precios", tab=active_tab) + "#precios-tabs")

    _set_admin_precios_notice(
        f"Producto '{nombre_anterior}' renombrado a '{nombre_nuevo}'.", "success", active_tab
    )
    return redirect(url_for("admin_precios", tab=active_tab) + "#precios-tabs")


@app.route("/admin/producto/<int:producto_id>/eliminar", methods=["POST"])
@login_required(rol="administrador")
def producto_eliminar(producto_id):
    active_tab = _safe_catalog_tab(request.form.get("active_tab"))
    producto = db.session.get(Producto, producto_id)
    if producto is None:
        abort(404)
    # Eliminar registro de precios asociado si existe
    precio_rec = ProductoPrecio.query.filter_by(producto_nombre=producto.nombre).first()
    if precio_rec:
        db.session.delete(precio_rec)
    nombre = producto.nombre
    db.session.delete(producto)
    marcar_cambio_catalogo(get_cliente_filtro(), f"Producto eliminado: {nombre}")
    db.session.commit()
    _set_admin_precios_notice(f"Producto '{nombre}' eliminado.", "info", active_tab)
    return redirect(url_for("admin_precios", tab=active_tab) + "#precios-tabs")


@app.route("/admin/tienda/crear", methods=["POST"])
@login_required(rol="administrador")
def tienda_crear():
    cliente_id = get_cliente_filtro()
    nombre = (request.form.get("nombre") or "").strip()
    direccion = (request.form.get("direccion") or "").strip() or "Direccion no especificada"
    if not nombre:
        _set_admin_config_notice("tiendas", "El nombre de la tienda es obligatorio.", "error")
        return redirect(url_for("admin_configuracion", section="tiendas") + "#sec-tiendas")

    ids = [int(t.id[1:]) for t in Tienda.query.filter_by(cliente_id=cliente_id).all() if t.id.startswith("T") and t.id[1:].isdigit()]
    nuevo_id = f"T{(max(ids) + 1) if ids else 1:03d}"
    db.session.add(Tienda(id=nuevo_id, cliente_id=cliente_id, nombre=nombre, direccion=direccion, activa=True))
    db.session.commit()
    _set_admin_config_notice("tiendas", f"Tienda creada con ID {nuevo_id}.", "success")
    return redirect(url_for("admin_configuracion", section="tiendas") + "#sec-tiendas")


@app.route("/admin/tienda/<tienda_id>/toggle", methods=["POST"])
@login_required(rol="administrador")
def tienda_toggle(tienda_id):
    cliente_id = get_cliente_filtro()
    tienda = Tienda.query.get_or_404(tienda_id)
    if tienda.cliente_id != cliente_id:
        abort(403)
    tienda.activa = not tienda.activa
    db.session.commit()
    _set_admin_config_notice("tiendas", f"Tienda {tienda.nombre} {'activada' if tienda.activa else 'desactivada'}.", "info")
    return redirect(url_for("admin_configuracion", section="tiendas") + "#sec-tiendas")


@app.route("/admin/tienda/<tienda_id>/default", methods=["POST"])
@login_required(rol="administrador")
def tienda_default(tienda_id):
    cliente_id = get_cliente_filtro()
    tiendas = Tienda.query.filter_by(cliente_id=cliente_id).all()
    for t in tiendas:
        t.es_default = (t.id == tienda_id)
    db.session.commit()
    _set_admin_config_notice("tiendas", "Tienda predeterminada actualizada.", "success")
    return redirect(url_for("admin_configuracion", section="tiendas") + "#sec-tiendas")


# --------------------------------------------------------------------------- #
#  Admin - Delivery (catalogo)
# --------------------------------------------------------------------------- #
@app.route("/admin/delivery", methods=["GET", "POST"])
@login_required(rol="administrador")
def admin_delivery():
    cliente_id = get_cliente_filtro()
    if request.method == "POST":
        section = request.form.get("_section") or "delivery-form"
        nombre = (request.form.get("nombre") or "").strip()
        precio = request.form.get("precio", type=float) or 0
        es_promocion = request.form.get("es_promocion") == "on"
        if not nombre:
            set_view_notice(session, "admin_delivery_notice", "El nombre del producto es obligatorio.", "error")
        else:
            existente = DeliveryProducto.query.filter_by(cliente_id=cliente_id, nombre=nombre).first()
            if existente:
                existente.precio = precio
                existente.es_promocion = es_promocion
                existente.activo = True
            else:
                db.session.add(DeliveryProducto(
                    cliente_id=cliente_id,
                    nombre=nombre,
                    precio=precio,
                    es_promocion=es_promocion,
                    activo=True,
                ))
            db.session.commit()
            set_view_notice(session, "admin_delivery_notice", "Producto agregado al catalogo.", "success")
            section = "delivery-catalogo"

    catalogo = DeliveryProducto.query.filter_by(cliente_id=cliente_id).order_by(DeliveryProducto.nombre).all()
    ventas = DeliveryVenta.query.filter_by(cliente_id=cliente_id).order_by(DeliveryVenta.id.desc()).limit(20).all()
    total_ventas = sum(float(v.total or 0) for v in ventas)
    local_notice = pop_view_notice(session, "admin_delivery_notice")

    return render_template(
        "admin_delivery.html",
        catalogo=catalogo,
        ventas=ventas,
        total_ventas=total_ventas,
        local_notice=local_notice,
        hide_global_flash=True,
    )


@app.route("/admin/delivery/<int:prod_id>/toggle", methods=["POST"])
@login_required(rol="administrador")
def delivery_toggle(prod_id):
    cliente_id = get_cliente_filtro()
    producto = DeliveryProducto.query.get_or_404(prod_id)
    if producto.cliente_id != cliente_id:
        abort(403)
    producto.activo = not producto.activo
    db.session.commit()
    accion = "activado" if producto.activo else "desactivado"
    set_view_notice(session, "admin_delivery_notice", f"Producto {accion} en el catalogo.", "info")
    return redirect(url_for("admin_delivery") + "#delivery-catalogo")


# --------------------------------------------------------------------------- #
#  Admin - Registros Averiados
# --------------------------------------------------------------------------- #
@app.route("/admin/averiados")
@login_required(rol="administrador")
def admin_averiados():
    cliente_id = get_cliente_filtro()
    periodos = (
        InventarioPeriodo.query.filter_by(cliente_id=cliente_id)
        .order_by(InventarioPeriodo.id.desc()).all()
    )
    periodo_id = request.args.get("periodo_id", type=int)
    periodo_f = next((p for p in periodos if p.id == periodo_id), None)
    if periodo_f is None and periodos:
        periodo_f = periodos[0]
        periodo_id = periodo_f.id
    tiendas_map = {
        tienda.id: tienda.nombre
        for tienda in Tienda.query.filter_by(cliente_id=cliente_id).all()
    }
    local_notice = pop_view_notice(session, "admin_averiados_notice")

    registros = []
    if periodo_f is not None:
        # Reconoce solo las alertas del período abierto, sin ocultar las de otros.
        RegistroAveriado.query.filter_by(
            cliente_id=cliente_id, periodo_id=periodo_f.id,
            sinc_estado="sincronizado", revisado=False,
        ).update({"revisado": True}, synchronize_session=False)
        db.session.commit()
        registros = (
            RegistroAveriado.query.filter_by(
                cliente_id=cliente_id, periodo_id=periodo_f.id,
                sinc_estado="sincronizado",
            )
            .order_by(RegistroAveriado.creado.desc()).all()
        )

    return render_template("admin_averiados.html",
                           registros=registros, periodos=periodos,
                           periodo_f=periodo_f, tiendas_map=tiendas_map,
                           local_notice=local_notice,
                           notif_averiados=0,
                           hide_global_flash=True)


@app.route("/admin/averiados/revisar", methods=["POST"])
@login_required(rol="administrador")
def admin_averiados_revisar():
    cliente_id = get_cliente_filtro()
    periodo_id = request.form.get("periodo_id", type=int)
    periodo = InventarioPeriodo.query.filter_by(
        id=periodo_id, cliente_id=cliente_id,
    ).first()
    if periodo is None:
        flash("Selecciona un período contable válido.", "warning")
        return redirect(url_for("admin_averiados"))

    q = RegistroAveriado.query.filter(
        RegistroAveriado.cliente_id == cliente_id,
        RegistroAveriado.periodo_id == periodo.id,
        RegistroAveriado.sinc_estado == "sincronizado",
        RegistroAveriado.revisado.is_(False),
    )

    revisados = q.update({"revisado": True}, synchronize_session=False)
    db.session.commit()
    set_view_notice(session, "admin_averiados_notice",
                    f"Registros marcados como revisados: {revisados}.", "success")
    return redirect(url_for("admin_averiados", periodo_id=periodo.id) + "#averiados-lista")


# --------------------------------------------------------------------------- #
#  Admin - Registros Stock Vencimiento
# --------------------------------------------------------------------------- #
@app.route("/admin/vencimientos")
@login_required(rol="administrador")
def admin_vencimientos():
    cliente_id = get_cliente_filtro()
    tienda_f  = request.args.get("tienda", "Todas")
    desde     = request.args.get("desde", date.today().replace(day=1).isoformat())
    hasta     = request.args.get("hasta", date.today().isoformat())
    tiendas   = Tienda.query.filter_by(cliente_id=cliente_id).all()
    local_notice = pop_view_notice(session, "admin_vencimientos_notice")

    # Al abrir la vista, se consideran vistas las notificaciones sincronizadas.
    marcar_vencimientos_vistos(cliente_id)
    db.session.commit()

    context = build_admin_vencimientos_context(
        cliente_id=cliente_id,
        tiendas=tiendas,
        tienda_f=tienda_f,
        desde=desde,
        hasta=hasta,
        local_notice=local_notice,
    )
    return render_template("admin_vencimientos.html", **context)


@app.route("/admin/vencimientos/revisar", methods=["POST"])
@login_required(rol="administrador")
def admin_vencimientos_revisar():
    cliente_id = get_cliente_filtro()
    tienda_f  = request.form.get("tienda", "Todas")
    desde     = request.form.get("desde", date.today().replace(day=1).isoformat())
    hasta     = request.form.get("hasta", date.today().isoformat())

    revisados = marcar_vencimientos_filtrados(cliente_id, tienda_f, desde, hasta)
    db.session.commit()
    set_view_notice(session, "admin_vencimientos_notice",
                    f"Registros marcados como revisados: {revisados}.", "success")
    return redirect(url_for("admin_vencimientos", tienda=tienda_f, desde=desde, hasta=hasta) + "#vencimientos-lista")


# --------------------------------------------------------------------------- #
#  Exportacion a Excel
# --------------------------------------------------------------------------- #
def _build_excel(headers, rows, sheet_name="Datos"):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = Workbook()
    ws = wb.active
    if ws is None:
        ws = wb.create_sheet(title="Datos")
    ws.title = sheet_name[:31]

    header_fill = PatternFill("solid", fgColor="1D4ED8")
    header_font = Font(bold=True, color="FFFFFF")
    for col, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=col, value=h)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center")

    for r, fila in enumerate(rows, start=2):
        for col, val in enumerate(fila, start=1):
            ws.cell(row=r, column=col, value=val)

    for col in range(1, len(headers) + 1):
        ws.column_dimensions[chr(64 + col)].width = 22

    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream


@app.route("/admin/inventario/export")
@login_required(rol="administrador")
def export_inventario():
    tienda_id = request.args.get("tienda", "T001")
    thresholds = get_thresholds()
    items = {(i.categoria, i.producto): i
             for i in InventarioItem.query.filter_by(tienda_id=tienda_id).all()}
    productos_db = get_productos_db()
    rows = []
    for categoria in CATEGORIAS:
        for producto in productos_db.get(categoria, []):
            item = items.get((categoria, producto))
            cantidad = item.cantidad if item else 0
            modo = item.ume if item else "N/A"
            _, etiqueta = stock_status(producto, cantidad, thresholds)
            estado = "Cargado" if cantidad > 0 else "No cargado"
            rows.append([categoria, producto, cantidad, modo, etiqueta, estado])

    stream = _build_excel(
        ["Categoria", "Producto", "Cantidad", "Modo", "Estado Stock", "Estado"],
        rows, "Inventario")
    return send_file(stream, as_attachment=True,
                     download_name=f"inventario_{tienda_id}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/admin/historial/export")
@login_required(rol="administrador")
def export_historial():
    tienda_id = request.args.get("tienda", "T001")
    registros = HistorialMovimiento.query.filter_by(tienda_id=tienda_id)\
        .order_by(HistorialMovimiento.fecha.desc()).all()
    rows = [[r.fecha, r.hora, r.usuario, r.categoria, r.producto, r.cantidad,
             r.modo, r.tipo_inventario] for r in registros]
    stream = _build_excel(
        ["Fecha", "Hora", "Usuario", "Categoria", "Producto", "Cantidad", "Modo", "Tipo"],
        rows, "Historial")
    return send_file(stream, as_attachment=True,
                     download_name=f"historial_{tienda_id}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# =========================================================================== #
#  MÓDULO DE AUDITORÍA — Rutas de Inventario Periódico                         #
# =========================================================================== #

@app.route("/admin/periodos")
@login_required(rol="administrador")
def admin_periodos():
    cliente_id = get_cliente_filtro()
    actualizar_estados_periodos(cliente_id=cliente_id)
    tienda_sel = get_tienda_filtro()
    tiendas = Tienda.query.filter_by(cliente_id=cliente_id, activa=True).all()
    q = InventarioPeriodo.query.filter_by(cliente_id=cliente_id)
    if tienda_sel != "ALL":
        q = q.filter_by(tienda_id=tienda_sel)
    periodos = q.order_by(InventarioPeriodo.id.desc()).all()
    tiendas_map = {tienda.id: tienda.nombre for tienda in tiendas}
    return render_template(
        "admin_periodos.html",
        periodos=periodos,
        tiendas=tiendas,
        tiendas_map=tiendas_map,
        autoclose_horas=get_autoclose_horas(cliente_id),
        mes_actual=today_local_iso()[:7],
    )


@app.route("/admin/periodos/crear", methods=["POST"])
@login_required(rol="administrador")
def admin_periodo_crear():
    cliente_id = get_cliente_filtro()
    tienda_id = request.form.get("tienda_id", "").strip()
    fecha_desde = request.form.get("fecha_desde", "").strip()
    fecha_hasta = request.form.get("fecha_hasta", "").strip()
    observacion = (request.form.get("observacion") or "").strip()

    if not tienda_id or not fecha_desde or not fecha_hasta:
        flash("Completá todos los campos para crear el período.", "warning")
        return redirect(url_for("admin_periodos"))

    try:
        d_desde = date.fromisoformat(fecha_desde)
        d_hasta = date.fromisoformat(fecha_hasta)
        dias = (d_hasta - d_desde).days
        if dias <= 0:
            raise ValueError("Rango inválido")
    except ValueError:
        flash("Fechas inválidas.", "error")
        return redirect(url_for("admin_periodos"))

    conflicto = buscar_periodo_historico_solapado(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )
    if conflicto:
        flash(
            f"No se creó el período: el rango se superpone con el período histórico "
            f"#{conflicto.numero} ({conflicto.fecha_desde} al {conflicto.fecha_hasta}).",
            "warning",
        )
        return redirect(url_for("admin_periodos"))

    if periodo_es_retroactivo(fecha_desde) and request.form.get("confirmar_retroactivo") != "1":
        flash(
            "La fecha pertenece a un mes anterior. Confirmá expresamente la creación "
            "del período retroactivo.",
            "warning",
        )
        return redirect(url_for("admin_periodos"))

    ultimo = (InventarioPeriodo.query
              .filter_by(cliente_id=cliente_id, tienda_id=tienda_id)
              .order_by(InventarioPeriodo.numero.desc())
              .first())
    numero = (ultimo.numero + 1) if ultimo else 1

    p = InventarioPeriodo(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        numero=numero,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        dias_periodo=dias,
        estado="Abierto",
        usuario_creador=session["usuario"],
        observacion=observacion,
    )
    db.session.add(p)
    db.session.flush()  # necesitamos p.id antes de inicializar sus pendientes

    notifs_creadas = _notificar_nuevo_periodo(p)
    retroalimentar_periodo_desde_items(p)
    db.session.commit()

    msg = f"Período #{numero} creado vacío, con sus productos pendientes de carga."
    if notifs_creadas:
        msg += f" Notificaciones enviadas: {notifs_creadas}."
    flash(msg, "success")
    return redirect(url_for("admin_periodo_detalle", periodo_id=p.id))


@app.route("/admin/periodos/<int:periodo_id>")
@login_required(rol="administrador")
def admin_periodo_detalle(periodo_id):
    cliente_id = get_cliente_filtro()
    periodo = db.session.get(InventarioPeriodo, periodo_id)
    if not periodo or periodo.cliente_id != cliente_id:
        abort(404)

    conteos = ConteoDetalle.query.filter_by(periodo_id=periodo_id).order_by(
        ConteoDetalle.categoria, ConteoDetalle.producto_nombre).all()
    ajustes = AjusteInventario.query.filter_by(periodo_id=periodo_id).order_by(
        AjusteInventario.fecha_ajuste.desc()).all()
    excel_imp = (ExcelImportado.query.filter_by(periodo_id=periodo_id)
                 .order_by(ExcelImportado.id.desc()).first())
    auditoria = (AuditoriaResultado.query.filter_by(periodo_id=periodo_id)
                 .filter(AuditoriaResultado.estado_auditoria != "Archivado")
                 .order_by(AuditoriaResultado.severidad.desc(),
                            AuditoriaResultado.impacto.desc()).all())
    facturas_pendientes_auditoria = (
        FacturaCompraDetalle.query.join(FacturaCompra)
        .filter(
            FacturaCompra.periodo_id == periodo_id,
            FacturaCompra.cliente_id == cliente_id,
            ~FacturaCompraDetalle.estado_vinculacion.in_(("vinculado", "aplicado", "fuera_rango")),
        )
        .count()
    )
    productos_catalogo = (
        Producto.query
        .order_by(Producto.categoria, Producto.nombre)
        .all()
    )
    # Derivar las categorías del catálogo real evita que el selector quede
    # vacío o desactualizado cuando se agregan categorías nuevas.
    categorias_catalogo = sorted({
        producto.categoria for producto in productos_catalogo
        if producto.categoria
    })
    from core.inventario import estado_sincronizacion_catalogo
    estado_auditoria = estado_actualizacion_auditoria(
        periodo,
        catalogo_pendiente=estado_sincronizacion_catalogo(cliente_id)["total"] > 0,
    )

    return render_template(
        "admin_periodo_detalle.html",
        periodo=periodo,
        tienda_nombre=_nombre_tienda_periodo(periodo),
        conteos=conteos,
        ajustes=ajustes,
        excel_imp=excel_imp,
        auditoria=auditoria,
        facturas_pendientes_auditoria=facturas_pendientes_auditoria,
        productos_catalogo=productos_catalogo,
        categorias=categorias_catalogo,
        estado_actualizacion_auditoria=estado_auditoria,
    )


@app.route("/admin/periodos/<int:periodo_id>/cerrar", methods=["POST"])
@login_required(rol="administrador")
def admin_periodo_cerrar(periodo_id):
    cliente_id = get_cliente_filtro()
    periodo = db.session.get(InventarioPeriodo, periodo_id)
    if not periodo or periodo.cliente_id != cliente_id:
        abort(404)

    # Validar: fue_cargado=False significa producto pendiente, no cero confirmado
    sin_cargar_q = ConteoDetalle.query.filter_by(
        periodo_id=periodo_id, fue_cargado=False
    ).all()
    sin_cargar = [c.producto_nombre for c in sin_cargar_q]

    if sin_cargar and not request.form.get("forzar"):
        flash(
            f"No se puede cerrar: {len(sin_cargar)} producto(s) pendiente(s) de carga. "
            f"Cargálos con cantidad 0 para confirmar que no hay stock, "
            f"o usá 'Forzar cierre'.",
            "warning",
        )
        return redirect(url_for("admin_periodo_detalle", periodo_id=periodo_id))

    periodo.estado = "Cerrado"
    periodo.fecha_cierre = utc_now()
    db.session.commit()
    flash("Período cerrado correctamente.", "success")
    return redirect(url_for("admin_periodo_detalle", periodo_id=periodo_id))


def _marcar_auditoria_por_cambio_admin(periodo, motivo: str) -> bool:
    """Marca una auditoría existente como pendiente sin recalcularla en silencio."""
    tiene_auditoria = (
        AuditoriaResultado.query.filter_by(
            periodo_id=periodo.id, cliente_id=periodo.cliente_id,
        )
        .filter(AuditoriaResultado.estado_auditoria != "Archivado")
        .first()
        is not None
    )
    marcar_cambio_auditoria(periodo.id, periodo.cliente_id, motivo)
    return tiene_auditoria


@app.route("/admin/periodos/<int:periodo_id>/ajuste", methods=["POST"])
@login_required(rol="administrador")
def admin_periodo_ajuste(periodo_id):
    cliente_id = get_cliente_filtro()
    periodo = db.session.get(InventarioPeriodo, periodo_id)
    if not periodo or periodo.cliente_id != cliente_id:
        abort(404)

    producto_nombre = (request.form.get("producto_nombre") or "").strip()
    categoria = (request.form.get("categoria") or "").strip()
    try:
        cantidad, unidad_ajuste = empleado_service.normalizar_ajuste_categoria(
            categoria, request.form.get("cantidad", 0)
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin_periodo_detalle", periodo_id=periodo_id))
    motivo = request.form.get("motivo", "Otro")
    observacion = (request.form.get("observacion") or "").strip()
    impacta_stock = request.form.get("impacta_stock") == "1"
    if ajuste_es_baja_no_imputable(motivo):
        impacta_stock = False

    if not producto_nombre:
        flash("Seleccioná un producto.", "warning")
        return redirect(url_for("admin_periodo_detalle", periodo_id=periodo_id))

    producto = Producto.query.filter_by(nombre=producto_nombre, categoria=categoria).first()
    if producto is None:
        flash("Seleccioná un producto válido del catálogo.", "warning")
        return redirect(url_for("admin_periodo_detalle", periodo_id=periodo_id))

    if impacta_stock:
        asegurar_conteo_admin(
            periodo, producto_nombre=producto_nombre, categoria=categoria,
            usuario=session["usuario"],
        )

    aj = AjusteInventario(
        periodo_id=periodo_id,
        cliente_id=cliente_id,
        producto_nombre=producto_nombre,
        usuario_admin=session["usuario"],
        cantidad_ajustada=cantidad,
        motivo=motivo,
        observacion=observacion,
        impacta_stock=impacta_stock,
    )
    db.session.add(aj)
    db.session.flush()
    cantidad_final = total_conteo_con_ajustes(periodo.id, producto_nombre)
    if impacta_stock:
        try:
            registrar_estado_operativo_admin(
                periodo, producto_nombre=producto_nombre, categoria=categoria,
                cantidad_final=cantidad_final, usuario=session["usuario"],
                detalle=f"Ajuste administrativo {cantidad:+g}: {motivo}. {observacion}".strip(),
            )
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "warning")
            return redirect(url_for("admin_periodo_detalle", periodo_id=periodo_id))
    auditoria_pendiente = _marcar_auditoria_por_cambio_admin(
        periodo,
        "Ajuste administrativo agregado"
        + (" con impacto en stock" if impacta_stock else " sin impacto en stock"),
    )
    db.session.commit()
    impacto = f" Stock final: {cantidad_final:g} {unidad_ajuste}." if impacta_stock else " Sin impacto en stock."
    flash(f"Ajuste de {cantidad:+g} {unidad_ajuste} agregado a '{producto_nombre}'.{impacto}", "success")
    if auditoria_pendiente:
        flash(
            "La auditoría quedó desactualizada. Sigue el aviso rojo y pulsa "
            "«Re-ejecutar auditoría» para aplicar los nuevos datos.",
            "warning",
        )
    return redirect(url_for("admin_periodo_detalle", periodo_id=periodo_id))


@app.route("/admin/periodos/<int:periodo_id>/excel/importar", methods=["POST"])
@login_required(rol="administrador")
def admin_periodo_excel_importar(periodo_id):
    cliente_id = get_cliente_filtro()
    periodo = db.session.get(InventarioPeriodo, periodo_id)
    if not periodo or periodo.cliente_id != cliente_id:
        abort(404)

    archivo = request.files.get("archivo_excel")
    if not archivo or not archivo.filename:
        flash("Seleccioná un archivo Excel.", "warning")
        return redirect(url_for("admin_periodo_detalle", periodo_id=periodo_id))

    contenido = archivo.read()
    try:
        ei, advertencias = importar_excel_transaccional(
            periodo_id=periodo_id,
            cliente_id=cliente_id,
            usuario=session["usuario"],
            filename=archivo.filename,
            contenido=contenido,
        )
        if advertencias:
            for w in advertencias[:5]:
                flash(w, "warning")
            if len(advertencias) > 5:
                flash(f"... y {len(advertencias) - 5} advertencia(s) más.", "warning")
        flash(
            f"Excel importado: {ei.id} | Productos nuevos sin vincular: {ei.productos_nuevos}",
            "success" if ei.productos_nuevos == 0 else "warning",
        )
    except Exception as exc:
        flash(f"Error al importar: {exc}", "error")

    return redirect(url_for("admin_periodo_detalle", periodo_id=periodo_id))


@app.route("/admin/periodos/<int:periodo_id>/excel/<int:excel_id>/vincular", methods=["POST"])
@login_required(rol="administrador")
def admin_excel_vincular(periodo_id, excel_id):
    """Vincula manualmente una fila del Excel con un producto interno."""
    cliente_id = get_cliente_filtro()
    excel = ExcelImportado.query.filter_by(
        id=excel_id,
        periodo_id=periodo_id,
        cliente_id=cliente_id,
    ).first()
    if excel is None:
        abort(404)
    ed = db.session.get(ExcelDetalle, int(request.form.get("detalle_id", 0)))
    if ed is None or ed.excel_id != excel.id:
        abort(404)
    nombre_interno = (request.form.get("nombre_interno") or "").strip()
    if ed and nombre_interno:
        ed.producto_nombre_interno = nombre_interno
        # Resolver producto_id por nombre para mantener FK estable
        p = Producto.query.filter(
            db.func.lower(Producto.nombre) == nombre_interno.lower()
        ).first()
        if p:
            ed.producto_id = p.id
            ed.estado_vinculacion = "vinculado"
            if ed.articulo and not p.codigo_articulo:
                p.codigo_articulo = ed.articulo
        else:
            ed.estado_vinculacion = "pendiente"
        db.session.commit()
        flash(f"'{ed.artdescrip}' vinculado a '{nombre_interno}'.", "success")
    return redirect(url_for("admin_periodo_detalle", periodo_id=periodo_id))


@app.route("/admin/periodos/<int:periodo_id>/auditoria/ejecutar", methods=["POST"])
@login_required(rol="administrador")
def admin_auditoria_ejecutar(periodo_id):
    cliente_id = get_cliente_filtro()
    periodo = db.session.get(InventarioPeriodo, periodo_id)
    if not periodo or periodo.cliente_id != cliente_id:
        abort(404)

    if periodo.estado not in ("Cerrado", "Conciliado", "Auditado"):
        flash(
            "Primero debes cerrar el período. Importar el Excel no cierra la carga de los empleados.",
            "warning",
        )
        return redirect(url_for("admin_periodo_detalle", periodo_id=periodo_id))

    # Bloquear si hay productos sin vincular (a menos que se fuerce)
    forzar = request.form.get("forzar")
    excel_imp = (ExcelImportado.query.filter_by(periodo_id=periodo_id)
                 .order_by(ExcelImportado.id.desc()).first())
    descartados = 0
    if excel_imp:
        # Las filas confirmadas como "sin producto" no son cambios aplicables
        # del catálogo y deben quedar fuera de Auditoría, tal como informa la
        # pantalla de sincronización. Esto también corrige importaciones hechas
        # antes de que existiera el descarte automático.
        from core.excel_importer import descartar_detalles_sin_producto
        descartados = descartar_detalles_sin_producto(excel_imp.id)
        if descartados:
            db.session.flush()
    if excel_imp and excel_imp.estado_validacion == "pendiente_vinculacion" and not forzar:
        if descartados:
            db.session.commit()
        flash(
            f"{excel_imp.productos_nuevos} producto(s) del Excel sin vincular. "
            f"Vinculálos primero o usá \"Forzar\" para ejecutar auditoría incompleta.",
            "warning",
        )
        return redirect(url_for("admin_periodo_detalle", periodo_id=periodo_id))

    from core.factura_ocr import FacturaError
    try:
        resultados = ejecutar_auditoria(periodo)
        # Deja listo el informe completo para todas las consultas posteriores a Nexa.
        refresh_period_report_markdown(periodo)
        db.session.commit()
        faltantes = sum(1 for r in resultados if r.tipo_diferencia == "faltante")
        aviso_incompleta = " (auditoría incompleta: hay productos sin vincular)" if forzar else ""
        flash(
            f"Auditoría ejecutada: {len(resultados)} producto(s) evaluados, "
            f"{faltantes} con faltante{aviso_incompleta}.",
            "success" if not forzar else "warning",
        )
    except FacturaError as exc:
        db.session.rollback()
        flash(
            f"Auditoría no ejecutada: {exc} Completa el procesamiento de las facturas antes de continuar.",
            "warning",
        )
    except Exception as exc:
        db.session.rollback()
        flash(f"Error en el motor de auditoría: {exc}", "error")

    return redirect(url_for("admin_auditoria", periodo_id=periodo_id))


@app.route("/admin/periodos/<int:periodo_id>/auditoria")
@login_required(rol="administrador")
def admin_auditoria(periodo_id):
    cliente_id = get_cliente_filtro()
    periodo = db.session.get(InventarioPeriodo, periodo_id)
    if not periodo or periodo.cliente_id != cliente_id:
        abort(404)

    filtro = request.args.get("filtro", "todos")
    if filtro not in {"todos", "faltante", "sobrante", "compensado", "critico", "pendiente", "sin_datos"}:
        filtro = "todos"

    # Se envía el conjunto completo para combinar filtros en pantalla sin
    # alterar los totales reales del período.
    resultados = AuditoriaResultado.query.filter_by(periodo_id=periodo_id).filter(
        AuditoriaResultado.estado_auditoria != "Archivado"
    ).order_by(
        AuditoriaResultado.severidad.desc(),
        AuditoriaResultado.impacto.desc(),
    ).all()
    # Prioridad visual: primero cualquier diferencia matemática distinta de cero,
    # incluso si el estado defensivo es "Sin datos"; luego los productos sin diferencia.
    # Dentro de cada grupo se muestran primero las diferencias de mayor magnitud.
    resultados.sort(key=lambda item: (
        abs(float(item.diferencia or 0)) < 0.01,
        -abs(float(item.diferencia or 0)),
        str(item.producto_nombre or "").casefold(),
    ))
    for resultado in resultados:
        resultado.explicacion_causal = explicar_causa_diferencia(resultado)
    facturas_pendientes_auditoria = (
        FacturaCompraDetalle.query.join(FacturaCompra)
        .filter(
            FacturaCompra.periodo_id == periodo_id,
            FacturaCompra.cliente_id == cliente_id,
            ~FacturaCompraDetalle.estado_vinculacion.in_(("vinculado", "aplicado", "fuera_rango")),
        )
        .count()
    )

    total_impacto = sum(r.impacto for r in resultados if r.tipo_diferencia == "faltante")
    resumen = {
        "todos": len(resultados),
        "faltante": sum(1 for r in resultados if r.tipo_diferencia == "faltante"),
        "sobrante": sum(1 for r in resultados if r.tipo_diferencia == "sobrante"),
        "compensado": sum(
            1 for r in resultados
            if r.tipo_diferencia == "compensado" or r.estado_auditoria == "Sin diferencia real"
        ),
        "critico": sum(1 for r in resultados if r.severidad == "Crítico"),
        "pendiente": sum(1 for r in resultados if r.estado_auditoria == "Pendiente"),
        "sin_datos": sum(1 for r in resultados if r.estado_auditoria == "Sin datos"),
    }
    categorias = sorted({r.categoria for r in resultados if r.categoria})
    from core.inventario import estado_sincronizacion_catalogo
    estado_actualizacion = estado_actualizacion_auditoria(
        periodo,
        catalogo_pendiente=estado_sincronizacion_catalogo(cliente_id)["total"] > 0,
    )
    ultima_ejecucion = estado_actualizacion["ultima_ejecucion"]
    causas_disponibles = [
        "Error de conteo", "Compra mal cargada", "Canje no registrado",
        "Producto vencido", "Merma o averiado", "Pendiente de revisión",
    ]
    return render_template(
        "admin_auditoria.html",
        periodo=periodo,
        tienda_nombre=_nombre_tienda_periodo(periodo),
        resultados=resultados,
        filtro=filtro,
        total_impacto=total_impacto,
        resumen=resumen,
        categorias=categorias,
        ultima_ejecucion=ultima_ejecucion,
        estado_actualizacion_auditoria=estado_actualizacion,
        facturas_pendientes_auditoria=facturas_pendientes_auditoria,
        causas_disponibles=causas_disponibles,
    )


def _nexa_conversacion_query(cliente_id):
    return AsistenteIAConversacion.query.filter_by(
        cliente_id=cliente_id,
        usuario=str(session.get("usuario") or ""),
    )


def _nexa_resolver_conversacion(cliente_id, payload, seccion, pregunta):
    conversation_id = payload.get("conversation_id")
    explicit_id = conversation_id not in (None, "")
    if not explicit_id:
        conversation_id = session.get("nexa_conversacion_id")
    if conversation_id not in (None, ""):
        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            abort(400)
        conversacion = _nexa_conversacion_query(cliente_id).filter_by(id=conversation_id).first()
        if conversacion is None and explicit_id:
            abort(404)
    else:
        conversacion = None
    if conversacion is None:
        conversacion = AsistenteIAConversacion(
            cliente_id=cliente_id,
            usuario=str(session.get("usuario") or ""),
            titulo=(pregunta.strip() or "Nueva conversación")[:120],
            seccion_inicial=seccion[:40],
        )
        db.session.add(conversacion)
        db.session.flush()
    session.pop("nexa_nueva_conversacion", None)
    session["nexa_conversacion_id"] = conversacion.id
    return conversacion


def _nexa_historial_modelo(conversacion, limite=6):
    consultas = (
        AsistenteIAConsulta.query
        .filter(
            AsistenteIAConsulta.conversacion_id == conversacion.id,
            AsistenteIAConsulta.estado.in_(("ok", "fallback")),
        )
        .order_by(AsistenteIAConsulta.id.desc())
        .limit(limite)
        .all()
    )
    consultas.reverse()
    return [
        {"question": item.pregunta, "answer": item.respuesta}
        for item in consultas
    ]


def _nexa_serializar_mensajes(conversacion, limite=20):
    consultas = (
        AsistenteIAConsulta.query
        .filter_by(conversacion_id=conversacion.id)
        .order_by(AsistenteIAConsulta.id.desc())
        .limit(limite)
        .all()
    )
    consultas.reverse()
    return [
        {
            "question": item.pregunta,
            "answer": item.respuesta,
            "status": item.estado,
            "created_at": item.creado.isoformat() if item.creado else None,
            "product_table": _nexa_tabla_producto_desde_json(item.contexto_json),
        }
        for item in consultas
    ]


def _nexa_serializar_conversacion(conversacion):
    return {
        "id": conversacion.id,
        "title": conversacion.titulo,
        "section": conversacion.seccion_inicial,
        "updated_at": (
            conversacion.actualizado.isoformat()
            if conversacion.actualizado else None
        ),
    }


def _nexa_tabla_producto_desde_json(contexto_json):
    """Extrae solo la tabla segura y estructurada que puede renderizar el cliente."""
    try:
        contexto = _json.loads(contexto_json or "{}")
    except (TypeError, ValueError, _json.JSONDecodeError):
        return None
    tabla = contexto.get("tabla_visual") if isinstance(contexto, dict) else None
    if not isinstance(tabla, dict):
        return None
    if not isinstance(tabla.get("columnas"), list) or not isinstance(tabla.get("fila"), dict):
        return None
    return tabla


def _nexa_guardar_consulta(
    *, conversacion, cliente_id, tienda_id, periodo, resultado, tipo,
    pregunta, contexto, respuesta,
):
    # El informe Markdown ya vive una sola vez en inventario_periodos. No se duplica
    # dentro de cada mensaje; aquí conservamos solo el contexto específico/trazable.
    contexto_trazable = {
        clave: valor for clave, valor in contexto.items()
        if clave != "informe_markdown"
    }
    if not respuesta.get("contextual", True):
        # Una cortesía queda en el hilo, pero al reabrirla no debe volver a
        # dibujar la tabla del producto como si hubiera sido una consulta.
        contexto_trazable.pop("tabla_visual", None)
    consulta = AsistenteIAConsulta(
        conversacion_id=conversacion.id,
        cliente_id=cliente_id,
        tienda_id=tienda_id or "ALL",
        periodo_id=periodo.id if periodo is not None else None,
        resultado_id=resultado.id if resultado is not None else None,
        usuario=str(session.get("usuario") or ""),
        tipo=tipo,
        pregunta=pregunta,
        respuesta=respuesta["answer"] or respuesta["error"],
        proveedor=respuesta["provider"],
        modelo=respuesta["model"],
        contexto_json=_json.dumps(contexto_trazable, ensure_ascii=False),
        estado=("fallback" if respuesta["fallback"] else
                ("ok" if respuesta["ok"] else "error")),
        error=respuesta["error"],
    )
    conversacion.actualizado = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.add(consulta)
    db.session.commit()
    return consulta


@app.route("/admin/asistente/conversaciones")
@login_required(rol="administrador")
def admin_nexa_conversaciones():
    cliente_id = get_cliente_filtro()
    conversaciones = (
        _nexa_conversacion_query(cliente_id)
        .order_by(AsistenteIAConversacion.actualizado.desc(), AsistenteIAConversacion.id.desc())
        .limit(3)
        .all()
    )
    active_id = session.get("nexa_conversacion_id")
    activa = None
    if active_id not in (None, ""):
        try:
            activa = _nexa_conversacion_query(cliente_id).filter_by(id=int(active_id)).first()
        except (TypeError, ValueError):
            activa = None
    if (
        activa is None
        and conversaciones
        and not session.get("nexa_nueva_conversacion")
    ):
        activa = conversaciones[0]
        session["nexa_conversacion_id"] = activa.id
    return jsonify(
        ok=True,
        active_conversation_id=activa.id if activa else None,
        conversations=[_nexa_serializar_conversacion(item) for item in conversaciones],
        messages=_nexa_serializar_mensajes(activa) if activa else [],
    )


@app.route("/admin/asistente/conversaciones/nueva", methods=["POST"])
@login_required(rol="administrador")
def admin_nexa_conversacion_nueva():
    session.pop("nexa_conversacion_id", None)
    session["nexa_nueva_conversacion"] = True
    return jsonify(ok=True, active_conversation_id=None, messages=[])


@app.route("/admin/asistente/conversaciones/<int:conversation_id>/seleccionar", methods=["POST"])
@login_required(rol="administrador")
def admin_nexa_conversacion_seleccionar(conversation_id):
    conversacion = _nexa_conversacion_query(get_cliente_filtro()).filter_by(
        id=conversation_id,
    ).first_or_404()
    session.pop("nexa_nueva_conversacion", None)
    session["nexa_conversacion_id"] = conversacion.id
    return jsonify(
        ok=True,
        active_conversation_id=conversacion.id,
        messages=_nexa_serializar_mensajes(conversacion),
    )


@app.route("/admin/periodos/<int:periodo_id>/asistente/consultar", methods=["POST"])
@login_required(rol="administrador")
def admin_asistente_consultar(periodo_id):
    """Nexa explica resultados existentes sin permitir que la IA los modifique."""
    cliente_id = get_cliente_filtro()
    periodo = db.session.get(InventarioPeriodo, periodo_id)
    if not periodo or periodo.cliente_id != cliente_id:
        abort(404)

    payload = request.get_json(silent=True) or {}
    pregunta = str(payload.get("pregunta") or "").strip()
    if not pregunta:
        return jsonify(ok=False, error="Escribe una consulta para Nexa."), 400
    if len(pregunta) > 1000:
        return jsonify(ok=False, error="La consulta no puede superar 1000 caracteres."), 400

    resultado = None
    resultado_id = payload.get("resultado_id")
    if resultado_id not in (None, ""):
        try:
            resultado_id = int(resultado_id)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="El resultado indicado no es válido."), 400
        resultado = db.session.get(AuditoriaResultado, resultado_id)
        if (
            not resultado
            or resultado.periodo_id != periodo.id
            or resultado.cliente_id != cliente_id
        ):
            abort(404)

    contexto = (
        build_product_context(periodo, resultado)
        if resultado is not None
        else build_period_context(periodo)
    )
    if resultado is not None:
        contexto["informe_markdown"] = (
            periodo.informe_ia_markdown or refresh_period_report_markdown(periodo)
        )
    if db.session.is_modified(periodo, include_collections=False):
        # Para períodos históricos sin instantánea, se guarda antes de esperar a la API.
        db.session.commit()
    conversacion = _nexa_resolver_conversacion(
        cliente_id,
        payload,
        "auditoria",
        pregunta,
    )
    respuesta = explain(
        pregunta,
        contexto,
        history=_nexa_historial_modelo(conversacion),
    )
    consulta = _nexa_guardar_consulta(
        conversacion=conversacion,
        cliente_id=cliente_id,
        tienda_id=periodo.tienda_id,
        periodo=periodo,
        resultado=resultado,
        tipo="producto" if resultado is not None else "periodo",
        pregunta=pregunta,
        contexto=contexto,
        respuesta=respuesta,
    )
    if not respuesta["ok"]:
        return jsonify(
            ok=False,
            error=respuesta["error"],
            provider=respuesta["provider"],
            model=respuesta["model"],
            product_table=(
                contexto.get("tabla_visual")
                if respuesta.get("contextual", True) else None
            ),
            consultation_id=consulta.id,
            conversation_id=conversacion.id,
            conversation=_nexa_serializar_conversacion(conversacion),
        ), 503
    return jsonify(
        ok=True,
        answer=respuesta["answer"],
        provider=respuesta["provider"],
        model=respuesta["model"],
        fallback=respuesta["fallback"],
        product_table=(
            contexto.get("tabla_visual")
            if respuesta.get("contextual", True) else None
        ),
        consultation_id=consulta.id,
        conversation_id=conversacion.id,
        conversation=_nexa_serializar_conversacion(conversacion),
    )


@app.route("/admin/asistente/consultar", methods=["POST"])
@login_required(rol="administrador")
def admin_nexa_consultar():
    """Nexa responde con contexto del apartado administrativo actual."""
    cliente_id = get_cliente_filtro()
    payload = request.get_json(silent=True) or {}
    pregunta = str(payload.get("pregunta") or "").strip()
    if not pregunta:
        return jsonify(ok=False, error="Escribe una consulta para Nexa."), 400
    if len(pregunta) > 1000:
        return jsonify(ok=False, error="La consulta no puede superar 1000 caracteres."), 400

    seccion = str(payload.get("seccion") or "resumen")
    if seccion not in NEXA_SECCIONES:
        seccion = "resumen"

    periodo = None
    periodo_id = payload.get("periodo_id")
    if periodo_id not in (None, ""):
        try:
            periodo_id = int(periodo_id)
        except (TypeError, ValueError):
            return jsonify(ok=False, error="El período indicado no es válido."), 400
        periodo = db.session.get(InventarioPeriodo, periodo_id)
        if periodo is None or periodo.cliente_id != cliente_id:
            abort(404)

    contexto = (
        build_period_context(periodo)
        if periodo is not None and seccion == "auditoria"
        else _nexa_contexto_seccion(seccion, cliente_id)
    )
    if periodo is not None and db.session.is_modified(periodo, include_collections=False):
        db.session.commit()
    conversacion = _nexa_resolver_conversacion(cliente_id, payload, seccion, pregunta)
    respuesta = explain(
        pregunta,
        contexto,
        history=_nexa_historial_modelo(conversacion),
    )
    consulta = _nexa_guardar_consulta(
        conversacion=conversacion,
        cliente_id=cliente_id,
        tienda_id=periodo.tienda_id if periodo is not None else "ALL",
        periodo=periodo,
        resultado=None,
        tipo="periodo" if periodo is not None and seccion == "auditoria" else "seccion",
        pregunta=pregunta,
        contexto=contexto,
        respuesta=respuesta,
    )

    if not respuesta["ok"]:
        return jsonify(
            ok=False,
            error=respuesta["error"],
            provider=respuesta["provider"],
            model=respuesta["model"],
            consultation_id=consulta.id,
            conversation_id=conversacion.id,
            conversation=_nexa_serializar_conversacion(conversacion),
        ), 503
    return jsonify(
        ok=True,
        answer=respuesta["answer"],
        provider=respuesta["provider"],
        model=respuesta["model"],
        fallback=respuesta["fallback"],
        consultation_id=consulta.id,
        conversation_id=conversacion.id,
        conversation=_nexa_serializar_conversacion(conversacion),
    )


@app.route("/admin/periodos/<int:periodo_id>/justificar/<int:resultado_id>", methods=["POST"])
@login_required(rol="administrador")
def admin_justificar(periodo_id, resultado_id):
    cliente_id = get_cliente_filtro()
    resultado = db.session.get(AuditoriaResultado, resultado_id)
    if (
        not resultado
        or resultado.cliente_id != cliente_id
        or resultado.periodo_id != periodo_id
    ):
        abort(404)

    causa = (request.form.get("causa") or "").strip()
    cantidad = float(request.form.get("cantidad_justificada", 0) or 0)
    observacion = (request.form.get("observacion") or "").strip()

    if not causa:
        flash("Seleccioná una causa.", "warning")
        return redirect(url_for("admin_auditoria", periodo_id=periodo_id))
    if causa == "Canje no registrado" and not observacion:
        flash("Para 'Canje no registrado' la observación es obligatoria.", "warning")
        return redirect(url_for("admin_auditoria", periodo_id=periodo_id))

    importe = cantidad * (resultado.costo_unitario or 0)
    j = Justificacion(
        resultado_id=resultado_id,
        cliente_id=cliente_id,
        causa=causa,
        cantidad_justificada=cantidad,
        importe_justificado=importe,
        observacion=observacion,
        usuario=session["usuario"],
    )
    db.session.add(j)
    resultado.estado_auditoria = "Justificado"
    # Si ya no quedan diferencias Pendientes ni Sugeridas, el período pasa a Auditado
    pendientes = AuditoriaResultado.query.filter(
        AuditoriaResultado.periodo_id == periodo_id,
        AuditoriaResultado.estado_auditoria.in_(["Pendiente", "Sugerido"]),
        AuditoriaResultado.tipo_diferencia != "correcto",
    ).count()
    if pendientes == 0:
        periodo_obj = db.session.get(InventarioPeriodo, periodo_id)
        if periodo_obj and periodo_obj.estado == "Conciliado":
            periodo_obj.estado = "Auditado"
    else:
        periodo_obj = db.session.get(InventarioPeriodo, periodo_id)
    if periodo_obj is not None:
        db.session.flush()
        refresh_period_report_markdown(periodo_obj)
    db.session.commit()
    flash("Justificación guardada.", "success")
    return redirect(url_for("admin_auditoria", periodo_id=periodo_id))


@app.route("/admin/periodos/<int:periodo_id>/revisar/<int:resultado_id>", methods=["POST"])
@login_required(rol="administrador")
def admin_marcar_revisado(periodo_id, resultado_id):
    """Marca un resultado como Revisado sin agregar justificación formal."""
    cliente_id = get_cliente_filtro()
    resultado = db.session.get(AuditoriaResultado, resultado_id)
    if (
        resultado
        and resultado.cliente_id == cliente_id
        and resultado.periodo_id == periodo_id
    ):
        marcar_resultado_revisado(resultado, session["usuario"])
        periodo = db.session.get(InventarioPeriodo, periodo_id)
        if periodo is None:
            abort(404)
        db.session.flush()
        refresh_period_report_markdown(periodo)
        db.session.commit()
        flash("Marcado como revisado.", "success")
    return redirect(url_for("admin_auditoria", periodo_id=periodo_id))


@app.route("/admin/periodos/<int:periodo_id>/reporte")
@login_required(rol="administrador")
def admin_reporte_gerencial(periodo_id):
    cliente_id = get_cliente_filtro()
    periodo = db.session.get(InventarioPeriodo, periodo_id)
    if not periodo or periodo.cliente_id != cliente_id:
        abort(404)
    ctx = build_reporte_gerencial(periodo)
    ctx["tienda_nombre"] = _nombre_tienda_periodo(periodo)
    return render_template("admin_reporte_gerencial.html", **ctx)


@app.route("/admin/periodos/<int:periodo_id>/exportar")
@login_required(rol="administrador")
def admin_auditoria_exportar(periodo_id):
    """Exporta el resultado de auditoría a Excel con todas las columnas definidas."""
    cliente_id = get_cliente_filtro()
    periodo = db.session.get(InventarioPeriodo, periodo_id)
    if not periodo or periodo.cliente_id != cliente_id:
        abort(404)

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        flash("openpyxl no está instalado. Ejecutá: pip install openpyxl", "error")
        return redirect(url_for("admin_auditoria", periodo_id=periodo_id))

    resultados = (AuditoriaResultado.query.filter_by(periodo_id=periodo_id)
                  .filter(AuditoriaResultado.estado_auditoria != "Archivado")
                  .order_by(AuditoriaResultado.impacto.desc()).all())

    wb = openpyxl.Workbook()
    ws = wb.active
    if ws is None:
        ws = wb.create_sheet()
    ws.title = f"Auditoría Inv.{periodo.numero}"

    HEADERS = [
        "Inventario", "Fecha Desde", "Fecha Hasta",
        "Código Producto", "Producto", "Categoría",
        "Stock Inicial Anterior", "Stock Inicial Excel", "Alerta Continuidad",
        "Compras", "Promedio Compras Histórico", "Factor Desvío Compra",
        "Ventas (inventario oficial)", "Ventas Delivery (info)", "Otros Ingresos", "Otras Salidas", "Stock Final oficial",
        "Stock Esperado Sistema", "Venta Teórica", "Conteo Empleado", "Ajuste Admin",
        "Stock Final Físico", "Diferencia (VR - VT)", "Tipo Diferencia", "Severidad",
        "Costo Unitario", "Fuente Costo", "Impacto",
        "Cantidad Merma", "Cantidad Vencida", "Diferencia Anterior Compensada",
        "Posible Causa Principal", "Evidencia", "Nivel de Confianza",
        "Estado Auditoría", "Usuario Conteo", "Usuario Ajuste", "Fecha Ajuste",
        "Justificación Manual", "Observación", "Usuario Justificación", "Fecha Justificación",
    ]

    header_fill = PatternFill("solid", fgColor="1E40AF")
    header_font = Font(bold=True, color="FFFFFF")
    faltante_fill = PatternFill("solid", fgColor="FEE2E2")
    sobrante_fill = PatternFill("solid", fgColor="DCFCE7")
    critico_fill = PatternFill("solid", fgColor="FCA5A5")

    ws.append(HEADERS)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}1"
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for r in resultados:
        # Justificación manual (última)
        jus = (Justificacion.query.filter_by(resultado_id=r.id)
               .order_by(Justificacion.id.desc()).first())

        row = [
            periodo.numero, periodo.fecha_desde, periodo.fecha_hasta,
            r.articulo_codigo, r.producto_nombre, r.categoria,
            r.stock_inicial_anterior, r.stock_inicial_excel,
            "SÍ" if r.alerta_continuidad else "No",
            r.compras, r.promedio_compras_historico, r.factor_desvio_compra,
            r.ventas, r.ventas_delivery, r.otros_ingresos, r.otras_salidas, r.stock_final_excel,
            r.stock_esperado, r.venta_teorica, r.conteo_empleado, r.ajuste_admin,
            r.conteo_final, r.diferencia, r.tipo_diferencia, r.severidad,
            r.costo_unitario, r.fuente_costo, r.impacto,
            r.cantidad_merma, r.cantidad_vencida, r.diferencia_anterior_compensada,
            r.causa_sugerida, r.evidencia, r.nivel_confianza,
            r.estado_auditoria, r.usuario_conteo, r.usuario_ajuste, r.fecha_ajuste,
            jus.causa if jus else "",
            jus.observacion if jus else "",
            jus.usuario if jus else "",
            str(jus.fecha.date()) if jus and jus.fecha else "",
        ]
        ws.append(row)
        data_row = ws.max_row
        fill = None
        if r.severidad == "Crítico":
            fill = critico_fill
        elif r.tipo_diferencia == "faltante":
            fill = faltante_fill
        elif r.tipo_diferencia == "sobrante":
            fill = sobrante_fill
        if fill:
            for cell in ws[data_row]:
                cell.fill = fill

    # Ajustar ancho de columnas
    for col in ws.columns:
        max_len = max((len(str(c.value)) for c in col if c.value), default=10)
        if col[0].column is None:
            continue
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = min(max_len + 4, 60)

    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return send_file(
        stream,
        as_attachment=True,
        download_name=f"auditoria_inv{periodo.numero}_{periodo.fecha_desde}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/admin/periodos/config/autoclose", methods=["GET", "POST"])
@login_required(rol="administrador")
def admin_config_autoclose():
    cliente_id = get_cliente_filtro()
    horas_actual = get_autoclose_horas(cliente_id)

    if request.method == "POST":
        try:
            horas = float(request.form.get("horas", 24))
            if horas < 1 or horas > 720:
                raise ValueError
        except (ValueError, TypeError):
            flash("Ingresá un valor válido mayor a 0.", "error")
            return redirect(url_for("admin_config_autoclose"))

        set_autoclose_horas(cliente_id, horas)
        flash(
            f"Auto-cierre configurado a {horas:g} hora(s) tras la fecha de fin del período.",
            "success",
        )
        return redirect(url_for("admin_periodos"))

    return render_template("admin_config_autoclose.html", horas_actual=horas_actual)


@app.route("/admin/productos-relacionados")
@login_required(rol="administrador")
def admin_productos_relacionados():
    cliente_id = get_cliente_filtro()
    relaciones = (ProductoRelacionado.query
                  .filter_by(cliente_id=cliente_id)
                  .order_by(ProductoRelacionado.producto_principal).all())
    productos = Producto.query.filter_by(visible_empleado=True).order_by(Producto.nombre).all()
    return render_template("admin_productos_relacionados.html",
                           relaciones=relaciones, productos=productos)


@app.route("/admin/productos-relacionados/crear", methods=["POST"])
@login_required(rol="administrador")
def admin_producto_relacionado_crear():
    cliente_id = get_cliente_filtro()
    principal = (request.form.get("producto_principal") or "").strip()
    relacionado = (request.form.get("producto_relacionado") or "").strip()
    try:
        ratio = float(request.form.get("ratio_esperado", 1))
        tolerancia = float(request.form.get("tolerancia", 0.1))
    except (ValueError, TypeError):
        flash("Ratio y tolerancia deben ser números.", "error")
        return redirect(url_for("admin_productos_relacionados"))

    productos_catalogo = (
        Producto.query
        .filter(Producto.visible_empleado.is_(True))
        .filter(db.func.lower(Producto.nombre).in_((principal.lower(), relacionado.lower())))
        .all()
    )
    productos_por_nombre = {producto.nombre.lower(): producto for producto in productos_catalogo}
    producto_principal = productos_por_nombre.get(principal.lower())
    producto_relacionado = productos_por_nombre.get(relacionado.lower())
    if producto_principal is None or producto_relacionado is None:
        flash("Seleccioná ambos productos desde el catálogo interno.", "warning")
        return redirect(url_for("admin_productos_relacionados"))

    principal = producto_principal.nombre
    relacionado = producto_relacionado.nombre
    if principal == relacionado:
        flash("Seleccioná dos productos distintos.", "warning")
        return redirect(url_for("admin_productos_relacionados"))

    existente = ProductoRelacionado.query.filter_by(
        cliente_id=cliente_id,
        producto_principal=principal,
        producto_relacionado=relacionado,
    ).first()
    if existente:
        flash("Ya existe esa relación.", "warning")
        return redirect(url_for("admin_productos_relacionados"))

    db.session.add(ProductoRelacionado(
        cliente_id=cliente_id,
        producto_principal=principal,
        producto_relacionado=relacionado,
        ratio_esperado=ratio,
        tolerancia=tolerancia,
        activo=True,
    ))
    db.session.commit()
    flash(f"Relación creada: {principal} → {relacionado} (ratio {ratio}x, tolerancia {tolerancia*100:.0f}%).", "success")
    return redirect(url_for("admin_productos_relacionados"))


@app.route("/admin/productos-relacionados/<int:rel_id>/toggle", methods=["POST"])
@login_required(rol="administrador")
def admin_producto_relacionado_toggle(rel_id):
    cliente_id = get_cliente_filtro()
    rel = db.session.get(ProductoRelacionado, rel_id)
    if rel and rel.cliente_id == cliente_id:
        rel.activo = not rel.activo
        db.session.commit()
        estado = "activada" if rel.activo else "desactivada"
        flash(f"Relación {estado}.", "success")
    return redirect(url_for("admin_productos_relacionados"))


@app.route("/admin/productos-relacionados/<int:rel_id>/eliminar", methods=["POST"])
@login_required(rol="administrador")
def admin_producto_relacionado_eliminar(rel_id):
    cliente_id = get_cliente_filtro()
    rel = db.session.get(ProductoRelacionado, rel_id)
    if rel and rel.cliente_id == cliente_id:
        db.session.delete(rel)
        db.session.commit()
        flash("Relación eliminada.", "info")
    return redirect(url_for("admin_productos_relacionados"))


with app.app_context():
    init_db()

# ── APScheduler: cierre automático de períodos ────────────────────────────────
# Werkzeug importa la aplicación una vez en el supervisor y otra en el proceso
# que atiende peticiones. Iniciar el scheduler en ambos deja una copia antigua
# viva después de cada recarga y puede ejecutar reglas de cierre desactualizadas.
_modo_desarrollo = os.getenv("FLASK_ENV", "development").lower() == "development"
_es_proceso_reloader = os.environ.get("WERKZEUG_RUN_MAIN", "").lower() == "true"
_debe_iniciar_scheduler = not _modo_desarrollo or _es_proceso_reloader
_scheduler = None
if _debe_iniciar_scheduler:
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler(daemon=True)
        _scheduler.add_job(
            func=job_autoclose_periodos,
            args=[app],
            trigger="interval",
            minutes=30,
            id="autoclose_periodos",
            replace_existing=True,
            misfire_grace_time=120,
        )
        _scheduler.start()
    except Exception as _e:
        import logging
        logging.getLogger(__name__).warning("APScheduler no pudo iniciarse: %s", _e)


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_ENV", "development").lower() == "development",
    )
