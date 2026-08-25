"""
Importador del inventario XLS/XLSX de Documentación Oficial.
Lee las columnas estándar y crea los registros ExcelImportado + ExcelDetalle.
Usa 'articulo' como clave de integración; vincula con producto interno cuando es posible.
"""
from __future__ import annotations

import io
import re
import unicodedata
from typing import Optional

from .models import db, ExcelImportado, ExcelDetalle, InventarioPeriodo, Producto

# Columnas reconocidas del inventario oficial (nombres en minúsculas, sin acentos).
# Los campos auxiliares del proveedor se detectan para compatibilidad y para
# excluir grupos no auditables, pero no forman parte del inventario procesado.
_COL_MAP = {
    "articulo": ["articulo", "art", "codigo", "cod"],
    "artdescrip": ["artdescrip", "descripcion", "nombre", "producto"],
    "stockinicial": ["stockinicial", "stock inicial", "si"],
    "compras": ["compras", "compra"],
    "otrosingresos": ["otrosingresos", "otros ingresos", "ingreso"],
    "otrassalidas": ["otrassalidas", "otras salidas", "salida"],
    "stockfinal": ["stockfinal", "stock final", "sf"],
    "ventateorica": ["ventateorica", "venta teorica", "vt"],
    "ventareal": ["ventareal", "venta real", "vr"],
    "diferencia": ["diferencia", "dif"],
    "importedesvio": ["importedesvio", "importe desvio", "desvio"],
    "kilos": ["kilos", "kg"],
    "unidades": ["unidades", "unid"],
    "grupo": ["grupo"],
    "grudescrip": [
        "grudescrip", "grupo descrip", "grupo descripcion",
        "depdescrip", "dep descrip", "departamento descripcion",
    ],
}

_COLUMNAS_DESCARTADAS = {
    "porcentaje", "porcentaje_vtapos", "importedesvio", "kilos",
    "unidades", "grupo", "depdescrip", "desdefecha", "hastafecha",
    "kilosvta",
}

_COLUMNAS_OBLIGATORIAS = {
    "artdescrip", "stockinicial", "compras", "otrosingresos",
    "otrassalidas", "stockfinal", "ventareal",
}

# Grupos a excluir (no se auditan)
_GRUPOS_EXCLUIR = {
    "canjes", "congelados", "frizzio", "promociones",
    "limpiezayotros", "limpieza", "otros",
}


def _norm(s: str) -> str:
    texto = unicodedata.normalize("NFKD", str(s or ""))
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch)).lower()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _norm_codigo(value) -> str:
    """Normaliza códigos numéricos de XLS (p. ej. 38.0) sin alterar códigos alfanuméricos."""
    codigo = str(value or "").strip()
    if re.fullmatch(r"[+-]?\d+\.0+", codigo):
        codigo = codigo.split(".", 1)[0]
    return codigo.upper()


def _cantidades_empaque(nombre: str) -> set[int]:
    """Extrae presentaciones escritas como x54, x 78, ×120, etc."""
    texto = unicodedata.normalize("NFKD", str(nombre or "")).lower().replace("×", "x")
    return {int(valor) for valor in re.findall(r"(?<![a-z0-9])x\s*(\d+)\b", texto)}


def empaques_compatibles(nombre_catalogo: str, nombre_excel: str) -> bool:
    """Dos nombres con cantidades de empaque explícitas solo coinciden si comparten cantidad."""
    catalogo = _cantidades_empaque(nombre_catalogo)
    excel = _cantidades_empaque(nombre_excel)
    return not catalogo or not excel or bool(catalogo & excel)


def _detectar_columnas(headers: list[str]) -> dict[str, int]:
    """Mapea nombre_campo → índice de columna."""
    h_norm = [_norm(h) for h in headers]
    resultado: dict[str, int] = {}
    for campo, aliases in _COL_MAP.items():
        for alias in aliases:
            try:
                idx = h_norm.index(alias)
                resultado[campo] = idx
                break
            except ValueError:
                pass
    return resultado


def _safe_float(value) -> Optional[float]:
    try:
        if value is None or str(value).strip() in ("", "-", "N/A"):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        texto = str(value).strip().replace(" ", "")
        negativo = texto.startswith("(") and texto.endswith(")")
        if negativo:
            texto = texto[1:-1]
        texto = re.sub(r"[^0-9,\.\-+]", "", texto)
        if "," in texto and "." in texto:
            if texto.rfind(",") > texto.rfind("."):
                texto = texto.replace(".", "").replace(",", ".")
            else:
                texto = texto.replace(",", "")
        elif "," in texto:
            texto = texto.replace(",", ".")
        numero = float(texto)
        return -numero if negativo else numero
    except (ValueError, TypeError):
        return None


def _build_nombre_map(cliente_id: str) -> dict[str, str]:
    """Mapa nombre_normalizado → nombre_original para todos los Producto."""
    productos = Producto.query.all()
    return {_norm(p.nombre): p.nombre for p in productos}


def _build_codigo_map() -> dict[str, str]:
    """Mapa codigo_articulo → nombre_original para productos que tienen código asignado."""
    productos = Producto.query.filter(Producto.codigo_articulo.isnot(None)).all()
    return {_norm_codigo(p.codigo_articulo): p.nombre for p in productos}


def _build_alias_map(nombre_map: dict[str, str]) -> dict[str, str]:
    """Mapea nombres conocidos del Excel al nombre vigente del catálogo."""
    from .inventario import RENOMBRAR_CATALOGO

    aliases: dict[str, str] = {}
    for nombre_catalogo, nombre_excel in RENOMBRAR_CATALOGO.items():
        nombre_real = nombre_map.get(_norm(nombre_catalogo))
        if nombre_real and empaques_compatibles(nombre_real, nombre_excel):
            aliases[_norm(nombre_excel)] = nombre_real
    return aliases


def _vincular_producto(articulo: str, artdescrip: str,
                       codigo_map: dict[str, str],
                       nombre_map: dict[str, str],
                       alias_map: Optional[dict[str, str]] = None) -> Optional[str]:
    """
    Prioridad de vinculación:
    1. articulo vs productos.codigo_articulo  (clave estable)
    2. artdescrip exacto vs productos.nombre  (normalizado)
    3. artdescrip parcial vs productos.nombre
    4. None → pendiente de vinculación manual
    """
    # 1. Por código de artículo
    codigo = _norm_codigo(articulo)
    if codigo and codigo in codigo_map:
        candidato = codigo_map[codigo]
        if empaques_compatibles(candidato, artdescrip):
            return candidato

    artdescrip_norm = _norm(artdescrip)

    # 2. Nombre exacto
    if artdescrip_norm in nombre_map:
        return nombre_map[artdescrip_norm]

    # 3. Alias explícito entre el catálogo interno y el nombre del Excel.
    if alias_map and artdescrip_norm in alias_map:
        return alias_map[artdescrip_norm]

    # 4. Nombre parcial conservador. Solo nombres compuestos y coincidencia
    # completa dentro de la descripción; evita asociar cualquier producto que
    # contenga "chocolate" con el producto genérico Chocolate.
    coincidencias: list[str] = []
    for k, v in nombre_map.items():
        if len(k.split()) < 2 or len(k) < 8:
            continue
        if not empaques_compatibles(v, artdescrip):
            continue
        if artdescrip_norm.startswith(k + " ") or artdescrip_norm.endswith(" " + k):
            coincidencias.append(v)
        elif f" {k} " in f" {artdescrip_norm} ":
            coincidencias.append(v)
    coincidencias = list(dict.fromkeys(coincidencias))
    if len(coincidencias) == 1:
        return coincidencias[0]

    return None


def _vincular_producto_publicado(articulo: str, artdescrip: str) -> Optional[Producto]:
    """Busca una coincidencia única entre productos publicados manualmente."""
    codigo = _norm_codigo(articulo)
    descripcion = _norm(artdescrip)
    candidatos = []
    for producto in Producto.query.filter(
        Producto.visible_empleado.is_(True),
        Producto.catalogo_version > 0,
    ).all():
        if codigo and _norm_codigo(producto.codigo_articulo) == codigo:
            candidatos.append(producto)
            continue
        nombre = _norm(producto.nombre)
        if len(nombre) < 4 or not empaques_compatibles(producto.nombre, artdescrip):
            continue
        coincide = descripcion == nombre or descripcion.startswith(nombre + " ")
        if len(nombre.split()) >= 2:
            coincide = (
                coincide
                or descripcion.endswith(" " + nombre)
                or f" {nombre} " in f" {descripcion} "
            )
        if coincide:
            candidatos.append(producto)
    unicos = {producto.id: producto for producto in candidatos}
    return next(iter(unicos.values())) if len(unicos) == 1 else None


def corregir_vinculaciones_empaque(excel_id: int) -> int:
    """Desvincula relaciones históricas xN/xM incompatibles del Excel indicado."""
    detalles = ExcelDetalle.query.filter_by(excel_id=excel_id).filter(
        ExcelDetalle.producto_id.isnot(None)
    ).all()
    corregidos = 0
    for detalle in detalles:
        producto = db.session.get(Producto, detalle.producto_id)
        if not producto or empaques_compatibles(producto.nombre, detalle.artdescrip):
            continue
        if (
            producto.codigo_articulo
            and _norm_codigo(producto.codigo_articulo) == _norm_codigo(detalle.articulo)
        ):
            producto.codigo_articulo = None
        detalle.producto_id = None
        detalle.producto_nombre_interno = None
        detalle.estado_vinculacion = "pendiente"
        corregidos += 1
    if corregidos:
        excel = db.session.get(ExcelImportado, excel_id)
        if excel:
            excel.estado_validacion = "pendiente_vinculacion"
            excel.productos_nuevos = max(int(excel.productos_nuevos or 0), corregidos)
    return corregidos


def revincular_detalles_pendientes(cliente_id: str) -> int:
    """Reintenta filas pendientes después de crear o sincronizar el catálogo."""
    excels = ExcelImportado.query.filter_by(cliente_id=cliente_id).filter(
        ExcelImportado.estado_validacion.in_(("ok", "pendiente_vinculacion"))
    ).all()
    if not excels:
        return 0

    nombre_map = _build_nombre_map(cliente_id)
    codigo_map = _build_codigo_map()
    alias_map = _build_alias_map(nombre_map)
    vinculados = 0

    for excel in excels:
        detalles = ExcelDetalle.query.filter_by(excel_id=excel.id).all()
        for detalle in detalles:
            if detalle.excluido_auditoria:
                producto_publicado = _vincular_producto_publicado(
                    detalle.articulo,
                    detalle.artdescrip,
                )
                if producto_publicado is None:
                    continue
                detalle.excluido_auditoria = False
                detalle.motivo_exclusion = None
                detalle.producto_id = producto_publicado.id
                detalle.producto_nombre_interno = producto_publicado.nombre
                detalle.estado_vinculacion = "vinculado"
                if detalle.articulo and not producto_publicado.codigo_articulo:
                    producto_publicado.codigo_articulo = _norm_codigo(detalle.articulo)
                vinculados += 1
                continue
            producto_actual = (
                db.session.get(Producto, detalle.producto_id)
                if detalle.producto_id else None
            )
            if (
                detalle.estado_vinculacion == "vinculado"
                and producto_actual is not None
                and empaques_compatibles(producto_actual.nombre, detalle.artdescrip)
            ):
                continue

            nombre = _vincular_producto(
                detalle.articulo,
                detalle.artdescrip,
                codigo_map,
                nombre_map,
                alias_map,
            )
            producto = Producto.query.filter_by(nombre=nombre).first() if nombre else None
            if producto is None:
                detalle.producto_id = None
                detalle.producto_nombre_interno = None
                detalle.estado_vinculacion = "sin_producto"
                continue

            detalle.producto_id = producto.id
            detalle.producto_nombre_interno = producto.nombre
            detalle.estado_vinculacion = "vinculado"
            if detalle.articulo and not producto.codigo_articulo:
                producto.codigo_articulo = _norm_codigo(detalle.articulo)
                codigo_map[_norm_codigo(detalle.articulo)] = producto.nombre
            vinculados += 1

        pendientes = sum(
            not d.excluido_auditoria and d.estado_vinculacion != "vinculado"
            for d in detalles
        )
        excel.productos_nuevos = pendientes
        excel.estado_validacion = "pendiente_vinculacion" if pendientes else "ok"

    return vinculados


def descartar_detalles_sin_producto(excel_id: int) -> int:
    """Excluye de Auditoría las filas que ya se confirmó que no tienen producto."""
    excel = db.session.get(ExcelImportado, excel_id)
    if excel is None:
        return 0

    descartados = 0
    detalles = ExcelDetalle.query.filter_by(excel_id=excel.id).all()
    for detalle in detalles:
        if detalle.estado_vinculacion != "sin_producto" or detalle.excluido_auditoria:
            continue
        detalle.excluido_auditoria = True
        detalle.motivo_exclusion = "Sin producto coincidente; descartado automáticamente"
        descartados += 1

    pendientes = sum(
        not detalle.excluido_auditoria
        and detalle.estado_vinculacion != "vinculado"
        for detalle in detalles
    )
    excel.productos_nuevos = pendientes
    excel.estado_validacion = "pendiente_vinculacion" if pendientes else "ok"
    return descartados


def _ultimos_excel_validos(cliente_id: str) -> list[ExcelImportado]:
    """Devuelve solo la importación vigente de cada período del cliente."""
    ultimos = (
        db.session.query(db.func.max(ExcelImportado.id))
        .filter(
            ExcelImportado.cliente_id == cliente_id,
            ExcelImportado.estado_validacion.in_(("ok", "pendiente_vinculacion")),
        )
        .group_by(ExcelImportado.periodo_id)
        .all()
    )
    ids = [fila[0] for fila in ultimos if fila[0] is not None]
    if not ids:
        return []
    return ExcelImportado.query.filter(ExcelImportado.id.in_(ids)).all()


def contar_detalles_pendientes(cliente_id: str) -> int:
    """Cuenta filas vigentes del Excel que todavía no están vinculadas."""
    excels = _ultimos_excel_validos(cliente_id)
    ids = [excel.id for excel in excels]
    if not ids:
        return 0
    return ExcelDetalle.query.filter(
        ExcelDetalle.excel_id.in_(ids),
        ExcelDetalle.excluido_auditoria.is_(False),
        ExcelDetalle.estado_vinculacion != "vinculado",
    ).count()


def contar_detalles_revinculables(cliente_id: str) -> int:
    """Cuenta filas pendientes que el catálogo actual ya permite vincular, sin modificar datos."""
    excels = _ultimos_excel_validos(cliente_id)
    if not excels:
        return 0
    nombre_map = _build_nombre_map(cliente_id)
    codigo_map = _build_codigo_map()
    alias_map = _build_alias_map(nombre_map)
    total = 0
    for excel in excels:
        for detalle in ExcelDetalle.query.filter_by(excel_id=excel.id).all():
            if detalle.excluido_auditoria:
                if _vincular_producto_publicado(detalle.articulo, detalle.artdescrip):
                    total += 1
                continue
            if detalle.estado_vinculacion == "vinculado":
                continue
            nombre = _vincular_producto(
                detalle.articulo,
                detalle.artdescrip,
                codigo_map,
                nombre_map,
                alias_map,
            )
            if nombre and Producto.query.filter_by(nombre=nombre).first():
                total += 1
    return total


def importar_excel(
    periodo_id: int,
    cliente_id: str,
    usuario: str,
    filename: str,
    contenido: bytes,
) -> tuple[ExcelImportado, list[str]]:
    """
    Parsea el inventario oficial, crea ExcelImportado y sus ExcelDetalle.
    Retorna (excel_importado, lista_de_advertencias).
    Los ExcelDetalle no se agregan a la sesión de BD hasta que el llamador hace db.session.commit().
    """
    advertencias: list[str] = []

    # Leer Excel con openpyxl o xlrd según extensión
    rows: list[list] = _leer_excel(contenido, filename)
    if not rows:
        raise ValueError("El archivo no contiene filas o no pudo ser leído.")

    # Detectar fila de cabeceras (primera fila con texto)
    header_row_idx = 0
    col_map: dict[str, int] = {}
    for i, row in enumerate(rows):
        col_map = _detectar_columnas([str(c) for c in row])
        if "artdescrip" in col_map or "articulo" in col_map:
            header_row_idx = i
            break

    if not col_map:
        raise ValueError(
            "No se pudieron detectar las columnas del Excel. "
            "Verificá que el archivo tenga los encabezados correctos."
        )

    data_rows = rows[header_row_idx + 1:]
    faltantes = sorted(_COLUMNAS_OBLIGATORIAS - set(col_map))
    if faltantes:
        raise ValueError(
            "Faltan columnas obligatorias del inventario oficial: " + ", ".join(faltantes)
        )
    nombre_map = _build_nombre_map(cliente_id)
    codigo_map = _build_codigo_map()
    alias_map = _build_alias_map(nombre_map)

    ei = ExcelImportado(
        periodo_id=periodo_id,
        cliente_id=cliente_id,
        nombre_archivo=filename,
        usuario_importador=usuario,
        estado_validacion="ok",
        productos_nuevos=0,
    )
    db.session.add(ei)
    db.session.flush()  # para obtener ei.id

    productos_nuevos = 0
    filas_procesadas = 0

    for row in data_rows:
        def _get(campo: str):
            idx = col_map.get(campo)
            if idx is None or idx >= len(row):
                return None
            return row[idx]

        artdescrip = _norm(str(_get("artdescrip") or ""))
        if not artdescrip:
            continue

        # Detectar si es grupo no auditable (se guarda con excluido_auditoria=True)
        grupo = _norm(str(_get("grupo") or ""))
        grudescrip = _norm(str(_get("grudescrip") or ""))
        grupo_excluido = next(
            (ex for ex in _GRUPOS_EXCLUIR if ex in grupo or ex in grudescrip), None
        )

        articulo = _norm_codigo(_get("articulo"))
        stockinicial = _safe_float(_get("stockinicial")) or 0.0
        compras = _safe_float(_get("compras")) or 0.0
        otrosingresos = _safe_float(_get("otrosingresos")) or 0.0
        otrassalidas = _safe_float(_get("otrassalidas")) or 0.0
        stockfinal = _safe_float(_get("stockfinal")) or 0.0
        ventateorica = _safe_float(_get("ventateorica")) or 0.0
        ventareal = _safe_float(_get("ventareal")) or 0.0
        diferencia = _safe_float(_get("diferencia")) or 0.0
        # Vincular: código primero, luego nombre exacto, luego parcial
        nombre_interno = _vincular_producto(
            articulo, str(_get("artdescrip") or ""), codigo_map, nombre_map, alias_map
        )
        if grupo_excluido:
            producto_publicado = _vincular_producto_publicado(
                articulo,
                str(_get("artdescrip") or ""),
            )
            if producto_publicado is not None:
                nombre_interno = producto_publicado.nombre
                grupo_excluido = None
        if nombre_interno is None and articulo:
            propietario_codigo = Producto.query.filter_by(codigo_articulo=articulo).first()
            if propietario_codigo and not empaques_compatibles(
                propietario_codigo.nombre, str(_get("artdescrip") or "")
            ):
                propietario_codigo.codigo_articulo = None
                codigo_map.pop(articulo, None)
                advertencias.append(
                    f"Código {articulo} desvinculado de '{propietario_codigo.nombre}': "
                    "la cantidad de empaque no coincide."
                )
        # Si se encontró, resolver producto_id y actualizar codigo_articulo si faltaba
        prod_id: Optional[int] = None
        if nombre_interno and not grupo_excluido:
            p = Producto.query.filter_by(nombre=nombre_interno).first()
            if p:
                prod_id = p.id
                if articulo and not p.codigo_articulo:
                    p.codigo_articulo = articulo
        if nombre_interno is None and not grupo_excluido:
            productos_nuevos += 1
            advertencias.append(
                f"Producto no vinculado: '{_get('artdescrip')}' (código: {articulo}). "
                f"Requiere alta o vinculación manual."
            )

        if grupo_excluido:
            estado_vinc = "excluido"
        elif prod_id:
            estado_vinc = "vinculado"
        elif not nombre_interno:
            estado_vinc = "sin_producto"
        else:
            estado_vinc = "pendiente"

        ed = ExcelDetalle(
            excel_id=ei.id,
            articulo=articulo,
            artdescrip=str(_get("artdescrip") or ""),
            stockinicial=stockinicial,
            compras=compras,
            otrosingresos=otrosingresos,
            otrassalidas=otrassalidas,
            stockfinal=stockfinal,
            ventateorica=ventateorica,
            ventareal=ventareal,
            diferencia=diferencia,
            # Las columnas auxiliares del archivo oficial se usan, cuando
            # corresponde, antes de este punto y se descartan del resultado.
            importedesvio=0.0,
            kilos=0.0,
            unidades=0.0,
            grupo="",
            grudescrip="",
            producto_nombre_interno=nombre_interno if not grupo_excluido else None,
            producto_id=prod_id,
            estado_vinculacion=estado_vinc,
            excluido_auditoria=bool(grupo_excluido),
            motivo_exclusion=f"Grupo excluido: {grupo_excluido}" if grupo_excluido else None,
        )
        db.session.add(ed)
        filas_procesadas += 1

    ei.productos_nuevos = productos_nuevos
    if productos_nuevos > 0:
        ei.estado_validacion = "pendiente_vinculacion"

    return ei, advertencias


def importar_excel_transaccional(
    periodo_id: int,
    cliente_id: str,
    usuario: str,
    filename: str,
    contenido: bytes,
) -> tuple[ExcelImportado, list[str]]:
    """Importa todo o revierte y conserva únicamente una cabecera ``fallido``."""
    try:
        ei, advertencias = importar_excel(
            periodo_id=periodo_id,
            cliente_id=cliente_id,
            usuario=usuario,
            filename=filename,
            contenido=contenido,
        )
        db.session.commit()
        return ei, advertencias
    except Exception:
        db.session.rollback()
        try:
            db.session.add(ExcelImportado(
                periodo_id=periodo_id,
                cliente_id=cliente_id,
                nombre_archivo=filename,
                usuario_importador=usuario,
                estado_validacion="fallido",
                productos_nuevos=0,
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
        raise


def _leer_excel(contenido: bytes, filename: str) -> list[list]:
    """Lee el contenido binario y devuelve lista de filas (listas de celdas)."""
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext in ("xlsx", "xlsm"):
        try:
            import openpyxl
        except ImportError:
            raise ImportError("openpyxl no está instalado. Ejecutá: pip install openpyxl")
        wb = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True)
        ws = wb.active
        if ws is None:
            raise ValueError("El archivo Excel no contiene hojas.")
        return [[cell.value for cell in row] for row in ws.iter_rows()]
    elif ext in ("xls",):
        try:
            import xlrd
        except ImportError:
            raise ImportError("xlrd no está instalado. Ejecutá: pip install xlrd")
        wb = xlrd.open_workbook(file_contents=contenido)
        ws = wb.sheet_by_index(0)
        return [list(ws.row_values(i)) for i in range(ws.nrows)]
    else:
        raise ValueError(f"Formato de archivo no soportado: {ext}. Usá .xlsx o .xls")
