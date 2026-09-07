"""Lógica de negocio para funcionalidades de empleado."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from typing import Callable, Optional
from sqlalchemy import false, or_

from flask import session

from core.catalogo import (
    catalogo_pendiente_usuario,
    get_productos_db,
    identidad_producto,
    recibir_catalogo_usuario,
)
from core.models import (
    db, InventarioItem, HistorialMovimiento, InventarioSnapshot,
    RegistroAveriado, RegistroVencimiento, ProductoPrecio, SincronizacionLog,
    DeliveryProducto, DeliveryVenta, InventarioPeriodo, ConteoDetalle,
    InventarioBorrador, utc_now,
)
from core.seed_data import CATEGORIAS, TIPOS_INVENTARIO, OPCIONES_UME, ESTADOS_BALDE
from core.time_utils import today_local_iso, now_local_time_str, format_utc_naive_to_local


KG_POR_BALDE_LLENO = Decimal("7.800")
ESTADOS_BALDE_VALIDOS = {"Lleno", "Medio lleno", "Vacio"}


def _decimal_positivo(valor, etiqueta: str) -> Decimal:
    texto = str(valor or "").strip().replace(",", ".")
    try:
        numero = Decimal(texto)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{etiqueta} debe ser un número válido.") from exc
    if not numero.is_finite() or numero <= 0:
        raise ValueError(f"{etiqueta} debe ser mayor que cero.")
    if abs(numero.as_tuple().exponent) > 3:
        raise ValueError(f"{etiqueta} admite hasta 3 decimales.")
    return numero


def _entero_positivo(valor, etiqueta: str) -> int:
    numero = _decimal_positivo(valor, etiqueta)
    if numero != numero.to_integral_value():
        raise ValueError(f"{etiqueta} debe ser un número entero.")
    return int(numero)


def _kg_texto(valor: Decimal | float) -> str:
    return f"{Decimal(str(valor)).quantize(Decimal('0.001')):,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")


def normalizar_conteo_kilos(*, estado_balde: str, cantidad_baldes=None, peso_kg=None) -> dict:
    estado = str(estado_balde or "").strip()
    if estado not in ESTADOS_BALDE_VALIDOS:
        raise ValueError("Selecciona un estado de balde válido.")
    if estado == "Medio lleno":
        peso = _decimal_positivo(peso_kg, "El peso real")
        if str(cantidad_baldes or "").strip():
            raise ValueError("Para Medio lleno ingresa solo el peso real en kg.")
        return {
            "cantidad": float(peso), "cantidad_unidades": float(peso), "ume": "kg",
            "estado_balde": estado, "cantidad_baldes": None, "peso_kg": float(peso),
            "factor": 1.0,
            "desc_conversion": f"{_kg_texto(peso)} kg · balde medio lleno (peso real)",
        }

    baldes = _entero_positivo(cantidad_baldes, "La cantidad de baldes")
    if str(peso_kg or "").strip():
        raise ValueError(f"Para {estado} ingresa solo la cantidad de baldes.")
    total = KG_POR_BALDE_LLENO * baldes if estado == "Lleno" else Decimal("0")
    detalle = (
        f"{_kg_texto(total)} kg = {baldes} balde{'s' if baldes != 1 else ''} "
        f"lleno{'s' if baldes != 1 else ''} × {_kg_texto(KG_POR_BALDE_LLENO)} kg"
        if estado == "Lleno"
        else f"0,000 kg · {baldes} balde{'s' if baldes != 1 else ''} vacío{'s' if baldes != 1 else ''}"
    )
    return {
        "cantidad": float(total), "cantidad_unidades": float(total), "ume": "kg",
        "estado_balde": estado, "cantidad_baldes": baldes, "peso_kg": None,
        "factor": float(KG_POR_BALDE_LLENO) if estado == "Lleno" else 0.0,
        "desc_conversion": detalle,
    }


def normalizar_cantidad_categoria(categoria: str, cantidad_raw) -> tuple[float, str]:
    if categoria == "Por Kilos":
        return float(_decimal_positivo(cantidad_raw, "La cantidad en kg")), "kg"
    return float(_entero_positivo(cantidad_raw, "La cantidad")), "Unidad"


def normalizar_ajuste_categoria(categoria: str, cantidad_raw) -> tuple[float, str]:
    texto = str(cantidad_raw or "").strip().replace(",", ".")
    try:
        numero = Decimal(texto)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("La cantidad del ajuste debe ser un número válido.") from exc
    if not numero.is_finite():
        raise ValueError("La cantidad del ajuste debe ser finita.")
    if categoria == "Por Kilos":
        if abs(numero.as_tuple().exponent) > 3:
            raise ValueError("El ajuste en kg admite hasta 3 decimales.")
        return float(numero), "kg"
    if numero != numero.to_integral_value():
        raise ValueError("El ajuste debe ser entero para productos por unidades.")
    return float(numero), "Unidad"


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
                    "hora": format_utc_naive_to_local(borrador.actualizado, "%H:%M:%S") or "—",
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
            "origen_carga": item.origen_carga or "carga_manual",
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
            "origen_carga": conteo.origen_carga or "carga_manual",
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
            "origen_carga": conteo.origen_carga or "carga_manual",
            "es_borrador": False,
            "hora": format_utc_naive_to_local(conteo.fecha_carga, "%H:%M:%S") or "—",
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
            "origen_carga": item.origen_carga or "carga_manual",
            "es_borrador": False,
            "hora": format_utc_naive_to_local(item.actualizado, "%H:%M:%S") or "—",
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


def combinar_cargas_para_vista(*, carrito: list, cargas_periodo: list, usuario: str) -> list:
    """Integra el carrito propio y las cargas de la tienda en una sola tabla visual."""
    visibles = []
    claves_propias = set()
    for indice, entrada in enumerate(carrito):
        item = dict(entrada)
        clave = (str(item.get("categoria") or ""), str(item.get("producto") or ""))
        claves_propias.add(clave)
        item.update(
            es_propio=True,
            carrito_idx=indice,
            usuario=usuario,
            es_borrador=True,
        )
        visibles.append(item)

    for carga in cargas_periodo:
        clave = (str(carga.get("categoria") or ""), str(carga.get("producto") or ""))
        if clave in claves_propias:
            continue
        item = dict(carga)
        item.update(
            cantidad_unidades=float(carga.get("cantidad") or 0),
            ume="kg" if carga.get("categoria") == "Por Kilos" else "Unidad",
            detalle="",
            es_propio=False,
            carrito_idx=None,
        )
        visibles.append(item)
    return visibles


def obtener_productos_no_cargados(*, productos: dict, productos_cargados: list) -> list:
    """Devuelve el catálogo que aún no tiene carga en el período seleccionado."""
    cargados = {
        identidad_producto(item.get("producto") or "")
        for item in productos_cargados
    }
    pendientes = []
    for categoria, nombres in productos.items():
        for nombre in nombres:
            clave = identidad_producto(nombre)
            if clave not in cargados:
                pendientes.append({"categoria": categoria, "producto": nombre})
    return pendientes


def construir_entradas_confirmacion_cero(*, productos: dict, productos_cargados: list,
                                         fecha: str) -> list:
    """Construye una entrada auditable por cada producto que sigue sin cargarse."""
    return [
        {
            "categoria": pendiente["categoria"],
            "producto": pendiente["producto"],
            "cantidad": 0.0,
            "cantidad_unidades": 0.0,
            "ume": "kg" if pendiente["categoria"] == "Por Kilos" else "Unidad",
            "factor": 1.0,
            "desc_conversion": "",
            "tipo_inventario": "Diario",
            "fecha": fecha,
            "detalle": "Confirmado sin stock al guardar el inventario.",
            "hora": now_local_time_str(),
            "version_esperada": 0,
            "confirmar_sobreescritura": False,
            "origen_carga": "confirmacion_sin_stock",
        }
        for pendiente in obtener_productos_no_cargados(
            productos=productos,
            productos_cargados=productos_cargados,
        )
    ]


def build_empleado_inventario_context(*, active_tab: str, carrito: list, hoy: str,
                                      productos_cargados=None, conflicto_carga=None):
    productos = get_productos_db(
        cliente_id=session.get("cliente_id", "C001"),
        username=session.get("usuario", ""),
    )
    productos_cargados = productos_cargados or []
    return {
        "productos": productos,
        "active_tab": _safe_inv_tab(active_tab),
        "categorias": CATEGORIAS,
        "tipos_inventario": TIPOS_INVENTARIO,
        "opciones_ume": OPCIONES_UME,
        "estados_balde": ESTADOS_BALDE,
        "carrito": carrito,
        "productos_cargados": productos_cargados,
        "productos_no_cargados": obtener_productos_no_cargados(
            productos=productos,
            productos_cargados=productos_cargados,
        ),
        "hoy": hoy,
        "conflicto_carga": conflicto_carga,
        "hide_global_flash": True,
    }


def add_carrito_item(*, carrito: list, categoria: str, producto: str, cantidad: float,
                     ume: str, tipo_inventario: str, fecha: str, detalle: str,
                     version_esperada: int = 0,
                     confirmar_sobreescritura: bool = False,
                     estado_balde: str = "", cantidad_baldes=None, peso_kg=None,
                     desc_conversion_inicial: str = ""):
    cantidad_unidades = cantidad
    factor = 1.0
    desc_conversion = desc_conversion_inicial
    if categoria == "Por Kilos":
        normalizada = normalizar_conteo_kilos(
            estado_balde=estado_balde,
            cantidad_baldes=cantidad_baldes,
            peso_kg=peso_kg,
        )
        cantidad = normalizada["cantidad"]
        cantidad_unidades = normalizada["cantidad_unidades"]
        ume = normalizada["ume"]
        factor = normalizada["factor"]
        desc_conversion = normalizada["desc_conversion"]
    elif ume in ("Caja", "Bulto"):
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
        "estado_balde": estado_balde if categoria == "Por Kilos" else "",
        "cantidad_baldes": cantidad_baldes if categoria == "Por Kilos" else None,
        "peso_kg": peso_kg if categoria == "Por Kilos" else None,
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
        periodo = db.session.get(InventarioPeriodo, int(periodo_id))
        if (
            periodo
            and periodo.cliente_id == cliente_id
            and periodo.tienda_id == tienda_id
            and periodo.estado in ("Abierto", "Pendiente", "Cargado")
        ):
            return periodo
        return None
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
        origen_carga = primera.get("origen_carga", "carga_manual")
        if origen_carga not in ("carga_manual", "confirmacion_sin_stock"):
            origen_carga = "carga_manual"
        actual = estados[(categoria, producto)]
        unidad_base = "kg" if categoria == "Por Kilos" else "Unidad"
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
                    "ume": unidad_base,
                    "tipo_inventario": tipo_inv,
                    "fecha": fecha_prod,
                    "sinc_estado": "pendiente",
                    "periodo_id": periodo_id,
                    "usuario_ultima_carga": usuario,
                    "version": version_nueva,
                    "fue_sobreescrito": True,
                    "origen_carga": origen_carga,
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
                item.ume = unidad_base
                item.tipo_inventario = tipo_inv
                item.fecha = fecha_prod
                item.sinc_estado = "pendiente"
                item.periodo_id = periodo_id
                item.usuario_ultima_carga = usuario
                item.version = version_nueva
                item.fue_sobreescrito = True
                item.origen_carga = origen_carga
            else:
                db.session.add(InventarioItem(
                    cliente_id=cliente_id,
                    tienda_id=tienda_id, categoria=categoria, producto=producto,
                    cantidad=cantidad_total, ume=unidad_base,
                    tipo_inventario=tipo_inv, fecha=fecha_prod,
                    sinc_estado="pendiente", periodo_id=periodo_id,
                    usuario_ultima_carga=usuario, version=version_nueva,
                    fue_sobreescrito=True, origen_carga=origen_carga))
            tipo_movimiento = "sobreescritura"
            usuario_anterior = actual["usuario"]
            cantidad_anterior = actual["cantidad"]
        else:
            version_nueva = 1
            if item:  # El mismo stock operativo provenía de otro período.
                item.cliente_id = cliente_id
                item.cantidad = cantidad_total
                item.ume = unidad_base
                item.tipo_inventario = tipo_inv
                item.fecha = fecha_prod
                item.sinc_estado = "pendiente"
                item.periodo_id = periodo_id
                item.usuario_ultima_carga = usuario
                item.version = version_nueva
                item.fue_sobreescrito = False
                item.origen_carga = origen_carga
            else:
                db.session.add(InventarioItem(
                    cliente_id=cliente_id,
                    tienda_id=tienda_id, categoria=categoria, producto=producto,
                    cantidad=cantidad_total, ume=unidad_base,
                    tipo_inventario=tipo_inv, fecha=fecha_prod,
                    sinc_estado="pendiente", periodo_id=periodo_id,
                    usuario_ultima_carga=usuario, version=version_nueva,
                    fue_sobreescrito=False, origen_carga=origen_carga))
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
            modo=unidad_base,
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
            origen_carga=origen_carga,
        ))

        # Estado por período: InventarioItem representa el stock operativo más
        # reciente y puede cambiar de período. ConteoDetalle conserva cada
        # carga en el período elegido para que dos períodos abiertos no se mezclen.
        conteo = ConteoDetalle.query.filter_by(
            periodo_id=periodo_id,
            cliente_id=cliente_id,
            tienda_id=tienda_id,
            producto_nombre=producto,
        ).first()
        ahora = utc_now()
        if conteo:
            conteo.usuario = usuario
            conteo.categoria = categoria
            conteo.cantidad_unidad = cantidad_total
            conteo.total_unidad_base = cantidad_total
            conteo.fue_cargado = True
            conteo.fecha_carga = ahora
            conteo.fue_sobreescrito = tipo_movimiento == "sobreescritura"
            conteo.version_ultima_carga = version_nueva
            conteo.origen_carga = origen_carga
        else:
            db.session.add(ConteoDetalle(
                periodo_id=periodo_id,
                cliente_id=cliente_id,
                tienda_id=tienda_id,
                usuario=usuario,
                producto_nombre=producto,
                categoria=categoria,
                cantidad_unidad=cantidad_total,
                total_unidad_base=cantidad_total,
                fue_cargado=True,
                primera_carga=ahora,
                fecha_carga=ahora,
                fue_sobreescrito=tipo_movimiento == "sobreescritura",
                version_ultima_carga=version_nueva,
                origen_carga=origen_carga,
            ))
        guardados += 1

    snapshot.total_items = guardados
    return guardados


def guardar_carrito_transaccional(
    carrito: list,
    tienda_id: str,
    usuario: str,
    *,
    cliente_id: str,
    periodo_id: int,
    antes_commit: Optional[Callable[[int], None]] = None,
) -> int:
    """Guarda todo el carrito o revierte por completo y permite reintentar."""
    try:
        guardados = build_carrito_guardado(
            carrito,
            tienda_id,
            usuario,
            cliente_id=cliente_id,
            periodo_id=periodo_id,
        )
        db.session.flush()
        if antes_commit is not None:
            antes_commit(guardados)
        db.session.commit()
        return guardados
    except Exception:
        db.session.rollback()
        raise


def build_averiado_context(*, cliente_id: str, tienda_id: str, periodo_id: int | None):
    recientes = []
    if periodo_id is not None:
        recientes = (
            RegistroAveriado.query.filter_by(
                cliente_id=cliente_id, tienda_id=tienda_id, periodo_id=periodo_id,
            )
            .order_by(RegistroAveriado.creado.desc()).limit(30).all()
        )
    return {
        "productos": get_productos_db(
            cliente_id=cliente_id,
            username=session.get("usuario", ""),
        ),
        "categorias": CATEGORIAS,
        "recientes": recientes,
        "hoy": today_local_iso(),
    }


def registrar_averiado(*, tienda_id: str, usuario: str, categoria: str, producto: str,
                       cantidad: float, ume: str, detalle: str, fecha: str,
                       periodo_id: int):
    cliente_id = session.get("cliente_id", "C001")
    periodo = db.session.get(InventarioPeriodo, periodo_id)
    if (
        periodo is None
        or periodo.cliente_id != cliente_id
        or periodo.tienda_id != tienda_id
        or periodo.estado not in ("Abierto", "Pendiente", "Cargado")
    ):
        raise ValueError("Selecciona un período contable abierto y válido.")
    try:
        datetime.strptime(fecha, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError("La fecha del averiado no es válida.") from exc
    if not (periodo.fecha_desde <= fecha <= periodo.fecha_hasta):
        raise ValueError(
            f"La fecha del averiado debe estar entre {periodo.fecha_desde} "
            f"y {periodo.fecha_hasta}."
        )
    if categoria == "Por Kilos":
        cantidad, ume = normalizar_cantidad_categoria(categoria, cantidad)
        cu, desc = cantidad, f"{_kg_texto(cantidad)} kg · peso real averiado"
    else:
        cu, desc = convertir_ume(producto, ume, cantidad)
    db.session.add(RegistroAveriado(
        cliente_id=cliente_id,
        tienda_id=tienda_id, periodo_id=periodo.id, fecha=fecha,
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
        "productos": get_productos_db(
            cliente_id=session.get("cliente_id", "C001"),
            username=session.get("usuario", ""),
        ),
        "categorias": CATEGORIAS,
        "recientes": RegistroVencimiento.query.filter_by(tienda_id=tienda_id).order_by(RegistroVencimiento.creado.desc()).limit(30).all(),
        "hoy": today_local_iso(),
    }


def registrar_vencimiento(*, tienda_id: str, usuario: str, categoria: str, producto: str,
                          cantidad: float, ume: str, fecha_vencimiento: str,
                          detalle: str, fecha: str):
    if categoria == "Por Kilos":
        cantidad, ume = normalizar_cantidad_categoria(categoria, cantidad)
        cu, desc = cantidad, f"{_kg_texto(cantidad)} kg · peso real próximo a vencer"
    else:
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


def _pendientes_inventario_usuario(cliente_id, tienda_id, usuario, periodo_id=None):
    query = (
        InventarioItem.query
        .filter_by(cliente_id=cliente_id, tienda_id=tienda_id, sinc_estado="pendiente")
        .filter(or_(
            InventarioItem.usuario_ultima_carga == usuario,
            InventarioItem.usuario_ultima_carga == "",
            InventarioItem.usuario_ultima_carga.is_(None),
        ))
    )
    if periodo_id is not None:
        query = query.filter(InventarioItem.periodo_id == int(periodo_id))
    return query


def build_sincronizacion_context(*, cliente_id: str, tienda_id: str, periodo_id=None):
    usuario = session.get("usuario", "")
    pend_inv = _pendientes_inventario_usuario(
        cliente_id, tienda_id, usuario, periodo_id=periodo_id
    ).count()
    averiados_q = RegistroAveriado.query.filter_by(
        cliente_id=cliente_id, tienda_id=tienda_id,
        usuario=usuario, sinc_estado="pendiente",
    )
    averiados_q = averiados_q.filter(
        RegistroAveriado.periodo_id == int(periodo_id) if periodo_id is not None else false()
    )
    pend_aver = averiados_q.count()
    pend_venc = RegistroVencimiento.query.filter_by(cliente_id=cliente_id, tienda_id=tienda_id, usuario=usuario, sinc_estado="pendiente").count()
    catalogo_pendiente, catalogo_cambios = catalogo_pendiente_usuario(
        cliente_id,
        usuario,
    )
    return {
        "pendientes": pend_inv + pend_aver + pend_venc,
        "pend_inv": pend_inv,
        "pend_aver": pend_aver,
        "pend_venc": pend_venc,
        "catalogo_pendiente": catalogo_pendiente,
        "catalogo_cambios": catalogo_cambios,
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


def procesar_sincronizacion(*, cliente_id: str, tienda_id: str, usuario: str,
                            accion: str, periodo_id=None):
    db.session.add(SincronizacionLog(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
        usuario=usuario,
        tipo="envio",
        accion=accion,
    ))

    pendientes = _pendientes_inventario_usuario(
        cliente_id, tienda_id, usuario, periodo_id=periodo_id
    ).all()
    for item in pendientes:
        item.sinc_estado = "sincronizado"
    n_inv = len(pendientes)

    averiados_q = RegistroAveriado.query.filter_by(
        cliente_id=cliente_id, tienda_id=tienda_id,
        usuario=usuario, sinc_estado="pendiente",
    )
    averiados_q = averiados_q.filter(
        RegistroAveriado.periodo_id == int(periodo_id) if periodo_id is not None else false()
    )
    pend_aver = averiados_q.all()
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
        catalogo_actualizado = recibir_catalogo_usuario(cliente_id, usuario)
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
    cliente_id = session.get("cliente_id", "C001")
    periodo = (
        InventarioPeriodo.query
        .filter_by(cliente_id=cliente_id, tienda_id=tienda_id)
        .filter(InventarioPeriodo.fecha_desde <= fecha)
        .filter(InventarioPeriodo.fecha_hasta >= fecha)
        .order_by(InventarioPeriodo.id.desc())
        .first()
    )
    hay_periodos = InventarioPeriodo.query.filter_by(
        cliente_id=cliente_id,
        tienda_id=tienda_id,
    ).first() is not None
    total = producto.precio * cantidad
    db.session.add(DeliveryVenta(
        cliente_id=cliente_id,
        fecha=fecha,
        hora=now_local_time_str(),
        producto=producto.nombre,
        cantidad=cantidad,
        precio_unitario=producto.precio,
        total=total,
        usuario=usuario,
        tienda_id=tienda_id,
        periodo_id=periodo.id if periodo else None,
        estado_periodo="en_rango" if periodo else ("fuera_rango" if hay_periodos else "sin_periodo"),
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
