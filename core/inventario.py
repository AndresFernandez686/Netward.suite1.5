"""
inventario.py — Módulo Desc.: procesamiento de Excel de inventario por período.

Flujo completo:
  1. Admin sube .xls/.xlsx de inventario + elige tienda y rango de fechas.
  2. Sistema limpia columnas irrelevantes y filtra grupos no relevantes.
    3. Regla de continuidad por período:
      - Si existe stock cargado por el empleado en el sistema → usa ese valor como SI.
      - Si no existe en sistema y hay snapshot previo del mismo mes/tienda → usa su stock_final como SI.
  4. Reemplaza ventas reales con DeliveryVenta del período.
  5. Recalcula venta teórica y diferencia.
  6. Agrega columnas: separador vacío | unid_por_caja | unid_por_bulto.
  7. Guarda snapshot con el stock_final procesado (para el próximo inventario).
  8. Descarga .xlsx coloreado.
"""
import io
import json
import unicodedata
from datetime import date, datetime
from typing import Optional, Tuple

import openpyxl
import openpyxl.utils
from openpyxl.styles import Font, PatternFill, Alignment
from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, session, url_for, send_file)

desc_bp = Blueprint("desc", __name__)

# ---------------------------------------------------------------------------
# Mapeo de columnas del Excel original (índices 0-based)
# ---------------------------------------------------------------------------
# Col  0 → grudescrip    usa para filtrar, luego ELIMINAR
# Col  1 → articulo      ELIMINAR
# Col  2 → artdescrip    MANTENER — clave de producto
# Col  3 → artcosto      ELIMINAR
# Col  4 → stockinicial  MANTENER — reemplazar
# Col  5 → compras       MANTENER — manual
# Col  6 → otrosingresos MANTENER — manual
# Col  7 → otrassalidas  MANTENER — manual
# Col  8 → stockfinal    MANTENER — manual
# Col  9 → ventateorica  MANTENER — recalcular
# Col 10 → ventareal     MANTENER — reemplazar
# Col 11 → diferencia    MANTENER — recalcular
# Col 12-22              ELIMINAR

COLS_MANTENER = [2, 4, 5, 6, 7, 8, 9, 10, 11]   # sin unidades (col16)

LABELS_SALIDA = [
    "Producto", "Stock Inicial", "Compras", "Otros Ingresos",
    "Otras Salidas", "Stock Final", "Venta Teorica", "Venta Real", "Diferencia",
]
# 3 columnas extra al final: separador | unid_x_caja | unid_x_bulto
LABELS_EXTRA = ["", "Unid. x Caja", "Cajas x Bulto"]

# Índices ORIGINALES
I_GRUPO     = 0
I_NOMBRE    = 2
I_SI        = 4
I_COMPRAS   = 5
I_OTROS_ING = 6
I_OTRAS_SAL = 7
I_SF        = 8
I_VT        = 9
I_VR        = 10
I_DIF       = 11

DEFAULT_LAYOUT = {
    "grupo": I_GRUPO,
    "nombre": I_NOMBRE,
    "si": I_SI,
    "compras": I_COMPRAS,
    "otros_ing": I_OTROS_ING,
    "otras_sal": I_OTRAS_SAL,
    "sf": I_SF,
    "vt": I_VT,
    "vr": I_VR,
    "dif": I_DIF,
}

# Índices en la fila YA FILTRADA
FI_NOMBRE    = 0
FI_SI        = 1
FI_COMPRAS   = 2
FI_OTROS_ING = 3
FI_OTRAS_SAL = 4
FI_SF        = 5
FI_VT        = 6
FI_VR        = 7
FI_DIF       = 8
# posiciones de las extras (índice 9, 10, 11)
FI_SEP       = 9
FI_UCAJA     = 10
FI_UBULTO    = 11

# Grupos del Excel que se EXCLUYEN siempre del output
GRUPOS_EXCLUIDOS = {
    "canjes", "congelados", "frizzio", "lineas especiales",
    "otros", "otros ingred.", "promociones",
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _requiere_admin():
    if session.get("rol") != "administrador":
        abort(403)


def _f(v):
    """Convierte a float de forma segura."""
    try:
        return float(v) if v not in (None, "", " ") else 0.0
    except (ValueError, TypeError):
        return 0.0


def _norm(nombre: str) -> str:
    """Normaliza para comparación: minúsculas + strip."""
    return str(nombre).strip().lower()


def _norm_header(value) -> str:
    """Normaliza encabezados para detectar columnas por nombre."""
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.replace("_", " ")
    return "".join(ch for ch in text if ch.isalnum())


def _detectar_layout(filas_raw: list) -> Tuple[dict, int]:
    """Detecta índices de columnas y la fila de encabezado real."""
    if not filas_raw:
        return dict(DEFAULT_LAYOUT), 0

    max_scan = min(len(filas_raw), 12)
    for header_idx in range(max_scan):
        header = [_norm_header(v) for v in filas_raw[header_idx]]
        idx = {h: i for i, h in enumerate(header) if h and h not in ("none",)}

        # Formato original esperado desde el sistema de inventario.
        if "grudescrip" in idx and "artdescrip" in idx and "stockinicial" in idx:
            return {
                "grupo": idx.get("grudescrip"),
                "nombre": idx.get("artdescrip"),
                "si": idx.get("stockinicial"),
                "compras": idx.get("compras"),
                "otros_ing": idx.get("otrosingresos"),
                "otras_sal": idx.get("otrassalidas"),
                "sf": idx.get("stockfinal"),
                "vt": idx.get("ventateorica"),
                "vr": idx.get("ventareal"),
                "dif": idx.get("diferencia"),
            }, header_idx

        # Formato ya procesado/exportado (Producto, Stock Inicial, ...).
        nombre_idx = idx.get("producto", idx.get("artdescrip"))
        procesado = {
            "grupo": None,
            "nombre": nombre_idx,
            "si": idx.get("stockinicial"),
            "compras": idx.get("compras"),
            "otros_ing": idx.get("otrosingresos"),
            "otras_sal": idx.get("otrassalidas"),
            "sf": idx.get("stockfinal"),
            "vt": idx.get("ventateorica"),
            "vr": idx.get("ventareal"),
            "dif": idx.get("diferencia"),
        }
        if all(procesado[k] is not None for k in ("nombre", "si", "compras", "otros_ing", "otras_sal", "sf", "vt", "vr", "dif")):
            return procesado, header_idx

    return dict(DEFAULT_LAYOUT), 0


def _leer_excel(contenido: bytes, filename: str) -> list:
    """Lee .xls o .xlsx y retorna lista de listas."""
    if filename.lower().endswith(".xls"):
        # xlrd es opcional y solo se necesita para archivos .xls.
        try:
            import xlrd
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Falta la dependencia 'xlrd' para leer archivos .xls. "
                "Instala con: pip install xlrd"
            ) from exc
        wb = xlrd.open_workbook(file_contents=contenido)
        ws = wb.sheet_by_index(0)
        return [list(ws.row_values(r)) for r in range(ws.nrows)]
    wb = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
    ws = wb.active
    assert ws is not None, "El archivo no tiene hojas activas"
    filas = [[c if c is not None else "" for c in row]
             for row in ws.iter_rows(values_only=True)]
    wb.close()
    return filas


# ---------------------------------------------------------------------------
# Consultas a la BD
# ---------------------------------------------------------------------------

def _stock_map(tienda_id: str) -> dict:
    """Retorna {nombre_norm: cantidad} desde InventarioItem (pendiente o sincronizado)."""
    from core.models import InventarioItem
    result = {}
    for item in InventarioItem.query.filter_by(tienda_id=tienda_id).all():
        k = _norm(item.producto)
        result[k] = result.get(k, 0.0) + _f(item.cantidad)
    return result


def _stock_map_periodo(periodo_id: int) -> dict:
    """Retorna {nombre_norm: cantidad} desde ConteoDetalle del período seleccionado."""
    from core.models import ConteoDetalle
    result = {}
    conteos = ConteoDetalle.query.filter_by(periodo_id=periodo_id).all()
    for c in conteos:
        if not c.fue_cargado:
            continue
        k = _norm(c.producto_nombre)
        result[k] = _f(c.total_unidad_base)
    return result


def _ventas_map(tienda_id: str, fecha_ini: str, fecha_fin: str, periodo_id: int | None = None) -> dict:
    """Retorna {nombre_norm: cantidad} desde DeliveryVenta en el período."""
    from sqlalchemy import and_, or_
    from core.models import DeliveryVenta
    filtro_periodo = and_(
        DeliveryVenta.periodo_id.is_(None),
        DeliveryVenta.estado_periodo != "fuera_rango",
        DeliveryVenta.fecha >= fecha_ini,
        DeliveryVenta.fecha <= fecha_fin,
    )
    if periodo_id is not None:
        filtro_periodo = or_(DeliveryVenta.periodo_id == periodo_id, filtro_periodo)
    result = {}
    for v in (DeliveryVenta.query
              .filter(DeliveryVenta.tienda_id == tienda_id, filtro_periodo)
              .all()):
        k = _norm(v.producto)
        result[k] = result.get(k, 0.0) + _f(v.cantidad)
    return result


def _precios_map() -> dict:
    """Retorna {nombre_norm: (unid_caja, unid_bulto)} desde ProductoPrecio."""
    from core.models import ProductoPrecio
    result = {}
    for p in ProductoPrecio.query.all():
        k = _norm(p.producto_nombre)
        result[k] = (_f(p.unidades_por_caja), _f(p.unidades_por_bulto))
    return result


def _snapshot_anterior(tienda_id: str, mes: str):
    """Retorna {nombre_norm: sf} del snapshot previo del mismo mes, o None."""
    from core.models import InventarioDescSnapshot
    snaps = (InventarioDescSnapshot.query
             .filter_by(tienda_id=tienda_id, mes=mes)
             .order_by(InventarioDescSnapshot.fecha_proceso.asc())
             .all())
    if not snaps:
        return None
    # Devuelve el más reciente disponible
    return json.loads(snaps[-1].stock_final_json)


def _guardar_snapshot(tienda_id: str, mes: str, fecha: str, sf_dict: dict):
    """Guarda o actualiza el snapshot del período procesado."""
    from core.models import InventarioDescSnapshot, db
    snap = InventarioDescSnapshot.query.filter_by(
        tienda_id=tienda_id, mes=mes, fecha_proceso=fecha).first()
    if snap is None:
        snap = InventarioDescSnapshot(tienda_id=tienda_id, mes=mes,
                                      fecha_proceso=fecha,
                                      stock_final_json=json.dumps(sf_dict))
        db.session.add(snap)
    else:
        snap.stock_final_json = json.dumps(sf_dict)
    db.session.commit()


# ---------------------------------------------------------------------------
# Procesamiento central
# ---------------------------------------------------------------------------

def _procesar_filas(filas_raw: list, stock_map: dict, ventas_map: dict,
                    prev_snapshot: Optional[dict], precios_map: dict):
    """
    Aplica toda la lógica de transformación.
    Devuelve (filas_procesadas, sf_dict, resumen).
    """
    if not filas_raw:
        return [], {}, {}

    layout, header_idx = _detectar_layout(filas_raw)
    datos = filas_raw[header_idx + 1:]   # omitir encabezado detectado
    filas_out  = []
    sf_out     = {}         # {nombre_norm: sf} para guardar snapshot
    n_si_snap  = 0          # productos con SI del snapshot anterior
    n_si_sys   = 0          # productos con SI del sistema
    n_vr       = 0          # productos con VR del sistema
    n_excl     = 0          # productos excluidos por grupo

    for fila in datos:
        indices_utiles = [v for v in layout.values() if v is not None]
        max_idx = max(indices_utiles) if indices_utiles else 0
        while len(fila) <= max_idx:
            fila.append(0.0)

        nombre = str(fila[layout["nombre"]]).strip()
        grupo = ""
        if layout["grupo"] is not None:
            grupo = str(fila[layout["grupo"]]).strip().lower()

        if not nombre:
            continue  # fila sin producto (totales, etc.)

        if grupo in GRUPOS_EXCLUIDOS:
            n_excl += 1
            continue

        key = _norm(nombre)

        # ── Stock inicial: sistema > snapshot > Excel original ─────────────
        if key in stock_map:
            fila[layout["si"]] = stock_map[key]
            n_si_sys += 1
        elif prev_snapshot and key in prev_snapshot:
            fila[layout["si"]] = prev_snapshot[key]
            n_si_snap += 1
        # else: se conserva el valor del Excel

        # ── Ventas reales ──────────────────────────────────────────────────
        if key in ventas_map:
            fila[layout["vr"]] = ventas_map[key]
            n_vr += 1

        # ── Venta teórica ──────────────────────────────────────────────────
        si   = _f(fila[layout["si"]])
        comp = _f(fila[layout["compras"]])
        oi   = _f(fila[layout["otros_ing"]])
        os_  = _f(fila[layout["otras_sal"]])
        sf   = _f(fila[layout["sf"]])
        vt   = round(si + comp + oi - sf - os_, 3)
        fila[layout["vt"]] = vt

        # ── Diferencia ────────────────────────────────────────────────────
        vr  = _f(fila[layout["vr"]])
        dif = round(vt - vr, 3)
        fila[layout["dif"]] = dif

        # ── Guardar SF para snapshot ───────────────────────────────────────
        sf_out[key] = sf

        # ── Columnas extra (precio admin) ──────────────────────────────────
        ucaja, ubulto = precios_map.get(key, (None, None))

        # ── Filtrar columnas de salida ─────────────────────────────────────
        fila_filtrada = [
            fila[layout["nombre"]],
            fila[layout["si"]],
            fila[layout["compras"]],
            fila[layout["otros_ing"]],
            fila[layout["otras_sal"]],
            fila[layout["sf"]],
            fila[layout["vt"]],
            fila[layout["vr"]],
            fila[layout["dif"]],
        ]
        # añadir separador + unidades
        fila_filtrada.append("")                                    # col 10 separador
        fila_filtrada.append(int(ucaja) if ucaja else "")           # col 11 unid_caja
        fila_filtrada.append(int(ubulto) if ubulto else "")         # col 12 unid_bulto
        filas_out.append(fila_filtrada)

    resumen = dict(
        total=len(filas_out),
        excluidos=n_excl,
        si_snap=n_si_snap,
        si_sys=n_si_sys,
        vr_sys=n_vr,
    )
    return filas_out, sf_out, resumen


# ---------------------------------------------------------------------------
# Generación del Excel de salida
# ---------------------------------------------------------------------------

def _generar_xlsx(filas_procesadas: list, fecha_proceso: str,
                  label_periodo: str) -> io.BytesIO:
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Inventario Procesado"

    # Estilos
    HDR_FILL  = PatternFill("solid", fgColor="1D4ED8")
    HDR_FONT  = Font(bold=True, color="FFFFFF", size=10)
    SIS_FILL  = PatternFill("solid", fgColor="DBEAFE")   # azul  → sistema
    SNAP_FILL = PatternFill("solid", fgColor="E0E7FF")   # violeta → snapshot
    CALC_FILL = PatternFill("solid", fgColor="D1FAE5")   # verde → calculado
    NEG_FILL  = PatternFill("solid", fgColor="FEE2E2")   # rojo  → negativo
    POS_FILL  = PatternFill("solid", fgColor="DCFCE7")   # verde → ok
    CENTER    = Alignment(horizontal="center", vertical="center")

    # Fila 1: encabezado principal
    header_row = LABELS_SALIDA + ["", fecha_proceso, label_periodo]
    ws.append(header_row)
    for cell in ws[1]:
        cell.fill      = HDR_FILL
        cell.font      = HDR_FONT
        cell.alignment = CENTER
    ws.row_dimensions[1].height = 22

    # Datos
    for fila in filas_procesadas:
        fila_fmt = []
        for v in fila:
            if isinstance(v, float) and v == int(v):
                fila_fmt.append(int(v))
            else:
                fila_fmt.append(v)
        ws.append(fila_fmt)

        rn = ws.max_row
        ws.cell(rn, FI_SI  + 1).fill  = SIS_FILL   # Stock Inicial
        ws.cell(rn, FI_VR  + 1).fill  = SIS_FILL   # Venta Real
        ws.cell(rn, FI_VT  + 1).fill  = CALC_FILL  # Venta Teórica
        dif_val = _f(fila[FI_DIF])
        ws.cell(rn, FI_DIF + 1).fill  = NEG_FILL if dif_val < 0 else POS_FILL

    # Anchos de columna
    anchos = {1: 42, 2: 14, 3: 12, 4: 16, 5: 16, 6: 12,
              7: 16, 8: 12, 9: 12, 10: 4, 11: 13, 12: 13}
    for col_idx, width in anchos.items():
        ws.column_dimensions[
            openpyxl.utils.get_column_letter(col_idx)
        ].width = width

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

@desc_bp.route("/admin/desc", methods=["GET", "POST"])
def admin_desc():
    _requiere_admin()
    from core.models import Tienda, InventarioDescSnapshot, Producto, InventarioPeriodo, ConteoDetalle

    cliente_id = session.get("cliente_id", "C001")
    tiendas = Tienda.query.filter_by(cliente_id=cliente_id).all()
    tiendas_map = {str(t.id): t.nombre for t in tiendas}
    periodos_disponibles = (
        InventarioPeriodo.query
        .filter_by(cliente_id=cliente_id)
        .order_by(InventarioPeriodo.id.desc())
        .all()
    )

    periodo_id_arg = request.args.get("periodo_id", type=int)
    periodo_seleccionado = next((p for p in periodos_disponibles if p.id == periodo_id_arg), None)
    if periodo_seleccionado is None and periodos_disponibles:
        periodo_seleccionado = periodos_disponibles[0]

    conteos_periodo = []
    if periodo_seleccionado is not None:
        conteos_periodo = (
            ConteoDetalle.query
            .filter_by(periodo_id=periodo_seleccionado.id)
            .order_by(ConteoDetalle.categoria, ConteoDetalle.producto_nombre)
            .all()
        )

    # Historial de snapshots para mostrar en la UI
    snapshots = (InventarioDescSnapshot.query
                 .order_by(InventarioDescSnapshot.creado.desc())
                 .limit(10).all())

    if request.method == "POST":
        archivo       = request.files.get("archivo")
        periodo_id    = request.form.get("periodo_id", type=int)

        periodo = (
            InventarioPeriodo.query
            .filter_by(id=periodo_id, cliente_id=cliente_id)
            .first()
        )
        if periodo is None:
            flash("Selecciona un período contable válido para procesar el Excel oficial.", "warning")
            return redirect(url_for("desc.admin_desc"))

        tienda_id = periodo.tienda_id
        fecha_ini = periodo.fecha_desde
        fecha_fin = periodo.fecha_hasta
        label_periodo = f"Periodo #{periodo.numero}"

        if not archivo or not archivo.filename:
            flash("Selecciona un archivo Excel antes de continuar.", "error")
            return redirect(url_for("desc.admin_desc", periodo_id=periodo.id))

        fname = archivo.filename
        if not (fname.lower().endswith(".xls") or fname.lower().endswith(".xlsx")):
            flash("Solo se permiten archivos .xlsx o .xls", "error")
            return redirect(url_for("desc.admin_desc", periodo_id=periodo.id))

        try:
            contenido = archivo.read()
            filas_raw = _leer_excel(contenido, fname)

            if len(filas_raw) < 2:
                flash("El archivo no contiene datos.", "error")
                return redirect(url_for("desc.admin_desc", periodo_id=periodo.id))

            # Determinar mes para regla de continuidad
            mes = fecha_fin[:7]   # YYYY-MM

            # Datos del período seleccionado (Periodo vs Excel oficial)
            sm   = _stock_map_periodo(periodo.id)
            vm   = _ventas_map(tienda_id, fecha_ini, fecha_fin, periodo.id) if tienda_id else {}
            pm   = _precios_map()
            prev = _snapshot_anterior(tienda_id, mes) if tienda_id else None

            # Procesar
            filas_proc, sf_dict, resumen = _procesar_filas(
                filas_raw, sm, vm, prev, pm)

            if not filas_proc:
                flash("No se encontraron filas válidas para procesar.", "warning")
                return redirect(url_for("desc.admin_desc", periodo_id=periodo.id))

            # Guardar snapshot
            if tienda_id and sf_dict:
                _guardar_snapshot(tienda_id, mes, fecha_fin, sf_dict)

            # Generar Excel
            buf = _generar_xlsx(filas_proc, fecha_fin, label_periodo)

            # Resumen flash
            continuidad = "snapshot anterior" if prev else "sistema (InventarioItem)"
            flash(
                f"Procesadas {resumen['total']} filas "
                f"({resumen['excluidos']} excluidas por grupo). "
                f"SI desde período ({periodo.numero}) / {continuidad}: {resumen['si_snap'] + resumen['si_sys']} prods. "
                f"VR desde sistema: {resumen['vr_sys']} prods.",
                "success",
            )

            tienda_nombre = tienda_id or "sintienda"
            return send_file(
                buf,
                as_attachment=True,
                download_name=f"inventario_{tienda_nombre}_{fecha_fin}.xlsx",
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        except Exception as exc:
            flash(f"Error al procesar: {exc}", "error")
            return redirect(url_for("desc.admin_desc", periodo_id=periodo.id))

    return render_template(
        "admin_desc.html",
        tiendas=tiendas,
        tiendas_map=tiendas_map,
        periodos_disponibles=periodos_disponibles,
        periodo_seleccionado=periodo_seleccionado,
        conteos_periodo=conteos_periodo,
        snapshots=snapshots,
        inventarios_procesados=InventarioDescSnapshot.query.count(),
        ultimo_snapshot=(snapshots[0] if snapshots else None),
        total_productos=Producto.query.count(),
        categorias_registradas=Producto.query.with_entities(Producto.categoria).distinct().count(),
        grupos_excluidos_count=len(GRUPOS_EXCLUIDOS),
        reglas_activas=3,
        hoy=date.today().isoformat(),
        primer_dia=date.today().replace(day=1).isoformat(),
    )



@desc_bp.route("/admin/desc/snapshot/<int:snap_id>/eliminar", methods=["POST"])
def desc_snapshot_eliminar(snap_id):
    _requiere_admin()
    from core.models import InventarioDescSnapshot, db
    snap = db.session.get(InventarioDescSnapshot, snap_id)
    if snap:
        db.session.delete(snap)
        db.session.commit()
        flash("Snapshot eliminado.", "info")
    return redirect(url_for("desc.admin_desc"))


# ---------------------------------------------------------------------------
# Sincronización de nombres: sistema → Excel
# ---------------------------------------------------------------------------

# Mapeo sistema (nombre actual) → Excel (nombre exacto leído por xlrd)
RENOMBRAR_CATALOGO = {
    # Impulsivo
    "Alfajor Almendrado":              "Almendrado x unidad",
    "Alfajor Bombon Crocante":         "Bombon crocante x unidad",
    "Alfajor Bombon Escoces":          "Bombon escoces x unidad",
    "Alfajor Bombon Suizo":            "Bombon suizo x unidad",
    "Alfajor Casatta":                 "Casatta x unidad",
    "Alfajor Bombon Cookies and Crema":"Alfajor cookies and cream x un.",
    "Familiar 1":                      "Familiar n\u2551 1 (chocolate/d.leche/americana)",
    "Familiar 2":                      "Familiar n\u2551 2 (chocolate/frutilla/dulce de leche)",
    "Familiar 3":                      "Familiar n\u2551 3 (vainilla/frutilla/granizado)",
    "Familiar 4":                      "Familiar n\u2551 4 (d.leche/frutilla/vainilla)",
    "Palito Bombon":                   "Palito bombon x unidad",
    "Palito Crema Americana":          "Palito cremoso americana x unidad",
    "Palito Crema Frutilla":           "Palito cremoso frutilla x unidad",
    "Palito Frutal Frutilla":          "Palito frutal frutilla x unidad",
    "Palito Frutal Limon":             "Palito frutal limon x unidad",
    "Palito Frutal Naranja":           "Palito frutal naranja x unidad",
    "Tentacion Chocolate":             "Tentacion 1 lt chocolate",
    "Tentacion Chocolate con Almendra":"Tentac 1 lt choco c/ almendras",
    "Tentacion Cookies":               "Tentacion 1 lt cookie",
    "Tentacion Crema Americana":       "Tentacion 1 lt crema americana",
    "Tentacion Dulce de Leche":        "Tentacion 1 lt dulce de leche",
    "Tentacion Dulce de Leche Granizado": "Tenta 1 lt ddl granizado",
    "Tentacion Frutilla":              "Tentacion 1 lt frutilla",
    "Tentacion Granizado":             "Tentacion 1 lt granizado",
    "Tentacion Limon":                 "Tentacion 1 lt limon",
    "Tentacion Menta Granizada":       "Tentacion 1 lt menta granizada",
    "Tentacion Vainilla":              "Tentacion 1 lt vainilla",
    "Torta Helada Cookies Mousse":     "Torta cookies mousse",
    "Torta Grido Rellena":             "Torta grido rellena",
    "Torta Milka":                     "Torta cookies and cream",
    "Torta Frutilla":                  "Torta frutillas con crema",
    # Extras
    "Bolsa 40x50":                     "Bolsa grido (40x50)",
    "Cucurucho Cascao x120":           "Cucurucho cascao chips x 120 u (nello)",
    "Cucurucho Nacional x54":          "Cucuruch\u2264n nacional x 78 u",
    "Isopor 1 kilo":                   "Isopor 1/1 grido",
    "Isopor 1/2 kilo":                 "Isopor de 1/2 grido",
    "Isopor 1/4":                      "Isopor de 1/4",
    "Servilleta Grido":                "Servilletas grido",
    "Tapa Burbuja Batido":             "Tapa burbuja de batido x 50 unid",
    "Vaso Batido":                     "Vaso grido batido",
    "Vaso Termico 240gr":              "Vaso termico 240 ml",
    "Vaso Sundae":                     "Vaso sundae (350 cc.)",
    "Vaso capuccino":                  "Vaso impreeso x 100",
}


def _calcular_plan_renombrado():
    """
    Devuelve lista de dicts con el plan de renombrado.
    accion: 'renombrar' | 'eliminar_duplicado' | 'conflicto'
    """
    from core.models import Producto
    existentes = {p.nombre: p for p in Producto.query.all()}
    existentes_lower = {k.lower(): v for k, v in existentes.items()}
    plan = []
    for nombre_sys, nombre_excel in RENOMBRAR_CATALOGO.items():
        prod = existentes.get(nombre_sys)
        if prod is None:
            plan.append({"de": nombre_sys, "a": nombre_excel,
                         "accion": "no_existe", "id": None})
            continue
        # ¿El nombre destino ya existe?
        destino_existe = existentes_lower.get(nombre_excel.lower())
        if destino_existe and destino_existe.id != prod.id:
            plan.append({"de": nombre_sys, "a": nombre_excel,
                         "accion": "eliminar_duplicado", "id": prod.id,
                         "id_destino": destino_existe.id})
        else:
            plan.append({"de": nombre_sys, "a": nombre_excel,
                         "accion": "renombrar", "id": prod.id})
    return plan


@desc_bp.route("/admin/desc/sincronizar", methods=["GET", "POST"])
def desc_sincronizar():
    _requiere_admin()
    from core.models import db, Producto, InventarioItem, ProductoPrecio, InventarioDescSnapshot

    if request.method == "POST":
        plan = _calcular_plan_renombrado()
        renombrados = 0
        eliminados  = 0
        errores     = []

        for item in plan:
            try:
                if item["accion"] == "renombrar":
                    prod = db.session.get(Producto, item["id"])
                    if prod is None:
                        continue
                    viejo = prod.nombre
                    nuevo = item["a"]
                    # Actualizar InventarioItem
                    InventarioItem.query.filter_by(producto=viejo).update({"producto": nuevo})
                    # Actualizar ProductoPrecio
                    pp = ProductoPrecio.query.filter_by(producto_nombre=viejo).first()
                    if pp:
                        pp.producto_nombre = nuevo
                    # Actualizar snapshots
                    for snap in InventarioDescSnapshot.query.all():
                        sf = json.loads(snap.stock_final_json)
                        viejo_key = viejo.strip().lower()
                        nuevo_key = nuevo.strip().lower()
                        if viejo_key in sf:
                            sf[nuevo_key] = sf.pop(viejo_key)
                            snap.stock_final_json = json.dumps(sf)
                    # Renombrar producto
                    prod.nombre = nuevo
                    renombrados += 1

                elif item["accion"] == "eliminar_duplicado":
                    # El nombre nuevo ya existe → eliminar el viejo (seed duplicado)
                    prod_viejo = db.session.get(Producto, item["id"])
                    if prod_viejo is not None:
                        db.session.delete(prod_viejo)
                        eliminados += 1

            except Exception as e:
                errores.append(f"{item['de']}: {e}")

        db.session.commit()
        msg = f"Sincronizado: {renombrados} renombrados, {eliminados} duplicados eliminados."
        if errores:
            msg += f" Errores: {'; '.join(errores)}"
        flash(msg, "success" if not errores else "warning")
        return redirect(url_for("desc.desc_sincronizar"))

    plan = _calcular_plan_renombrado()
    return render_template("admin_sincronizar.html", plan=plan)



