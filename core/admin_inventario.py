"""Lógica de negocio para el inventario administrativo.

Este módulo concentra el cálculo de métricas, filtros y accesos rápidos
para mantener `app.py` como una capa fina de enrutamiento.
"""
from __future__ import annotations

from typing import Dict, Iterable, List

from flask import url_for

from core.models import InventarioItem, Producto, ProductoPrecio, RegistroVencimiento, StockThreshold
from core.seed_data import CATEGORIAS, stock_status


def _format_es_number(value, decimals: int = 0):
    """Formatea números con separador de miles estilo ES/py."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if decimals <= 0:
        return f"{int(round(number)):,}".replace(",", ".")
    formatted = f"{number:,.{decimals}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _productos_por_categoria() -> Dict[str, List[str]]:
    """Devuelve el catálogo actual agrupado por categoría."""
    result: Dict[str, List[str]] = {}
    for categoria in CATEGORIAS:
        result[categoria] = [
            p.nombre
            for p in Producto.query.filter_by(categoria=categoria).order_by(Producto.nombre).all()
        ]
    return result


def _inventario_agregado(tienda_id: str):
    """Agrupa inventario sincronizado por categoria/producto en una tienda o en todas."""
    inventario = {}
    query = InventarioItem.query.filter_by(sinc_estado="sincronizado")
    if tienda_id != "ALL":
        query = query.filter_by(tienda_id=tienda_id)

    for item in query.all():
        key = (item.categoria, item.producto)
        dato = inventario.setdefault(key, {
            "cantidad": 0,
            "ume": item.ume or "N/A",
            "tiendas": set(),
        })
        dato["cantidad"] += item.cantidad or 0
        dato["tiendas"].add(item.tienda_id)
        if dato["ume"] in (None, "", "N/A") and item.ume:
            dato["ume"] = item.ume
    return inventario


def _items_sincronizados(tienda_id=None):
    """InventarioItems sincronizados, opcionalmente filtrados por tienda."""
    q = InventarioItem.query.filter_by(sinc_estado="sincronizado")
    if tienda_id and tienda_id != "ALL":
        q = q.filter_by(tienda_id=tienda_id)
    return q.all()


def _precios_lookup():
    """{nombre_lower: ProductoPrecio} solo con precio cargado."""
    return {
        p.producto_nombre.strip().lower(): p
        for p in ProductoPrecio.query.filter(ProductoPrecio.precio.isnot(None)).all()
    }


def build_admin_inventory_context(
    *,
    cliente_id: str,
    tiendas: Iterable,
    tienda_id: str,
    categoria_filtro: str,
    busqueda: str,
    estado_filtro: str,
    alerta_filtro: str,
):
    """Calcula todo el contexto de la vista de inventario admin."""
    thresholds = {
        t.producto: {"critico": t.critico, "medio": t.medio}
        for t in StockThreshold.query.all()
    }
    precios = _precios_lookup()
    inventario_map = _inventario_agregado(tienda_id)
    productos_db = _productos_por_categoria()

    productos_totales = 0
    cargados_totales = 0
    stock_total_general = 0
    valor_total_general = 0
    bajo_stock_total = 0

    data = {}
    resumen = {}
    categorias_render = CATEGORIAS if categoria_filtro == "Todas" else [categoria_filtro]

    for categoria in CATEGORIAS:
        productos_categoria = productos_db.get(categoria, [])
        filas_categoria = []
        filas_totales = []

        for producto in productos_categoria:
            item = inventario_map.get((categoria, producto))
            cantidad = item["cantidad"] if item else 0
            modo = item["ume"] if item else "N/A"
            nivel, etiqueta = stock_status(producto, cantidad, thresholds)
            cargado = cantidad > 0
            precio = precios.get(producto.strip().lower())
            valor = (cantidad * precio.precio) if precio and precio.precio is not None else 0

            fila = {
                "producto": producto,
                "cantidad": cantidad,
                "cantidad_fmt": _format_es_number(cantidad),
                "modo": modo,
                "nivel": nivel,
                "etiqueta": etiqueta,
                "cargado": cargado,
                "valor": valor,
                "valor_fmt": _format_es_number(valor),
            }
            filas_totales.append(fila)

            if busqueda and busqueda not in producto.lower():
                continue
            if estado_filtro == "Cargado" and not cargado:
                continue
            if estado_filtro == "No cargado" and cargado:
                continue
            if alerta_filtro == "Bajo stock" and nivel not in ("warning", "critical"):
                continue
            filas_categoria.append(fila)

        stock_total = sum(f["cantidad"] for f in filas_totales)
        valor_total = sum(f["valor"] for f in filas_totales)
        cargados = sum(1 for f in filas_totales if f["cargado"])
        bajo_stock = sum(1 for f in filas_totales if f["nivel"] in ("warning", "critical") and f["cargado"])
        total = len(productos_categoria)

        data[categoria] = filas_categoria
        resumen[categoria] = {
            "total": total,
            "cargados": cargados,
            "no_cargados": total - cargados,
            "porcentaje": round(cargados / total * 100, 1) if total else 0,
            "stock_total": stock_total,
            "stock_total_fmt": _format_es_number(stock_total),
            "valor_total": valor_total,
            "valor_total_fmt": _format_es_number(valor_total),
            "bajo_stock": bajo_stock,
            "productos_fmt": _format_es_number(total),
        }

        productos_totales += total
        cargados_totales += cargados
        stock_total_general += stock_total
        valor_total_general += valor_total
        bajo_stock_total += bajo_stock

    tiendas = list(tiendas)
    tienda_label = "Todas las tiendas" if tienda_id == "ALL" else next((t.nombre for t in tiendas if t.id == tienda_id), tienda_id)
    tienda_export_id = tienda_id if tienda_id != "ALL" else (tiendas[0].id if tiendas else "T001")
    tienda_historial_id = tienda_id if tienda_id != "ALL" else (tiendas[0].id if tiendas else "T001")
    tienda_vencimientos_id = tienda_id if tienda_id != "ALL" else "Todas"

    quick_actions = [
        {
            "label": "Ver inventario completo",
            "sub": "Todos los productos cargados y sin cargar",
            "href": url_for(
                "admin_inventario",
                tienda=tienda_id,
                categoria="Todas",
                estado="Todos",
                busqueda="",
                alerta="Todos",
            ) + "#inventario-detalle",
            "icon": "icons/box.svg",
            "count": productos_totales,
            "tone": "blue",
        },
        {
            "label": "Productos con bajo stock",
            "sub": "Abre el filtro de alertas del inventario",
            "href": url_for(
                "admin_inventario",
                tienda=tienda_id,
                categoria="Todas",
                estado="Todos",
                busqueda="",
                alerta="Bajo stock",
            ) + "#inventario-detalle",
            "icon": "icons/alert.svg",
            "count": bajo_stock_total,
            "tone": "warning",
        },
        {
            "label": "Productos vencidos",
            "sub": "Ir al panel de vencimientos",
            "href": url_for("admin_vencimientos", tienda=tienda_vencimientos_id),
            "icon": "icons/clock.svg",
            "count": (
                RegistroVencimiento.query.filter_by(
                    cliente_id=cliente_id,
                    sinc_estado="sincronizado",
                    revisado=False,
                    tienda_id=tienda_id,
                ).count()
                if tienda_id != "ALL"
                else RegistroVencimiento.query.filter_by(
                    cliente_id=cliente_id,
                    sinc_estado="sincronizado",
                    revisado=False,
                ).count()
            ),
            "tone": "danger",
        },
        {
            "label": "Últimos movimientos",
            "sub": "Revisa el historial reciente",
            "href": url_for("admin_historial", tienda=tienda_historial_id),
            "icon": "icons/chart.svg",
            "count": None,
            "tone": "green",
        },
    ]

    return {
        "tienda_label": tienda_label,
        "tienda_export_id": tienda_export_id,
        "tienda_historial_id": tienda_historial_id,
        "tienda_vencimientos_id": tienda_vencimientos_id,
        "quick_actions": quick_actions,
        "data": data,
        "resumen": resumen,
        "categorias_render": categorias_render,
        "total_productos": productos_totales,
        "total_cargados": cargados_totales,
        "total_stock": stock_total_general,
        "total_stock_fmt": _format_es_number(stock_total_general),
        "total_valor": valor_total_general,
        "total_valor_fmt": _format_es_number(valor_total_general),
        "bajo_stock_total": bajo_stock_total,
    }