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
from datetime import datetime, date, timedelta
from functools import wraps
import secrets

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, send_file, jsonify, abort)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

from core.models import (db, Cliente, Tienda, Usuario, Producto, InventarioItem,
                    HistorialMovimiento, InventarioSnapshot, DeliveryProducto,
                    DeliveryVenta, StockThreshold, ProductoPrecio,
                    InventarioDescSnapshot, RegistroAveriado, RegistroVencimiento,
                    SincronizacionLog)
from core.catalogo import get_productos_db as catalogo_get_productos_db, activar_catalogo_pendiente_empleado
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"), override=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or "netward-dev-secret-change-me"
app.config["ASSET_VERSION"] = os.getenv("ASSET_VERSION", datetime.utcnow().strftime("%Y%m%d%H%M%S"))
# ── Seguridad de sesion ───────────────────────────────────────────────────────
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)  # Sesion expira en 8 h
app.config["SESSION_COOKIE_HTTPONLY"] = True    # JS no puede leer la cookie de sesion
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # Proteccion CSRF basica
# ─────────────────────────────────────────────────────────────────────────────
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", os.getenv("DATABASE_URL_EMPLEADO", "sqlite:///netward_empleado.db"))
app.config["SQLALCHEMY_BINDS"] = {
    "empleado": os.getenv("DATABASE_URL_EMPLEADO", "sqlite:///netward_empleado.db"),
    "administrador": os.getenv("DATABASE_URL_ADMIN", "sqlite:///netward_admin.db"),
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
app.register_blueprint(desc_bp)

# Filtro Jinja2 para parsear JSON en templates
import json as _json
import re as _re
app.jinja_env.filters["from_json"] = _json.loads

def _strip_unidad(nombre: str) -> str:
    """Quita variantes de 'x unidad' / 'x un.' del final del nombre (solo para display al empleado)."""
    return _re.sub(r"\s+x\s+un(?:idad|\.?)\s*$", "", str(nombre), flags=_re.IGNORECASE)

app.jinja_env.filters["strip_unidad"] = _strip_unidad


def set_database_bind(bind_name):
    """Selecciona la base de datos activa para la sesion actual."""
    db.session.remove()
    db.session.bind = bind_name
    return bind_name


def get_productos_db():
    """Devuelve el catálogo visible para empleado por categoria."""
    return catalogo_get_productos_db(include_hidden=False)


def get_active_bind():
    """Devuelve el bind de base de datos segun el rol activo.

    Centralizado: el administrador SIEMPRE lee del bind "empleado" para los
    datos de inventario (los empleados escriben ahi). Ya no es necesario
    llamar set_database_bind("empleado") manualmente en cada ruta admin.
    """
    return "empleado"


@app.before_request
def select_database_for_request():
    """Asigna la base de datos adecuada antes de cada peticion."""
    set_database_bind(get_active_bind())
    # Selector global de tienda del admin: persiste en sesion
    if session.get("rol") == "administrador":
        tienda_arg = request.args.get("tienda")
        if tienda_arg:
            cliente_id = get_cliente_filtro()
            tiendas_validas = {t.id for t in Tienda.query.filter_by(cliente_id=cliente_id, activa=True).all()}
            if tienda_arg == "ALL" or tienda_arg in tiendas_validas:
                session["admin_tienda_id"] = tienda_arg


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
    """Guarda un aviso local para /admin/precios sin usar flash global."""
    set_view_notice(session, "admin_precios_notice", message, category, tab=tab or "tab-0")


def get_cliente_filtro() -> str:
    """Cliente activo en sesión; usa C001 como fallback de compatibilidad."""
    return session.get("cliente_id", "C001")


def _add_column_if_missing(conn, table_name: str, column_sql: str, column_name: str):
    """Agrega una columna en SQLite solo si no existe."""
    cols = conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    existing = {c[1] for c in cols}
    if column_name not in existing:
        conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def ensure_multitenant_schema():
    """Migración liviana para multi-tenant sin depender de Alembic."""
    with db.engine.begin() as conn:
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
        _add_column_if_missing(conn, "registros_vencimiento",
                               "sinc_estado VARCHAR(20) NOT NULL DEFAULT 'pendiente'", "sinc_estado")
        _add_column_if_missing(conn, "usuarios",
                               "password_hash VARCHAR(256)", "password_hash")
        _add_column_if_missing(conn, "productos",
                       "visible_empleado BOOLEAN NOT NULL DEFAULT 1", "visible_empleado")

        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_tiendas_cliente_id ON tiendas(cliente_id)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_usuarios_cliente_id ON usuarios(cliente_id)")


# --------------------------------------------------------------------------- #
#  Inicializacion / seed de base de datos
# --------------------------------------------------------------------------- #
def init_db():
    """Crea las tablas e inserta los datos iniciales si la BD esta vacia."""
    # Usar checkfirst=True explícito para evitar errores con tablas ya existentes
    # (ocurre cuando SQLALCHEMY_BINDS apunta al mismo archivo que el default)
    with db.engine.begin() as conn:
        db.metadata.create_all(bind=conn, checkfirst=True)

    ensure_multitenant_schema()

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

    db.session.commit()


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
            if rol and session.get("rol") != rol:
                flash("No tienes permisos para acceder a esa seccion.", "error")
                return redirect(url_for("index"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


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
        "sync_pendientes": 0,
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
        except Exception:
            pass
    # Solo consultar notificaciones si hay sesion activa de administrador
    if session.get("rol") == "administrador" and session.get("usuario"):
        cliente_id = get_cliente_filtro()
        try:
            ctx["notif_averiados"]    = RegistroAveriado.query.filter_by(cliente_id=cliente_id, sinc_estado="sincronizado", revisado=False).count()
            ctx["notif_vencimientos"] = RegistroVencimiento.query.filter_by(cliente_id=cliente_id, sinc_estado="sincronizado", revisado=False).count()
        except Exception:
            ctx["notif_averiados"]    = 0
            ctx["notif_vencimientos"] = 0
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
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("empleado_inventario"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("usuario") or "").strip()
        contrasena = request.form.get("contrasena") or ""

        if not username or not contrasena:
            flash("Por favor, completa todos los campos.", "warning")
            return redirect(url_for("login"))

        usuario = Usuario.query.filter_by(username=username).first()
        if not usuario:
            flash(f"Usuario '{username}' no reconocido.", "error")
            return redirect(url_for("login"))

        if not usuario.password_hash or not check_password_hash(usuario.password_hash, contrasena):
            flash("Contrasena incorrecta.", "error")
            return redirect(url_for("login"))

        session.clear()          # Eliminar cualquier sesion anterior antes de crear una nueva
        session.permanent = True # Aplicar PERMANENT_SESSION_LIFETIME
        session["usuario"] = usuario.username
        session["cliente_id"] = usuario.cliente_id or "C001"
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

    usuarios = Usuario.query.order_by(Usuario.username).all()
    return render_template("login.html", usuarios=usuarios)


@app.route("/logout")
def logout():
    session.clear()
    flash("Sesion cerrada correctamente.", "success")
    return redirect(url_for("login"))


# --------------------------------------------------------------------------- #
#  Empleado - Inventario
# --------------------------------------------------------------------------- #
def get_carrito():
    return session.get("carrito", [])


def set_carrito(carrito):
    session["carrito"] = carrito
    session.modified = True


def _safe_inv_tab(tab_value):
    return tab_value if tab_value in CATEGORIAS else CATEGORIAS[0]


def _redirect_inventario_context(default_anchor="sec-carga"):
    active_tab = _safe_inv_tab(request.form.get("active_tab"))
    anchor = (request.form.get("anchor") or default_anchor).strip() or default_anchor
    return redirect(url_for("empleado_inventario", tab=active_tab) + f"#{anchor}")


@app.route("/empleado/inventario")
@login_required(rol="empleado")
def empleado_inventario():
    return render_template(
        "empleado_inventario.html",
        **empleado_service.build_empleado_inventario_context(
            active_tab=request.args.get("tab") or CATEGORIAS[0],
            carrito=get_carrito(),
            hoy=today_local_iso(),
        ),
    )


@app.route("/empleado/carrito/agregar", methods=["POST"])
@login_required(rol="empleado")
def carrito_agregar():
    categoria = request.form.get("categoria")
    producto = (request.form.get("producto") or "").strip()
    cantidad = request.form.get("cantidad", type=float) or 0
    ume = request.form.get("ume", "Unidad")
    tipo_inventario = request.form.get("tipo_inventario", "Diario")
    fecha = request.form.get("fecha", today_local_iso())
    detalle = request.form.get("detalle", "")

    if not producto:
        flash("Selecciona un producto antes de agregar.", "warning")
        return _redirect_inventario_context("sec-carga")

    if cantidad <= 0:
        flash("Ingresa una cantidad valida.", "warning")
        return _redirect_inventario_context("sec-carga")

    carrito = get_carrito()
    carrito, msg = empleado_service.add_carrito_item(
        carrito=carrito,
        categoria=categoria or CATEGORIAS[0],
        producto=producto,
        cantidad=cantidad,
        ume=ume,
        tipo_inventario=tipo_inventario,
        fecha=fecha,
        detalle=detalle,
    )
    set_carrito(carrito)
    flash(msg, "success")
    return _redirect_inventario_context("sec-carga")


@app.route("/empleado/carrito/eliminar/<int:idx>", methods=["POST"])
@login_required(rol="empleado")
def carrito_eliminar(idx):
    carrito = get_carrito()
    carrito, msg = empleado_service.remove_carrito_item(carrito, idx)
    if msg:
        set_carrito(carrito)
        flash(msg, "info")
    return _redirect_inventario_context("sec-carrito")


@app.route("/empleado/carrito/limpiar", methods=["POST"])
@login_required(rol="empleado")
def carrito_limpiar():
    set_carrito([])
    flash("Carrito limpiado.", "info")
    return _redirect_inventario_context("sec-carrito")


@app.route("/empleado/carrito/guardar", methods=["POST"])
@login_required(rol="empleado")
def carrito_guardar():
    carrito = get_carrito()
    if not carrito:
        flash("No hay productos en el carrito para guardar.", "warning")
        return _redirect_inventario_context("sec-carrito")

    tienda_id = session["tienda_id"]
    usuario   = session["usuario"]
    guardados = empleado_service.build_carrito_guardado(carrito, tienda_id, usuario)

    db.session.commit()
    set_carrito([])
    flash(f"{guardados} producto(s) guardado(s) exitosamente.", "success")
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
    tienda_id = session["tienda_id"]
    usuario   = session["usuario"]
    context = empleado_service.build_averiado_context(tienda_id=tienda_id)

    if request.method == "POST":
        categoria = request.form.get("categoria", "")
        producto  = (request.form.get("producto") or "").strip()
        cantidad_raw = (request.form.get("cantidad") or "").strip()
        cantidad_es_invalida = False
        try:
            cantidad = int(cantidad_raw)
            if str(cantidad) != cantidad_raw:
                cantidad_es_invalida = True
        except (TypeError, ValueError):
            cantidad = 0
            cantidad_es_invalida = True
        ume       = request.form.get("ume", "Unidad")
        detalle   = (request.form.get("detalle") or "").strip()
        fecha     = request.form.get("fecha", today_local_iso())

        if not producto:
            flash("Selecciona un producto.", "warning")
        elif cantidad_es_invalida:
            flash("La cantidad debe ser un número entero.", "warning")
        elif cantidad <= 0:
            flash("Ingresa una cantidad válida.", "warning")
        else:
            cu, desc = empleado_service.registrar_averiado(
                tienda_id=tienda_id, usuario=usuario,
                categoria=categoria, producto=producto,
                cantidad=cantidad, ume=ume,
                detalle=detalle, fecha=fecha,
            )
            db.session.commit()
            nombre_d = _re.sub(r"\s+x\s+un(?:idad|\.?)\s*$", "", producto, flags=_re.IGNORECASE)
            msg = f"Averiado registrado: {nombre_d} — {cantidad:g} {ume}"
            if desc:
                msg += f" → {desc}"
            msg += " (pendiente de sincronización)"
            flash(msg, "success")
            return redirect(url_for("empleado_averiado"))

    return render_template("empleado_averiado.html", **context)


@app.route("/empleado/averiado/<int:reg_id>/eliminar", methods=["POST"])
@login_required(rol="empleado")
def averiado_eliminar(reg_id):
    reg = db.session.get(RegistroAveriado, reg_id)
    if reg and reg.tienda_id == session["tienda_id"]:
        db.session.delete(reg)
        db.session.commit()
        flash("Registro eliminado.", "info")
    return redirect(url_for("empleado_averiado"))


# --------------------------------------------------------------------------- #
#  Empleado - Stock próximo a vencer
# --------------------------------------------------------------------------- #
@app.route("/empleado/vencimiento", methods=["GET", "POST"])
@login_required(rol="empleado")
def empleado_vencimiento():
    tienda_id = session["tienda_id"]
    usuario   = session["usuario"]
    context = empleado_service.build_vencimiento_context(tienda_id=tienda_id)

    if request.method == "POST":
        categoria        = request.form.get("categoria", "")
        producto         = (request.form.get("producto") or "").strip()
        cantidad_raw     = (request.form.get("cantidad") or "").strip()
        cantidad_es_invalida = False
        try:
            cantidad = int(cantidad_raw)
            if str(cantidad) != cantidad_raw:
                cantidad_es_invalida = True
        except (TypeError, ValueError):
            cantidad = 0
            cantidad_es_invalida = True
        ume              = request.form.get("ume", "Unidad")
        fecha_venc       = (request.form.get("fecha_vencimiento") or "").strip()
        detalle          = (request.form.get("detalle") or "").strip()
        fecha            = request.form.get("fecha", today_local_iso())

        if not producto:
            flash("Selecciona un producto.", "warning")
        elif cantidad_es_invalida:
            flash("La cantidad debe ser un número entero.", "warning")
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
    return render_template("empleado_sincronizar.html",
                           **empleado_service.build_sincronizacion_context(cliente_id=cliente_id, tienda_id=tienda_id))


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
    next_url  = request.form.get("_next", url_for("empleado_inventario"))
    cliente_id = get_cliente_filtro()
    tienda_id = session["tienda_id"]
    usuario   = session["usuario"]
    resumen = empleado_service.procesar_sincronizacion(cliente_id=cliente_id, tienda_id=tienda_id, usuario=usuario, accion=accion)
    if accion == "enviar_recibir":
        flash((
            f"Sincronización completada: {resumen['n_total']} registro(s) enviado(s) "
            f"(Inventario: {resumen['n_inv']}, Averiados: {resumen['n_aver']}, Vencimientos: {resumen['n_venc']}) "
            f"y catálogo actualizado ({resumen['catalogo_actualizado']} producto(s))."
        ), "success")
    else:
        flash(
            f"Datos enviados: {resumen['n_total']} registro(s) (Inventario: {resumen['n_inv']}, Averiados: {resumen['n_aver']}, Vencimientos: {resumen['n_venc']}).",
            "success",
        )
    db.session.commit()
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
    delta = datetime.utcnow() - dt
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
    active_tab = request.args.get("tab") or "tab-0"
    if request.method == "POST":
        active_tab = request.form.get("active_tab") or "tab-0"
        ids = request.form.getlist("ids")
        for pid in ids:
            try:
                pid_int = int(pid)
            except ValueError:
                continue
            producto = db.session.get(Producto, pid_int)
            if producto is None:
                continue
            precio_val = request.form.get(f"precio_{pid}") or None
            caja_val = request.form.get(f"caja_{pid}") or None
            bulto_val = request.form.get(f"bulto_{pid}") or None
            try:
                precio_val = float(str(precio_val).replace(".", "").replace(",", ".")) if precio_val else None
                caja_val = float(caja_val) if caja_val else None
                bulto_val = float(bulto_val) if bulto_val else None
            except ValueError:
                continue
            rec = ProductoPrecio.query.filter_by(producto_nombre=producto.nombre).first()
            if rec is None:
                rec = ProductoPrecio(producto_nombre=producto.nombre, categoria=producto.categoria)
                db.session.add(rec)
            rec.precio = precio_val
            if producto.categoria in ("Impulsivo", "Extras"):
                rec.unidades_por_caja = caja_val
                rec.unidades_por_bulto = bulto_val
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

    total_prod = Producto.query.count()
    con_precio = sum(
        1 for p in Producto.query.all()
        if precios_map.get(p.nombre) and precios_map[p.nombre].precio
    )
    porcentaje = round(con_precio / total_prod * 100, 1) if total_prod else 0

    # Valor estimado calculable con los precios actuales
    precios = _precios_lookup()
    valor_estimado = 0.0
    for i in _items_sincronizados("ALL"):
        pp = precios.get(i.producto.strip().lower())
        if pp and pp.precio:
            valor_estimado += (i.cantidad or 0) * pp.precio

    return render_template("admin_precios.html",
                           productos_por_cat=productos_por_cat,
                           categorias=CATEGORIAS,
                           precios_map=precios_map,
                           con_precio=con_precio, total_prod=total_prod,
                           porcentaje=porcentaje, valor_estimado=valor_estimado,
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


# --------------------------------------------------------------------------- #
#  Admin - Alertas centralizadas
# --------------------------------------------------------------------------- #
@app.route("/admin/alertas")
@login_required(rol="administrador")
def admin_alertas():
    cliente_id = get_cliente_filtro()
    tienda_sel = get_tienda_filtro()
    tiendas_map = {t.id: t.nombre for t in Tienda.query.filter_by(cliente_id=cliente_id).all()}
    thresholds = get_thresholds()

    # Stock bajo (nivel critico segun StockThreshold)
    stock_bajo = []
    for i in _items_sincronizados(tienda_sel):
        nivel, etiqueta = stock_status(i.producto, i.cantidad or 0, thresholds)
        if nivel == "critico":
            stock_bajo.append({
                "producto": i.producto, "categoria": i.categoria,
                "cantidad": i.cantidad, "etiqueta": etiqueta,
                "tienda": tiendas_map.get(i.tienda_id, i.tienda_id),
            })

    # Proximos a vencer (<= 15 dias)
    q_venc = RegistroVencimiento.query.filter_by(cliente_id=cliente_id, sinc_estado="sincronizado")
    if tienda_sel != "ALL":
        q_venc = q_venc.filter_by(tienda_id=tienda_sel)
    por_vencer = []
    for r in q_venc.all():
        dias = _dias_hasta(r.fecha_vencimiento)
        if dias is not None and dias <= 15:
            por_vencer.append({
                "producto": r.producto, "categoria": r.categoria,
                "tienda": tiendas_map.get(r.tienda_id, r.tienda_id),
                "fecha_vencimiento": r.fecha_vencimiento, "dias": dias,
                "cantidad": r.cantidad, "ume": r.ume,
                "nivel": "danger" if dias < 7 else "warning",
            })
    por_vencer.sort(key=lambda x: x["dias"])

    # Averiados no revisados
    q_aver = RegistroAveriado.query.filter_by(cliente_id=cliente_id, sinc_estado="sincronizado", revisado=False)
    if tienda_sel != "ALL":
        q_aver = q_aver.filter_by(tienda_id=tienda_sel)
    averiados = [{
        "producto": r.producto, "categoria": r.categoria,
        "tienda": tiendas_map.get(r.tienda_id, r.tienda_id),
        "cantidad": r.cantidad, "ume": r.ume, "fecha": r.fecha,
        "detalle": r.detalle,
    } for r in q_aver.order_by(RegistroAveriado.creado.desc()).all()]

    return render_template("admin_alertas.html",
                           stock_bajo=stock_bajo, por_vencer=por_vencer,
                           averiados=averiados)


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
    for t in tiendas:
        ultimo_envio = (SincronizacionLog.query
                        .filter_by(cliente_id=cliente_id, tienda_id=t.id, tipo="envio")
                        .order_by(SincronizacionLog.timestamp.desc()).first())
        ultima_recepcion = (SincronizacionLog.query
                            .filter_by(cliente_id=cliente_id, tienda_id=t.id, tipo="recepcion")
                            .order_by(SincronizacionLog.timestamp.desc()).first())
        pendientes = InventarioItem.query.filter_by(
            cliente_id=cliente_id, tienda_id=t.id, sinc_estado="pendiente").count()
        total_pendientes += pendientes
        filas.append({
            "tienda": t.nombre, "tienda_id": t.id, "activa": t.activa,
            "ultimo_envio": format_utc_naive_to_local(ultimo_envio.timestamp) if ultimo_envio else None,
            "ultima_recepcion": format_utc_naive_to_local(ultima_recepcion.timestamp) if ultima_recepcion else None,
            "pendientes": pendientes,
        })
    return render_template("admin_sync_estado.html", filas=filas,
                           total_pendientes=total_pendientes,
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
    cliente_id = get_cliente_filtro()
    tiendas = Tienda.query.filter_by(cliente_id=cliente_id).all()
    default = next((t.id for t in tiendas if t.es_default), None)
    local_notice = session.pop("admin_config_notice", None)
    active_tab = _safe_config_tab(
        request.args.get("tab")
        or ((local_notice or {}).get("tab"))
        or "tab-impulsivo"
    )
    productos_impulsivo = Producto.query.filter_by(categoria="Impulsivo").order_by(Producto.nombre).all()
    productos_extras = Producto.query.filter_by(categoria="Extras").order_by(Producto.nombre).all()
    productos_kilos = Producto.query.filter_by(categoria="Por Kilos").order_by(Producto.nombre).all()
    precios_map = {p.producto_nombre: p for p in ProductoPrecio.query.all()}
    return render_template("admin_configuracion.html",
                           tiendas=tiendas, default=default,
                           productos_impulsivo=productos_impulsivo,
                           productos_extras=productos_extras,
                           productos_kilos=productos_kilos,
                           precios_map=precios_map,
                           active_tab=active_tab,
                           local_notice=local_notice,
                           hide_global_flash=True)


@app.route("/admin/configuracion/precios", methods=["POST"])
@login_required(rol="administrador")
def producto_precio_guardar():
    ids = request.form.getlist("ids")
    for pid in ids:
        try:
            pid_int = int(pid)
        except ValueError:
            continue
        producto = db.session.get(Producto, pid_int)
        if producto is None or producto.categoria not in ("Impulsivo", "Extras"):
            continue
        precio_val = request.form.get(f"precio_{pid}") or None
        caja_val = request.form.get(f"caja_{pid}") or None
        bulto_val = request.form.get(f"bulto_{pid}") or None
        try:
            # precio llega sin puntos de miles (el JS los quita antes de submit)
            precio_val = int(precio_val) if precio_val else None
            caja_val = float(caja_val) if caja_val else None
            bulto_val = float(bulto_val) if bulto_val else None
        except ValueError:
            continue
        rec = ProductoPrecio.query.filter_by(producto_nombre=producto.nombre).first()
        if rec is None:
            rec = ProductoPrecio(producto_nombre=producto.nombre, categoria=producto.categoria)
            db.session.add(rec)
        rec.precio = precio_val
        rec.unidades_por_caja = caja_val
        rec.unidades_por_bulto = bulto_val
    db.session.commit()
    flash("Precios y cantidades actualizados correctamente.", "success")
    return redirect(url_for("admin_precios"))


@app.route("/admin/producto/crear", methods=["POST"])
@login_required(rol="administrador")
def producto_crear():
    nombre = (request.form.get("nombre") or "").strip()
    categoria = (request.form.get("categoria") or "").strip()
    active_tab = _safe_config_tab(request.form.get("active_tab"))
    if "active_tab" not in request.form and categoria in ("Impulsivo", "Extras", "Por Kilos"):
        active_tab = {
            "Impulsivo": "tab-impulsivo",
            "Extras": "tab-extras",
            "Por Kilos": "tab-kilos",
        }[categoria]

    if not nombre:
        _set_admin_config_notice("productos", "El nombre del producto es obligatorio.", "error", active_tab)
        return redirect(url_for("admin_configuracion", tab=active_tab) + "#sec-productos")
    if categoria not in ("Impulsivo", "Por Kilos", "Extras"):
        _set_admin_config_notice("productos", "Categoria no valida.", "error", active_tab)
        return redirect(url_for("admin_configuracion", tab=active_tab) + "#sec-productos")
    if Producto.query.filter_by(nombre=nombre, categoria=categoria).first():
        _set_admin_config_notice("productos", f"Ya existe '{nombre}' en {categoria}.", "warning", active_tab)
        return redirect(url_for("admin_configuracion", tab=active_tab) + "#sec-productos")
    db.session.add(Producto(nombre=nombre, categoria=categoria, visible_empleado=False))
    db.session.commit()
    _set_admin_config_notice("productos", f"Producto '{nombre}' agregado a {categoria}.", "success", active_tab)
    return redirect(url_for("admin_configuracion", tab=active_tab) + "#sec-productos")


@app.route("/admin/producto/<int:producto_id>/eliminar", methods=["POST"])
@login_required(rol="administrador")
def producto_eliminar(producto_id):
    active_tab = _safe_config_tab(request.form.get("active_tab"))
    producto = db.session.get(Producto, producto_id)
    if producto is None:
        abort(404)
    # Eliminar registro de precios asociado si existe
    precio_rec = ProductoPrecio.query.filter_by(producto_nombre=producto.nombre).first()
    if precio_rec:
        db.session.delete(precio_rec)
    nombre = producto.nombre
    db.session.delete(producto)
    db.session.commit()
    _set_admin_config_notice("productos", f"Producto '{nombre}' eliminado.", "info", active_tab)
    return redirect(url_for("admin_configuracion", tab=active_tab) + "#sec-productos")


@app.route("/admin/tienda/crear", methods=["POST"])
@login_required(rol="administrador")
def tienda_crear():
    cliente_id = get_cliente_filtro()
    nombre = (request.form.get("nombre") or "").strip()
    direccion = (request.form.get("direccion") or "").strip() or "Direccion no especificada"
    if not nombre:
        _set_admin_config_notice("tiendas", "El nombre de la tienda es obligatorio.", "error")
        return redirect(url_for("admin_configuracion") + "#sec-tiendas")

    ids = [int(t.id[1:]) for t in Tienda.query.filter_by(cliente_id=cliente_id).all() if t.id.startswith("T") and t.id[1:].isdigit()]
    nuevo_id = f"T{(max(ids) + 1) if ids else 1:03d}"
    db.session.add(Tienda(id=nuevo_id, cliente_id=cliente_id, nombre=nombre, direccion=direccion, activa=True))
    db.session.commit()
    _set_admin_config_notice("tiendas", f"Tienda creada con ID {nuevo_id}.", "success")
    return redirect(url_for("admin_configuracion") + "#sec-tiendas")


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
    return redirect(url_for("admin_configuracion") + "#sec-tiendas")


@app.route("/admin/tienda/<tienda_id>/default", methods=["POST"])
@login_required(rol="administrador")
def tienda_default(tienda_id):
    cliente_id = get_cliente_filtro()
    tiendas = Tienda.query.filter_by(cliente_id=cliente_id).all()
    for t in tiendas:
        t.es_default = (t.id == tienda_id)
    db.session.commit()
    _set_admin_config_notice("tiendas", "Tienda predeterminada actualizada.", "success")
    return redirect(url_for("admin_configuracion") + "#sec-tiendas")


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
    tienda_f  = request.args.get("tienda", "Todas")
    desde     = request.args.get("desde", date.today().replace(day=1).isoformat())
    hasta     = request.args.get("hasta", date.today().isoformat())
    tiendas   = Tienda.query.filter_by(cliente_id=cliente_id).all()
    local_notice = pop_view_notice(session, "admin_averiados_notice")

    # Al abrir la vista, se consideran vistas las notificaciones sincronizadas.
    RegistroAveriado.query.filter_by(
        cliente_id=cliente_id,
        sinc_estado="sincronizado",
        revisado=False,
    ).update({"revisado": True}, synchronize_session=False)
    db.session.commit()

    q = RegistroAveriado.query.filter(
        RegistroAveriado.cliente_id == cliente_id,
        RegistroAveriado.sinc_estado == "sincronizado",
        RegistroAveriado.fecha >= desde,
        RegistroAveriado.fecha <= hasta,
    )
    if tienda_f != "Todas":
        q = q.filter_by(tienda_id=tienda_f)
    registros = q.order_by(RegistroAveriado.creado.desc()).all()

    return render_template("admin_averiados.html",
                           registros=registros, tiendas=tiendas,
                           tienda_f=tienda_f, desde=desde, hasta=hasta,
                           local_notice=local_notice,
                           notif_averiados=0,
                           hide_global_flash=True)


@app.route("/admin/averiados/revisar", methods=["POST"])
@login_required(rol="administrador")
def admin_averiados_revisar():
    cliente_id = get_cliente_filtro()
    tienda_f  = request.form.get("tienda", "Todas")
    desde     = request.form.get("desde", date.today().replace(day=1).isoformat())
    hasta     = request.form.get("hasta", date.today().isoformat())

    q = RegistroAveriado.query.filter(
        RegistroAveriado.cliente_id == cliente_id,
        RegistroAveriado.sinc_estado == "sincronizado",
        RegistroAveriado.revisado.is_(False),
        RegistroAveriado.fecha >= desde,
        RegistroAveriado.fecha <= hasta,
    )
    if tienda_f != "Todas":
        q = q.filter(RegistroAveriado.tienda_id == tienda_f)

    revisados = q.update({"revisado": True}, synchronize_session=False)
    db.session.commit()
    set_view_notice(session, "admin_averiados_notice",
                    f"Registros marcados como revisados: {revisados}.", "success")
    return redirect(url_for("admin_averiados", tienda=tienda_f, desde=desde, hasta=hasta) + "#averiados-lista")


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


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_ENV", "development").lower() == "development",
    )
