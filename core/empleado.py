"""Lógica de negocio para funcionalidades de empleado."""
from __future__ import annotations

from collections import defaultdict
import json
from sqlalchemy import or_

from flask import session

from core.catalogo import get_productos_db, activar_catalogo_pendiente_empleado
from core.models import (
    db, InventarioItem, HistorialMovimiento, InventarioSnapshot,
    RegistroAveriado, RegistroVencimiento, ProductoPrecio, SincronizacionLog,
    DeliveryProducto, DeliveryVenta, InventarioPeriodo, ConteoDetalle,
    InventarioBorrador,
)
from core.seed_data import CATEGORIAS, TIPOS_INVENTARIO, OPCIONES_UME, ESTADOS_BALDE
from core.time_utils import today_local_iso, now_local_time_str, format_utc_naive_to_local


def _safe_inv_tab(tab_value):
    return tab_value if tab_value in CATEGORIAS else CATEGORIAS[0]


class ConflictoCarga(RuntimeError):
    """La versión que el empleado intentó guardar ya no es la vigente."""

    def __init__(self, producto, usuario, cantidad, version):
        super().__init__(f"{producto} fue cargado por {usuario}.")
        self.producto = producto
        self.usuario = usuario
        self.cantidad = float(cantidad or 0)
        self.version = int(version or 0)


def _version_borrador(borrador):
    actualizado = borrador.actualizado
    if actualizado:
        return -max(1, int(actualizado.timestamp() * 1_000_000))
    return -max(1, int(borrador.id or 1))


def _cargas_en_borradores(*, cliente_id, tienda_id, periodo_id, excluir_usuario=None):
    """Obtiene el borrador más reciente por producto entre empleados de la tienda."""
    query = InventarioBorrador.query.filter_by(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        periodo_id=periodo_id,
    )

    cargas = {}
    borradores = query.order_by(
        InventarioBorrador.actualizado.desc(),
        InventarioBorrador.id.desc(),
    ).all()
    for borrador in borradores:
        try:
            contenido = json.loads(borrador.contenido_json or "[]")
        except (TypeError, ValueError):
            continue
        if not isinstance(contenido, list):
            continue
        agrupado = defaultdict(float)
        for entrada in contenido:
            if not isinstance(entrada, dict):
                continue
            categoria = str(entrada.get("categoria") or "")
            producto = str(entrada.get("producto") or "")
            if not categoria or not producto:
                continue
            cantidad = entrada.get("cantidad_unidades", entrada.get("cantidad", 0))
            agrupado[(categoria, producto)] += float(cantidad or 0)
        for (categoria, producto), cantidad in agrupado.items():
            clave = (categoria, producto)
            if clave not in cargas:
                cargas[clave] = {
                    "producto": producto,
                    "categoria": categoria,
                    "cantidad": cantidad,
                    "usuario": borrador.usuario,
                    "version": _version_borrador(borrador),
                    "fue_sobreescrito": False,
                    "es_borrador": True,
                    "origen": "borrador",
                }
    if excluir_usuario:
        return {
            clave: carga
            for clave, carga in cargas.items()
            if carga["usuario"] != excluir_usuario
        }
    return cargas


def retirar_producto_de_otros_borradores(*, cliente_id, tienda_id, periodo_id,
                                         usuario, categoria, producto,
                                         version_esperada):
    """Retira una reserva borrador que otro empleado aceptó sobreescribir."""
    cargas = _cargas_en_borradores(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        periodo_id=periodo_id,
        excluir_usuario=usuario,
    )
    actual = cargas.get((categoria, producto))
    if not actual or actual["version"] != int(version_esperada or 0):
        return False

    borradores = InventarioBorrador.query.filter(
        InventarioBorrador.cliente_id == cliente_id,
        InventarioBorrador.tienda_id == tienda_id,
        InventarioBorrador.periodo_id == periodo_id,
        InventarioBorrador.usuario != usuario,
    ).all()
    for borrador in borradores:
        try:
            contenido = json.loads(borrador.contenido_json or "[]")
        except (TypeError, ValueError):
            continue
        restante = [
            entrada for entrada in contenido
            if not (
                isinstance(entrada, dict)
                and entrada.get("categoria") == categoria
                and entrada.get("producto") == producto
            )
        ]
        if len(restante) == len(contenido):
            continue
        if restante:
            borrador.contenido_json = json.dumps(restante, ensure_ascii=False)
        else:
            db.session.delete(borrador)
    return True


def obtener_carga_actual(*, cliente_id, tienda_id, periodo_id, categoria, producto,
                         excluir_usuario=None):
    """Devuelve la última carga válida del producto dentro del período."""
    borrador = _cargas_en_borradores(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        periodo_id=periodo_id,
        excluir_usuario=excluir_usuario,
    ).get((categoria, producto))
    if borrador:
        return borrador

    item = InventarioItem.query.filter_by(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        categoria=categoria,
        producto=producto,
    ).first()
    if item and int(item.periodo_id or 0) == int(periodo_id):
        return {
            "producto": producto,
            "categoria": categoria,
            "cantidad": float(item.cantidad or 0),
            "usuario": item.usuario_ultima_carga or "desconocido",
            "version": int(item.version or 1),
            "fue_sobreescrito": bool(item.fue_sobreescrito),
            "origen": "item",
        }

    conteo = ConteoDetalle.query.filter_by(
        periodo_id=periodo_id,
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        producto_nombre=producto,
    ).first()
    if conteo and conteo.fue_cargado:
        return {
            "producto": producto,
            "categoria": categoria,
            "cantidad": float(conteo.total_unidad_base or 0),
            "usuario": conteo.usuario or "desconocido",
            "version": int(conteo.version_ultima_carga or 1),
            "fue_sobreescrito": bool(conteo.fue_sobreescrito),
            "origen": "conteo",
        }
    return None


def listar_cargas_periodo(*, cliente_id, tienda_id, periodo_id):
    """Lista sin duplicar el estado visible que compartirán todos los empleados."""
    cargas = {}
    for conteo in ConteoDetalle.query.filter_by(
        periodo_id=periodo_id,
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        fue_cargado=True,
    ).all():
        cargas[(conteo.categoria, conteo.producto_nombre)] = {
            "producto": conteo.producto_nombre,
            "categoria": conteo.categoria,
            "cantidad": float(conteo.total_unidad_base or 0),
            "usuario": conteo.usuario,
            "version": int(conteo.version_ultima_carga or 1),
            "fue_sobreescrito": bool(conteo.fue_sobreescrito),
        }
    for item in InventarioItem.query.filter_by(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        periodo_id=periodo_id,
    ).all():
        cargas[(item.categoria, item.producto)] = {
            "producto": item.producto,
            "categoria": item.categoria,
            "cantidad": float(item.cantidad or 0),
            "usuario": item.usuario_ultima_carga,
            "version": int(item.version or 1),
            "fue_sobreescrito": bool(item.fue_sobreescrito),
            "es_borrador": False,
        }
    for clave, carga in _cargas_en_borradores(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        periodo_id=periodo_id,
    ).items():
        # Un borrador es la intención más reciente y debe ser visible, aunque
        # exista debajo un conteo previamente guardado del mismo producto.
        cargas[clave] = carga
    return sorted(cargas.values(), key=lambda c: (c["categoria"], c["producto"]))


def build_empleado_inventario_context(*, active_tab: str, carrito: list, hoy: str,
                                      cargas_existentes=None, conflicto_carga=None):
    return {
        "productos": get_productos_db(),
        "active_tab": _safe_inv_tab(active_tab),
        "categorias": CATEGORIAS,
        "tipos_inventario": TIPOS_INVENTARIO,
        "opciones_ume": OPCIONES_UME,
        "estados_balde": ESTADOS_BALDE,
        "carrito": carrito,
        "hoy": hoy,
        "cargas_existentes": cargas_existentes or [],
        "conflicto_carga": conflicto_carga,
        "hide_global_flash": True,
    }


def add_carrito_item(*, carrito: list, categoria: str, producto: str, cantidad: float,
                     ume: str, tipo_inventario: str, fecha: str, detalle: str,
                     version_esperada: int = 0,
                     confirmar_sobreescritura: bool = False):
    cantidad_unidades = cantidad
    factor = 1.0
    desc_conversion = ""
    if ume in ("Caja", "Bulto"):
        pp = ProductoPrecio.query.filter(
            db.func.lower(ProductoPrecio.producto_nombre) == producto.lower()
        ).first()
        if pp:
            u_caja = float(pp.unidades_por_caja or 0)
            u_bulto = float(pp.unidades_por_bulto or 0)
            if ume == "Caja" and u_caja > 0:
                factor = u_caja
                cantidad_unidades = cantidad * u_caja
                desc_conversion = f"{cantidad:g} Caja × {u_caja:g} unid/caja = {cantidad_unidades:g} unid."
            elif ume == "Bulto" and u_bulto > 0 and u_caja > 0:
                factor = u_bulto * u_caja
                cantidad_unidades = cantidad * u_bulto * u_caja
                desc_conversion = (
                    f"{cantidad:g} Bulto × {u_bulto:g} cajas/bulto "
                    f"× {u_caja:g} unid/caja = {cantidad_unidades:g} unid."
                )

    carrito = [i for i in carrito if not (
        i["categoria"] == categoria and i["producto"] == producto and i["ume"] == ume
    )]
    # El registro más reciente se muestra primero en el carrito.
    carrito.insert(0, {
        "categoria": categoria,
        "producto": producto,
        "cantidad": cantidad,
        "cantidad_unidades": cantidad_unidades,
        "ume": ume,
        "factor": factor,
        "desc_conversion": desc_conversion,
        "tipo_inventario": tipo_inventario,
        "fecha": fecha,
        "detalle": detalle,
        "hora": now_local_time_str(),
        "version_esperada": int(version_esperada or 0),
        "confirmar_sobreescritura": bool(confirmar_sobreescritura),
    })
    nombre_display = producto if ume == "Unidad" else __import__("re").sub(r"\s+x\s+un(?:idad|\.?|)\s*$", "", producto, flags=__import__("re").IGNORECASE)
    msg = f"{nombre_display} agregado ({cantidad:g} {ume})"
    if desc_conversion:
        msg += f" → {desc_conversion}"
    return carrito, msg


def remove_carrito_item(carrito: list, idx: int):
    if 0 <= idx < len(carrito):
        eliminado = carrito.pop(idx)
        return carrito, f"{eliminado['producto']} eliminado del carrito."
    return carrito, None


def _periodo_destino(cliente_id, tienda_id, periodo_id=None):
    if periodo_id:
        return db.session.get(InventarioPeriodo, int(periodo_id))
    seleccionado = session.get("empleado_periodo_id")
    if seleccionado:
        periodo = db.session.get(InventarioPeriodo, int(seleccionado))
        if periodo:
            return periodo
    return (
        InventarioPeriodo.query
        .filter_by(cliente_id=cliente_id, tienda_id=tienda_id)
        .filter(InventarioPeriodo.estado.in_(["Abierto", "Pendiente", "Cargado"]))
        .order_by(InventarioPeriodo.id.desc())
        .first()
    )


def build_carrito_guardado(carrito: list, tienda_id: str, usuario: str,
                           cliente_id: str | None = None,
                           periodo_id: int | None = None):
    if not carrito:
        return 0
    cliente_id = cliente_id or session.get("cliente_id", "C001")
    periodo = _periodo_destino(cliente_id, tienda_id, periodo_id)
    periodo_id = periodo.id if periodo else None
    fecha_snapshot = carrito[0].get("fecha") or today_local_iso()
    guardados = 0
    grupos = defaultdict(lambda: {"entradas": [], "total_unidades": 0.0})
    for entrada in carrito:
        key = (entrada["categoria"], entrada["producto"])
        grupos[key]["entradas"].append(entrada)
        grupos[key]["total_unidades"] += float(entrada.get("cantidad_unidades", entrada["cantidad"]) or 0)

    # Validar todo antes de escribir: cancelar un conflicto no deja cambios parciales.
    estados = {}
    for (categoria, producto), grupo in grupos.items():
        actual = obtener_carga_actual(
            cliente_id=cliente_id,
            tienda_id=tienda_id,
            periodo_id=periodo_id,
            categoria=categoria,
            producto=producto,
            excluir_usuario=usuario,
        ) if periodo_id else None
        primera = grupo["entradas"][0]
        esperada = int(primera.get("version_esperada", 0) or 0)
        confirmada = bool(primera.get("confirmar_sobreescritura", False))
        if actual:
            if esperada != actual["version"]:
                raise ConflictoCarga(producto, actual["usuario"], actual["cantidad"], actual["version"])
            if actual["usuario"] != usuario and not confirmada:
                raise ConflictoCarga(producto, actual["usuario"], actual["cantidad"], actual["version"])
            if actual.get("origen") == "borrador":
                retirado = retirar_producto_de_otros_borradores(
                    cliente_id=cliente_id,
                    tienda_id=tienda_id,
                    periodo_id=periodo_id,
                    usuario=usuario,
                    categoria=categoria,
                    producto=producto,
                    version_esperada=actual["version"],
                )
                if not retirado:
                    vigente = obtener_carga_actual(
                        cliente_id=cliente_id,
                        tienda_id=tienda_id,
                        periodo_id=periodo_id,
                        categoria=categoria,
                        producto=producto,
                        excluir_usuario=usuario,
                    ) or {"usuario": "otro empleado", "cantidad": 0, "version": 0}
                    raise ConflictoCarga(producto, vigente["usuario"], vigente["cantidad"], vigente["version"])
                actual = obtener_carga_actual(
                    cliente_id=cliente_id,
                    tienda_id=tienda_id,
                    periodo_id=periodo_id,
                    categoria=categoria,
                    producto=producto,
                    excluir_usuario=usuario,
                )
        elif esperada != 0:
            raise ConflictoCarga(producto, "otro empleado", 0, 0)
        estados[(categoria, producto)] = actual

    # Crear o actualizar snapshot ANTES de insertar historial (para tener su ID)
    snapshot = InventarioSnapshot.query.filter_by(
        fecha=fecha_snapshot, tienda_id=tienda_id, usuario=usuario).first()
    if snapshot:
        snapshot.total_items = len(grupos)
        snapshot.tipo_inventario = carrito[0].get("tipo_inventario", "Diario")
    else:
        snapshot = InventarioSnapshot(
            cliente_id=cliente_id,
            fecha=fecha_snapshot,
            tienda_id=tienda_id,
            usuario=usuario,
            tipo_inventario=carrito[0].get("tipo_inventario", "Diario"),
            total_items=len(grupos),
        )
        db.session.add(snapshot)
    db.session.flush()  # necesario para obtener snapshot.id antes de crear historial

    for (categoria, producto), grupo in grupos.items():
        cantidad_total = round(grupo["total_unidades"], 3)
        primera = grupo["entradas"][0]
        tipo_inv = primera["tipo_inventario"]
        fecha_prod = primera["fecha"]
        actual = estados[(categoria, producto)]
        item = InventarioItem.query.filter_by(
            cliente_id=cliente_id,
            tienda_id=tienda_id,
            categoria=categoria,
            producto=producto,
        ).first()
        if actual and item and actual.get("origen") == "item":
            version_nueva = actual["version"] + 1
            actualizados = (
                InventarioItem.query
                .filter(InventarioItem.id == item.id, InventarioItem.version == actual["version"])
                .update({
                    "cantidad": cantidad_total,
                    "ume": "Unidad",
                    "tipo_inventario": tipo_inv,
                    "fecha": fecha_prod,
                    "sinc_estado": "pendiente",
                    "periodo_id": periodo_id,
                    "usuario_ultima_carga": usuario,
                    "version": version_nueva,
                    "fue_sobreescrito": True,
                }, synchronize_session=False)
            )
            if actualizados != 1:
                db.session.expire_all()
                vigente = obtener_carga_actual(
                    cliente_id=cliente_id, tienda_id=tienda_id,
                    periodo_id=periodo_id, categoria=categoria, producto=producto,
                ) or {"usuario": "otro empleado", "cantidad": 0, "version": 0}
                raise ConflictoCarga(producto, vigente["usuario"], vigente["cantidad"], vigente["version"])
            tipo_movimiento = "sobreescritura"
            usuario_anterior = actual["usuario"]
            cantidad_anterior = actual["cantidad"]
        elif actual:
            version_nueva = actual["version"] + 1
            if item:
                item.cantidad = cantidad_total
                item.ume = "Unidad"
                item.tipo_inventario = tipo_inv
                item.fecha = fecha_prod
                item.sinc_estado = "pendiente"
                item.periodo_id = periodo_id
                item.usuario_ultima_carga = usuario
                item.version = version_nueva
                item.fue_sobreescrito = True
            else:
                db.session.add(InventarioItem(
                    cliente_id=cliente_id,
                    tienda_id=tienda_id, categoria=categoria, producto=producto,
                    cantidad=cantidad_total, ume="Unidad",
                    tipo_inventario=tipo_inv, fecha=fecha_prod,
                    sinc_estado="pendiente", periodo_id=periodo_id,
                    usuario_ultima_carga=usuario, version=version_nueva,
                    fue_sobreescrito=True))
            tipo_movimiento = "sobreescritura"
            usuario_anterior = actual["usuario"]
            cantidad_anterior = actual["cantidad"]
        else:
            version_nueva = 1
            if item:  # El mismo stock operativo provenía de otro período.
                item.cliente_id = cliente_id
                item.cantidad = cantidad_total
                item.ume = "Unidad"
                item.tipo_inventario = tipo_inv
                item.fecha = fecha_prod
                item.sinc_estado = "pendiente"
                item.periodo_id = periodo_id
                item.usuario_ultima_carga = usuario
                item.version = version_nueva
                item.fue_sobreescrito = False
            else:
                db.session.add(InventarioItem(
                    cliente_id=cliente_id,
                    tienda_id=tienda_id, categoria=categoria, producto=producto,
                    cantidad=cantidad_total, ume="Unidad",
                    tipo_inventario=tipo_inv, fecha=fecha_prod,
                    sinc_estado="pendiente", periodo_id=periodo_id,
                    usuario_ultima_carga=usuario, version=version_nueva,
                    fue_sobreescrito=False))
            tipo_movimiento = "original"
            usuario_anterior = ""
            cantidad_anterior = None

        detalles = [e.get("desc_conversion") or e.get("detalle", "") for e in grupo["entradas"]]
        db.session.add(HistorialMovimiento(
            fecha=fecha_prod,
            hora=primera["hora"],
            usuario=usuario,
            categoria=categoria,
            producto=producto,
            cantidad=cantidad_total,
            modo="Unidad",
            tipo_inventario=tipo_inv,
            detalle=" | ".join(d for d in detalles if d),
            tienda_id=tienda_id,
            cliente_id=cliente_id,
            snapshot_id=snapshot.id,
            periodo_id=periodo_id,
            tipo_movimiento=tipo_movimiento,
            usuario_anterior=usuario_anterior,
            cantidad_anterior=cantidad_anterior,
            version=version_nueva,
        ))
        guardados += 1

    snapshot.total_items = guardados
    return guardados


def build_averiado_context(*, tienda_id: str):
    return {
        "productos": get_productos_db(),
        "categorias": CATEGORIAS,
        "recientes": RegistroAveriado.query.filter_by(tienda_id=tienda_id).order_by(RegistroAveriado.creado.desc()).limit(30).all(),
        "hoy": today_local_iso(),
    }


def registrar_averiado(*, tienda_id: str, usuario: str, categoria: str, producto: str,
                       cantidad: int, ume: str, detalle: str, fecha: str):
    cu, desc = convertir_ume(producto, ume, cantidad)
    db.session.add(RegistroAveriado(
        cliente_id=session.get("cliente_id", "C001"),
        tienda_id=tienda_id, fecha=fecha,
        hora=now_local_time_str(),
        usuario=usuario, categoria=categoria,
        producto=producto, cantidad=cantidad,
        cantidad_unidades=cu, ume=ume,
        desc_conversion=desc, detalle=detalle,
        sinc_estado="pendiente",
    ))
    return cu, desc


def build_vencimiento_context(*, tienda_id: str):
    return {
        "productos": get_productos_db(),
        "categorias": CATEGORIAS,
        "recientes": RegistroVencimiento.query.filter_by(tienda_id=tienda_id).order_by(RegistroVencimiento.creado.desc()).limit(30).all(),
        "hoy": today_local_iso(),
    }


def registrar_vencimiento(*, tienda_id: str, usuario: str, categoria: str, producto: str,
                          cantidad: int, ume: str, fecha_vencimiento: str,
                          detalle: str, fecha: str):
    cu, desc = convertir_ume(producto, ume, cantidad)
    db.session.add(RegistroVencimiento(
        cliente_id=session.get("cliente_id", "C001"),
        tienda_id=tienda_id, fecha=fecha,
        hora=now_local_time_str(),
        usuario=usuario, categoria=categoria,
        producto=producto, cantidad=cantidad,
        cantidad_unidades=cu, ume=ume,
        desc_conversion=desc, fecha_vencimiento=fecha_vencimiento,
        detalle=detalle,
        sinc_estado="pendiente",
    ))
    return cu, desc


def _pendientes_inventario_usuario(cliente_id, tienda_id, usuario):
    return (
        InventarioItem.query
        .filter_by(cliente_id=cliente_id, tienda_id=tienda_id, sinc_estado="pendiente")
        .filter(or_(
            InventarioItem.usuario_ultima_carga == usuario,
            InventarioItem.usuario_ultima_carga == "",
            InventarioItem.usuario_ultima_carga.is_(None),
        ))
    )


def build_sincronizacion_context(*, cliente_id: str, tienda_id: str):
    usuario = session.get("usuario", "")
    pend_inv = _pendientes_inventario_usuario(cliente_id, tienda_id, usuario).count()
    pend_aver = RegistroAveriado.query.filter_by(cliente_id=cliente_id, tienda_id=tienda_id, usuario=usuario, sinc_estado="pendiente").count()
    pend_venc = RegistroVencimiento.query.filter_by(cliente_id=cliente_id, tienda_id=tienda_id, usuario=usuario, sinc_estado="pendiente").count()
    return {
        "pendientes": pend_inv + pend_aver + pend_venc,
        "pend_inv": pend_inv,
        "pend_aver": pend_aver,
        "pend_venc": pend_venc,
        "sync_ultimo_envio": sync_ultimo_envio_empleado(),
        "sync_ultima_recepcion": sync_ultima_recepcion_empleado(),
    }


def sync_ultimo_envio_empleado():
    u, t = session.get("usuario"), session.get("tienda_id", "")
    r = (SincronizacionLog.query
         .filter_by(usuario=u, tienda_id=t, tipo="envio")
         .order_by(SincronizacionLog.timestamp.desc()).first())
    return format_utc_naive_to_local(r.timestamp) if r else None


def sync_ultima_recepcion_empleado():
    u, t = session.get("usuario"), session.get("tienda_id", "")
    r = (SincronizacionLog.query
         .filter_by(usuario=u, tienda_id=t, tipo="recepcion")
         .order_by(SincronizacionLog.timestamp.desc()).first())
    return format_utc_naive_to_local(r.timestamp) if r else None


def procesar_sincronizacion(*, cliente_id: str, tienda_id: str, usuario: str, accion: str):
    db.session.add(SincronizacionLog(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        usuario=usuario,
        tipo="envio",
        accion=accion,
    ))

    pendientes = _pendientes_inventario_usuario(cliente_id, tienda_id, usuario).all()
    for item in pendientes:
        item.sinc_estado = "sincronizado"
    n_inv = len(pendientes)

    pend_aver = RegistroAveriado.query.filter_by(cliente_id=cliente_id, tienda_id=tienda_id, usuario=usuario, sinc_estado="pendiente").all()
    for reg in pend_aver:
        reg.sinc_estado = "sincronizado"
    n_aver = len(pend_aver)

    pend_venc = RegistroVencimiento.query.filter_by(cliente_id=cliente_id, tienda_id=tienda_id, usuario=usuario, sinc_estado="pendiente").all()
    for reg in pend_venc:
        reg.sinc_estado = "sincronizado"
    n_venc = len(pend_venc)

    n_total = n_inv + n_aver + n_venc
    catalogo_actualizado = 0
    if accion == "enviar_recibir":
        catalogo_actualizado = activar_catalogo_pendiente_empleado()
        db.session.add(SincronizacionLog(
            cliente_id=cliente_id,
            tienda_id=tienda_id,
            usuario=usuario,
            tipo="recepcion",
            accion=accion,
        ))
    return {
        "n_inv": n_inv,
        "n_aver": n_aver,
        "n_venc": n_venc,
        "n_total": n_total,
        "catalogo_actualizado": catalogo_actualizado,
    }


def build_historial_context(*, tienda_id: str, usuario: str):
    snapshots = InventarioSnapshot.query.filter_by(
        tienda_id=tienda_id, usuario=usuario
    ).order_by(InventarioSnapshot.fecha.desc(), InventarioSnapshot.id.desc()).all()

    selected_snapshot = snapshots[0] if snapshots else None
    detalle = []
    if selected_snapshot is not None:
        # Preferir FK directa; fallback por (tienda_id, usuario, fecha) para registros legacy
        detalle = (
            HistorialMovimiento.query
            .filter(
                (HistorialMovimiento.snapshot_id == selected_snapshot.id)
                | (
                    (HistorialMovimiento.snapshot_id.is_(None))
                    & (HistorialMovimiento.tienda_id == tienda_id)
                    & (HistorialMovimiento.usuario == usuario)
                    & (HistorialMovimiento.fecha == selected_snapshot.fecha)
                )
            )
            .order_by(HistorialMovimiento.categoria, HistorialMovimiento.producto)
            .all()
        )

    return {
        "snapshots": snapshots,
        "selected_snapshot": selected_snapshot,
        "detalle": detalle,
    }


def build_delivery_context(*, tienda_id: str):
    hoy = today_local_iso()
    activos = DeliveryProducto.query.filter_by(activo=True).all()
    ventas_hoy = DeliveryVenta.query.filter_by(
        tienda_id=tienda_id,
        fecha=hoy,
    ).all()
    total_hoy = sum(float(venta.total or 0) for venta in ventas_hoy)
    return {
        "hoy": hoy,
        "activos": activos,
        "ventas_hoy": ventas_hoy,
        "total_hoy": total_hoy,
        "total_dia": total_hoy,
    }


def registrar_venta_delivery(*, tienda_id: str, usuario: str, producto_id: int, cantidad: int, fecha: str):
    producto = db.session.get(DeliveryProducto, producto_id)
    if not producto:
        return None
    total = producto.precio * cantidad
    db.session.add(DeliveryVenta(
        cliente_id=session.get("cliente_id", "C001"),
        fecha=fecha,
        hora=now_local_time_str(),
        producto=producto.nombre,
        cantidad=cantidad,
        precio_unitario=producto.precio,
        total=total,
        usuario=usuario,
        tienda_id=tienda_id,
    ))
    return producto.nombre, total


def convertir_ume(producto: str, ume: str, cantidad: float):
    if ume not in ("Caja", "Bulto", "Tira"):
        return cantidad, ""
    pp = ProductoPrecio.query.filter(
        db.func.lower(ProductoPrecio.producto_nombre) == producto.strip().lower()
    ).first()
    if not pp:
        return cantidad, ""
    u_caja = float(pp.unidades_por_caja or 0)
    u_bulto = float(pp.unidades_por_bulto or 0)
    if ume == "Caja" and u_caja > 0:
        cu = cantidad * u_caja
        return cu, f"{cantidad:g} Caja × {u_caja:g} unid/caja = {cu:g} unid."
    if ume in ("Bulto", "Tira") and u_bulto > 0 and u_caja > 0:
        cu = cantidad * u_bulto * u_caja
        return cu, (f"{cantidad:g} {ume} × {u_bulto:g} cajas/{ume.lower()} "
                    f"× {u_caja:g} unid/caja = {cu:g} unid.")
    return cantidad, ""
