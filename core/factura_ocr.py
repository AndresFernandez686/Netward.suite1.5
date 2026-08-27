"""Lectura y aplicación de facturas de compra en Documentación Oficial.

Primero usa el texto incluido en el PDF. Si el comprobante es una imagen, renderiza
las páginas y usa Tesseract como respaldo OCR. Las compras solo se aplican cuando el
producto y su conversión de UME son suficientemente confiables.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
from importlib import import_module
import io
import json
import math
import os
import re
import unicodedata
from typing import Iterable

from .models import (
    db, ExcelDetalle, ExcelDetalleEdicion, ExcelImportado, FacturaCompra,
    FacturaCompraDetalle, InventarioPeriodo, Producto, ProductoPrecio,
)


MAX_FACTURAS_POR_CARGA = 20
MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_TOTAL_BYTES = 60 * 1024 * 1024


class FacturaError(ValueError):
    pass


@dataclass
class LineaExtraida:
    codigo: str
    descripcion: str
    cantidad: float
    precio_unitario: float = 0
    importe: float = 0


@dataclass
class FacturaExtraida:
    proveedor: str
    numero: str
    fecha_emision: date | None
    total: float
    metodo: str
    texto: str
    lineas: list[LineaExtraida]


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value)).strip()


def _numero(value: str) -> float:
    text = re.sub(r"[^0-9,.-]", "", str(value or "").strip())
    if not text:
        return 0
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif text.count(".") > 1 or (text.count(".") == 1 and len(text.rsplit(".", 1)[1]) == 3):
        text = text.replace(".", "")
    return float(text)


def _extraer_texto_pdf(contenido: bytes) -> tuple[str, str]:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(contenido)) as pdf:
            texto = "\n".join(page.extract_text(x_tolerance=2, y_tolerance=3) or "" for page in pdf.pages)
        if len(_norm(texto)) >= 80:
            return texto, "texto_pdf"
    except Exception:
        texto = ""

    try:
        import pypdfium2 as pdfium
        # Tesseract es un respaldo opcional: se carga solo cuando el PDF no
        # trae texto para que el flujo digital no dependa del ejecutable OCR.
        pytesseract = import_module("pytesseract")
        if os.getenv("TESSERACT_CMD", "").strip():
            getattr(pytesseract, "pytesseract").tesseract_cmd = os.getenv(
                "TESSERACT_CMD", ""
            ).strip()
        pdf = pdfium.PdfDocument(contenido)
        partes = []
        for pagina in pdf:
            imagen = pagina.render(scale=2).to_pil()
            partes.append(getattr(pytesseract, "image_to_string")(imagen, lang="spa"))
        texto = "\n".join(partes)
    except Exception as exc:
        raise FacturaError(
            "El PDF no contiene texto legible y el OCR no está disponible. "
            "Instala Tesseract con el idioma español o utiliza un PDF digital."
        ) from exc
    if len(_norm(texto)) < 80:
        raise FacturaError("No se pudo reconocer contenido suficiente en el PDF.")
    return texto, "ocr_tesseract"


def _detectar_proveedor(texto: str) -> str:
    normal = _norm(texto)
    if "helacor paraguay" in normal or "80084710" in normal:
        return "Helacor"
    if "fane industrial" in normal or "80019396" in normal:
        return "Fane"
    raise FacturaError("Proveedor no reconocido. Actualmente se admiten facturas Helacor y Fane.")


_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def _cabecera(texto: str, proveedor: str) -> tuple[str, date | None, float]:
    normal = _norm(texto)
    numero = ""
    fecha = None
    total = 0.0
    if proveedor == "Helacor":
        match = re.search(r"Factura\s+electr[^\n]*\nN[^:]*:\s*([0-9-]+)", texto, re.I)
        if not match:
            match = re.search(r"N[^:]{0,4}:\s*([0-9]{3}-[0-9]{3}-[0-9]+)", texto, re.I)
        numero = match.group(1) if match else ""
        match = re.search(r"Fecha\s+emisi[^:]*:\s*(\d{1,2})-(\d{1,2})-(\d{4})", texto, re.I)
        if match:
            fecha = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    else:
        match = re.search(r"\b(\d{3}-\d{3}-\d{7})\b", texto)
        numero = match.group(1) if match else ""
        match = re.search(r"Fecha\s*:\s*(\d{1,2})\s+de\s+([A-Za-záéíóú]+)\s+de\s+(\d{4})", texto, re.I)
        if match:
            mes = _MESES.get(_norm(match.group(2)))
            if mes:
                fecha = date(int(match.group(3)), mes, int(match.group(1)))
    matches = re.findall(r"(?:TOTAL DE LA OPERACI[ÓO]N|Total a Pagar)\s*:?.*?([0-9][0-9.]+)\s*$", texto, re.I | re.M)
    if matches:
        total = _numero(matches[-1])
    if not numero:
        match = re.search(r"\b(\d{40,50})\b", normal.replace(" ", ""))
        numero = (match.group(1)[10:23] if match else "sin-numero")
    return numero, fecha, total


def _lineas_helacor(texto: str) -> list[LineaExtraida]:
    resultado = []
    patron = re.compile(
        r"^(\d{6,})\s+(.+?)\s+UNI\s+([0-9]+(?:[.,][0-9]+)?)\s+([0-9.]+)\s+0\s+0\s+0\s+([0-9.]+)\s*$",
        re.I,
    )
    for linea in texto.splitlines():
        match = patron.match(linea.strip())
        if match:
            resultado.append(LineaExtraida(
                codigo=match.group(1), descripcion=match.group(2).strip(),
                cantidad=_numero(match.group(3)), precio_unitario=_numero(match.group(4)),
                importe=_numero(match.group(5)),
            ))
    return resultado


def _lineas_fane(contenido: bytes) -> list[LineaExtraida]:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(contenido)) as pdf:
            paginas = [page.extract_words() for page in pdf.pages]
    except Exception:
        return []

    resultado = []
    for words in paginas:
        grupos: list[list[dict]] = []
        for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
            if grupos and abs(grupos[-1][0]["top"] - word["top"]) <= 2.2:
                grupos[-1].append(word)
            else:
                grupos.append([word])
        for grupo in grupos:
            words_row = sorted(grupo, key=lambda w: w["x0"])
            qty = next((w for w in words_row if 70 <= w["x0"] < 112 and re.fullmatch(r"\d+[,.]\d+", w["text"])), None)
            descripcion = " ".join(w["text"] for w in words_row if 112 <= w["x0"] < 265).strip(" ,")
            if not qty or not descripcion:
                continue
            codigo_words = [w["text"] for w in words_row if w["x0"] < 70 and re.fullmatch(r"\d{2,14}", w["text"])]
            precio_words = [w["text"] for w in words_row if 265 <= w["x0"] < 310 and re.search(r"\d", w["text"])]
            importe_words = [w["text"] for w in words_row if w["x0"] >= 400 and re.search(r"\d", w["text"])]
            resultado.append(LineaExtraida(
                codigo=codigo_words[0] if codigo_words else "",
                descripcion=descripcion,
                cantidad=_numero(qty["text"]),
                precio_unitario=_numero(precio_words[-1]) if precio_words else 0,
                importe=_numero(importe_words[-1]) if importe_words else 0,
            ))
    return resultado


def _lineas_fane_texto(texto: str) -> list[LineaExtraida]:
    """Respaldo para el texto producido por OCR cuando no hay coordenadas PDF."""
    resultado = []
    patron = re.compile(
        r"^(?:(\d{2,14})\s+)?(\d+[,.]\d+)\s+(.+?)\s+([0-9.]+)\s+0\s+0\s+0\s+([0-9.]+)\s*$",
        re.I,
    )
    for linea in texto.splitlines():
        match = patron.match(linea.strip())
        if match:
            resultado.append(LineaExtraida(
                codigo=match.group(1) or "", cantidad=_numero(match.group(2)),
                descripcion=match.group(3).strip(" ,"),
                precio_unitario=_numero(match.group(4)), importe=_numero(match.group(5)),
            ))
    return resultado


def extraer_factura(contenido: bytes) -> FacturaExtraida:
    if not contenido.startswith(b"%PDF"):
        raise FacturaError("El archivo no es un PDF válido.")
    texto, metodo = _extraer_texto_pdf(contenido)
    proveedor = _detectar_proveedor(texto)
    numero, fecha, total = _cabecera(texto, proveedor)
    lineas = _lineas_helacor(texto) if proveedor == "Helacor" else _lineas_fane(contenido)
    if proveedor == "Fane" and not lineas:
        lineas = _lineas_fane_texto(texto)
    if not lineas:
        raise FacturaError(f"No se detectaron productos en la factura {proveedor}.")
    return FacturaExtraida(proveedor, numero, fecha, total, metodo, texto, lineas)


_CODIGOS_PROVEEDOR = {
    "Helacor": {
        "4000105": "Palito Crema Americana", "4000890": "Palito Bombon",
        "4000833": "Alfajor Bombon Cookies and Crema", "4000116": "Alfajor Bombon Escoces",
        "4000115": "Alfajor Bombon Suizo", "4000448": "Torta Grido Rellena",
        "4000111": "Alfajor Casatta", "4000839": "Torta Milka",
        "4000132": "Familiar 1", "4000133": "Familiar 3", "4000135": "Familiar 4",
    },
    "Fane": {
        "09202": "Cucurucho Biscoito Dulce x300",
        "7840583002311": "Cucurucho Cascao x120",
        "7840263015693": "Servilleta Grido", "011": "Isopor 1 kilo",
        "017": "Isopor 1/2 kilo", "1166": "Isopor 1/4",
        "7896411893088": "Cobertura Chocolate", "7896411893163": "Cobertura Frutilla",
        "7896411893149": "Cobertura Dulce de Leche",
    },
}


def _factor_conversion(proveedor: str, linea: LineaExtraida) -> tuple[float, str]:
    normal = _norm(linea.descripcion)
    if proveedor == "Helacor":
        pack = re.search(r"\bpack\s*x?\s*(\d+)\b", normal)
        factor = float(pack.group(1)) if pack else 1.0
        if "caj" in normal:
            unidades = re.findall(r"\bx\s*(\d+)\s*(?:un\w*)?\b", normal)
            candidatos = [int(n) for n in unidades if f"x {n} lt" not in normal and f"x {n}lts" not in normal]
            if candidatos:
                factor *= candidatos[-1]
        elif not pack:
            unidades = re.search(r"\bx\s*(\d+)\s+un", normal)
            if unidades:
                factor = float(unidades.group(1))
        return factor, "pack detectado" if factor != 1 else "unidad facturada"

    # En Fane los artículos por caja muestran pocas cajas y el contenido del pack.
    # Cantidades grandes (p. ej. 100 vasos) ya representan unidades facturadas.
    if linea.cantidad < 20:
        unidades = re.search(r"\b(\d+)\s*(?:uni|unid)\b", normal)
        if unidades:
            return float(unidades.group(1)), "unidades por paquete"
    return 1.0, "unidad facturada"


def factor_conversion_catalogo(
    producto: Producto | None, cliente_id: str,
) -> tuple[float, str] | None:
    """Devuelve unidades por bulto desde la presentación real del producto.

    En ``ProductoPrecio``, ``unidades_por_bulto`` conserva el nombre histórico
    de la columna, pero la interfaz lo define como *cajas por bulto*. Por ello,
    la UME correcta es unidades/caja × cajas/bulto. No se usan valores fijos por
    código: cada producto puede tener una presentación diferente.
    """
    if producto is None or producto.categoria not in {"Impulsivo", "Fanee", "Extras"}:
        return None
    precio = ProductoPrecio.query.filter_by(
        cliente_id=cliente_id, producto_id=producto.id,
    ).first()
    if precio is None:
        precio = ProductoPrecio.query.filter(
            ProductoPrecio.cliente_id == cliente_id,
            db.func.lower(ProductoPrecio.producto_nombre) == producto.nombre.strip().lower(),
        ).first()
    if precio is None:
        return None
    unidades_caja = float(precio.unidades_por_caja or 0)
    cajas_bulto = float(precio.unidades_por_bulto or 0)
    if (
        not math.isfinite(unidades_caja) or not math.isfinite(cajas_bulto)
        or unidades_caja <= 0 or cajas_bulto <= 0
    ):
        return None
    return (
        unidades_caja * cajas_bulto,
        f"catálogo: {unidades_caja:g} unidades/caja × {cajas_bulto:g} cajas/bulto",
    )


def _resolver_factor_conversion(
    proveedor: str, linea: LineaExtraida, producto: Producto | None, cliente_id: str,
) -> tuple[float, str]:
    # Helacor factura estos artículos por bulto. Una vez vinculado el producto,
    # su presentación configurada es más confiable que el texto variable del PDF.
    if proveedor == "Helacor":
        factor_catalogo = factor_conversion_catalogo(producto, cliente_id)
        if factor_catalogo is not None:
            return factor_catalogo
    return _factor_conversion(proveedor, linea)


def calcular_compras_unidades(cantidad_facturada: float, factor_conversion: float) -> float:
    """Calcula la compra en unidades desde los dos datos editables de la factura.

    ``compras_calculadas`` se conserva en la base de datos para mostrarla en la
    pantalla, pero no debe convertirse en una segunda fuente de verdad: si el
    administrador corrige la cantidad o el factor, una copia anterior puede
    quedar desactualizada. Por eso todos los consumidores usan esta función.
    """
    cantidad = float(cantidad_facturada or 0)
    factor = float(factor_conversion or 0)
    if not math.isfinite(cantidad) or not math.isfinite(factor):
        raise FacturaError("La cantidad y el factor de conversión deben ser números válidos.")
    if cantidad < 0 or factor <= 0:
        raise FacturaError("La cantidad no puede ser negativa y el factor debe ser mayor que cero.")
    return cantidad * factor


def _buscar_producto(proveedor: str, linea: LineaExtraida) -> tuple[Producto | None, str]:
    nombre = _CODIGOS_PROVEEDOR.get(proveedor, {}).get(linea.codigo)
    if nombre:
        producto = Producto.query.filter_by(nombre=nombre).first()
        if producto:
            return producto, "código de proveedor"
        # Algunas instalaciones conservan como nombre interno el alias usado
        # por el inventario oficial (p. ej. "Bombon escoces x unidad") en vez
        # del nombre del catálogo base. El código del proveedor sigue siendo
        # inequívoco, por lo que también se resuelve contra ese alias.
        from .inventario import RENOMBRAR_CATALOGO
        alias = RENOMBRAR_CATALOGO.get(nombre)
        if alias:
            producto = Producto.query.filter_by(nombre=alias).first()
            if producto:
                return producto, "código de proveedor y alias del inventario"

    normal = _norm(linea.descripcion)
    reglas = [
        ("cucharita nacional", "Cucharita Grido"),
        ("vaso grido batido", "Vaso Batido"),
    ]
    for fragmento, candidato in reglas:
        if fragmento in normal:
            producto = Producto.query.filter_by(nombre=candidato).first()
            return producto, "descripción de proveedor" if producto else "producto no existe en catálogo"

    # Coincidencia conservadora para códigos/productos futuros. Se comparan tanto
    # el nombre interno como el alias del inventario oficial y se exige una única
    # mejor coincidencia compatible con la presentación xN.
    from .excel_importer import empaques_compatibles
    from .inventario import RENOMBRAR_CATALOGO
    permitidas = {"Impulsivo", "Por Kilos", "Fanee", "Extras"}
    stop = {"grido", "unidad", "unid", "pack", "caja", "cajas", "expo", "py"}
    candidatos = []
    for producto in Producto.query.filter(Producto.categoria.in_(permitidas)).all():
        variantes = {producto.nombre, RENOMBRAR_CATALOGO.get(producto.nombre, "")}
        mejor = 0
        for variante in variantes:
            if not variante or not empaques_compatibles(variante, linea.descripcion):
                continue
            tokens = [t for t in _norm(variante).split() if len(t) >= 3 and t not in stop and not t.isdigit()]
            if not tokens:
                continue
            presentes = sum(1 for token in tokens if re.search(rf"\b{re.escape(token)}\b", normal))
            cobertura = presentes / len(tokens)
            if cobertura == 1 and (len(tokens) >= 2 or len(tokens[0]) >= 6):
                mejor = max(mejor, len(tokens) * 10 + len(_norm(variante)))
        if mejor:
            candidatos.append((mejor, producto))
    candidatos.sort(key=lambda item: item[0], reverse=True)
    if candidatos and (len(candidatos) == 1 or candidatos[0][0] > candidatos[1][0]):
        return candidatos[0][1], "coincidencia de descripción"
    return None, "sin coincidencia confiable"


def importar_factura(
    *, periodo: InventarioPeriodo, cliente_id: str, usuario: str,
    nombre_archivo: str, contenido: bytes, orden_carga: int = 0,
) -> tuple[FacturaCompra | None, list[str]]:
    if len(contenido) > MAX_PDF_BYTES:
        raise FacturaError("Cada factura puede pesar como máximo 15 MB.")
    digest = hashlib.sha256(contenido).hexdigest()
    existente = FacturaCompra.query.filter_by(cliente_id=cliente_id, sha256=digest).first()
    if existente:
        return None, [f"{nombre_archivo}: factura duplicada; ya fue cargada en el período #{existente.periodo.numero}."]

    extraida = extraer_factura(contenido)
    fecha_desde = datetime.strptime(periodo.fecha_desde, "%Y-%m-%d").date()
    fecha_hasta = datetime.strptime(periodo.fecha_hasta, "%Y-%m-%d").date()
    en_rango = bool(extraida.fecha_emision and fecha_desde <= extraida.fecha_emision <= fecha_hasta)
    factura = FacturaCompra(
        periodo_id=periodo.id, cliente_id=cliente_id, proveedor=extraida.proveedor,
        numero_factura=extraida.numero, fecha_emision=extraida.fecha_emision,
        nombre_archivo=nombre_archivo[:255], sha256=digest, archivo_pdf=contenido,
        # El administrador elige expresamente el período al cargar la factura.
        # La fecha se valida y advierte, pero no debe hacer que Auditoría ignore
        # silenciosamente una compra confirmada dentro de ese período.
        metodo_extraccion=extraida.metodo, estado="procesada",
        total_factura=extraida.total, usuario_importador=usuario,
        texto_extraido=extraida.texto[:100_000], orden_carga=max(0, int(orden_carga)),
    )
    db.session.add(factura)
    db.session.flush()

    permitidas = {"Impulsivo", "Por Kilos", "Fanee", "Extras"}
    avisos = []
    if not en_rango:
        avisos.append(
            f"{nombre_archivo}: la fecha de emisión no coincide con el rango del período; "
            "se aplicará al período seleccionado."
        )
    for linea in extraida.lineas:
        producto, motivo = _buscar_producto(extraida.proveedor, linea)
        factor, fuente_factor = _resolver_factor_conversion(
            extraida.proveedor, linea, producto, cliente_id,
        )
        estado = "vinculado" if producto else "pendiente"
        if producto and producto.categoria not in permitidas:
            estado = "categoria_invalida"
            motivo = f"{extraida.proveedor} no corresponde a {producto.categoria}"
        if extraida.proveedor == "Fane" and linea.codigo == "7840263015693":
            estado = "pendiente_conversion"
            motivo = "la presentación de servilletas requiere confirmar el factor UME"
        calculadas = calcular_compras_unidades(linea.cantidad, factor)
        db.session.add(FacturaCompraDetalle(
            factura_id=factura.id, codigo_proveedor=linea.codigo[:40],
            descripcion=linea.descripcion[:255], cantidad_facturada=linea.cantidad,
            factor_conversion=factor, compras_calculadas=calculadas,
            precio_unitario=linea.precio_unitario, importe=linea.importe,
            producto_id=producto.id if producto else None,
            producto_nombre=producto.nombre if producto else None,
            estado_vinculacion=estado, confianza="Alta" if producto else "Baja",
            observacion=f"{motivo}; {fuente_factor}"[:255],
        ))
        if estado != "vinculado":
            avisos.append(f"{linea.descripcion}: {motivo}.")
    return factura, avisos


def aplicar_compras_facturas(periodo: InventarioPeriodo, cliente_id: str, usuario: str) -> dict:
    excel = (
        ExcelImportado.query.filter_by(periodo_id=periodo.id, cliente_id=cliente_id)
        .filter(ExcelImportado.estado_validacion.in_(("ok", "pendiente_vinculacion")))
        .order_by(ExcelImportado.id.desc()).first()
    )
    if not excel:
        raise FacturaError("Primero importa el inventario XLS/XLSX del período.")

    # Reparar importaciones creadas con versiones anteriores: una fecha de
    # emisión distinta dejaba todas las líneas fuera de rango y los catálogos
    # que usan alias quedaban sin producto. La asignación explícita al período
    # y el código del proveedor permiten reconciliarlas de forma determinista.
    facturas = FacturaCompra.query.filter_by(
        periodo_id=periodo.id, cliente_id=cliente_id,
    ).all()
    for factura in facturas:
        if factura.estado == "fuera_rango":
            factura.estado = "procesada"
        permitidas = {"Impulsivo", "Por Kilos", "Fanee", "Extras"}
        for detalle in factura.detalles:
            if detalle.producto_id is None and detalle.estado_vinculacion in ("pendiente", "fuera_rango"):
                producto, motivo = _buscar_producto(
                    factura.proveedor,
                    LineaExtraida(
                        codigo=detalle.codigo_proveedor,
                        descripcion=detalle.descripcion,
                        cantidad=detalle.cantidad_facturada,
                        precio_unitario=detalle.precio_unitario,
                        importe=detalle.importe,
                    ),
                )
                if producto and producto.categoria in permitidas:
                    detalle.producto_id = producto.id
                    detalle.producto_nombre = producto.nombre
                    detalle.estado_vinculacion = "vinculado"
                    detalle.confianza = "Alta"
                    detalle.observacion = f"{motivo}; reconciliada al aplicar compras"[:255]
            if detalle.estado_vinculacion == "fuera_rango":
                detalle.estado_vinculacion = "vinculado" if detalle.producto_id else "pendiente"
            # Repara factores heredados o extraídos del PDF. Las correcciones
            # que un administrador confirmó expresamente se conservan.
            if (
                factura.proveedor == "Helacor"
                and detalle.producto_id is not None
                and detalle.confianza != "Confirmada"
            ):
                producto = db.session.get(Producto, detalle.producto_id)
                factor_catalogo = factor_conversion_catalogo(producto, cliente_id)
                if factor_catalogo is not None:
                    detalle.factor_conversion, fuente = factor_catalogo
                    detalle.compras_calculadas = calcular_compras_unidades(
                        detalle.cantidad_facturada, detalle.factor_conversion,
                    )
                    detalle.observacion = f"{fuente}; conversión sincronizada"[:255]
    db.session.flush()

    detalles_periodo = (
        FacturaCompraDetalle.query.join(FacturaCompra)
        .filter(
            FacturaCompra.periodo_id == periodo.id,
            FacturaCompra.cliente_id == cliente_id,
        )
        .all()
    )
    incompletas = []
    for detalle in detalles_periodo:
        if detalle.estado_vinculacion == "fuera_rango":
            continue
        cantidad = float(detalle.cantidad_facturada or 0)
        factor = float(detalle.factor_conversion or 0)
        if (
            detalle.producto_id is None
            or detalle.estado_vinculacion not in ("vinculado", "aplicado")
            or not math.isfinite(cantidad) or cantidad < 0
            or not math.isfinite(factor) or factor <= 0
        ):
            incompletas.append(detalle)
    if incompletas:
        raise FacturaError(
            f"No se aplicaron compras: completa y guarda las {len(incompletas)} "
            "línea(s) marcadas para revisión."
        )

    filas = (
        FacturaCompraDetalle.query.join(FacturaCompra)
        .filter(FacturaCompra.periodo_id == periodo.id, FacturaCompra.cliente_id == cliente_id,
                FacturaCompraDetalle.estado_vinculacion.in_(("vinculado", "aplicado")),
                FacturaCompraDetalle.producto_id.isnot(None)).all()
    )
    if not filas:
        raise FacturaError("No hay compras vinculadas y válidas para aplicar.")

    totales: dict[int, float] = {}
    for fila in filas:
        # Recalcular siempre desde los campos que ve y confirma el usuario. Así
        # Auditoría nunca reutiliza un total cacheado antes de una corrección.
        cantidad = calcular_compras_unidades(
            fila.cantidad_facturada, fila.factor_conversion,
        )
        if abs(float(fila.compras_calculadas or 0) - cantidad) > 1e-9:
            fila.compras_calculadas = cantidad
        totales[fila.producto_id] = totales.get(fila.producto_id, 0.0) + cantidad

    detalles_excel = ExcelDetalle.query.filter_by(excel_id=excel.id).all()
    vinculados_excel = {d.producto_id: d for d in detalles_excel if d.producto_id}
    cambios = 0
    no_encontrados = []
    for producto_id, cantidad in totales.items():
        detalle = vinculados_excel.get(producto_id)
        if not detalle:
            producto = db.session.get(Producto, producto_id)
            no_encontrados.append(producto.nombre if producto else str(producto_id))
            continue
        anterior = float(detalle.compras or 0)
        if abs(anterior - cantidad) > 1e-9:
            detalle.compras = cantidad
            db.session.add(ExcelDetalleEdicion(
                cliente_id=cliente_id, periodo_id=periodo.id, excel_id=excel.id,
                detalle_id=detalle.id, usuario=usuario,
                cambios_json=json.dumps({
                    "origen": "facturas_pdf",
                    "compras": {"anterior": anterior, "nuevo": cantidad},
                }, ensure_ascii=False),
            ))
            cambios += 1
    for fila in filas:
        if fila.producto_id in vinculados_excel:
            fila.estado_vinculacion = "aplicado"
    for factura in FacturaCompra.query.filter_by(periodo_id=periodo.id, cliente_id=cliente_id).all():
        if factura.estado != "fuera_rango":
            pendientes = any(
                detalle.estado_vinculacion not in ("aplicado", "fuera_rango")
                for detalle in factura.detalles
            )
            factura.estado = "aplicada_parcial" if pendientes else "aplicada"
    return {"cambios": cambios, "productos": len(totales), "no_encontrados": no_encontrados, "excel_id": excel.id}
