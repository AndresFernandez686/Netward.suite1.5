"""
inventario.py — Importación del inventario de Documentación Oficial por período.

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
  8. Persiste el archivo y sus detalles para que Auditoría los consuma.
  9. Redirige al resumen del período; la importación no descarga otro Excel.
"""
import io
import json
import math
import unicodedata
import zipfile
from datetime import date, datetime
from typing import Optional, Tuple

import openpyxl
from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, session, url_for, jsonify, send_file as send_pdf_response)
from werkzeug.utils import secure_filename

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
            original = {
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
            }
            if all(original[k] is not None for k in (
                "nombre", "si", "compras", "otros_ing", "otras_sal", "sf", "vt", "vr", "dif"
            )):
                return original, header_idx

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

    raise ValueError(
        "No se detectaron todas las columnas obligatorias: producto, stock inicial, "
        "compras, otros ingresos, otras salidas, stock final, venta teórica, "
        "venta real y diferencia."
    )


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
    """Guarda o actualiza el snapshot; el llamador confirma la transacción."""
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
# Rutas
# ---------------------------------------------------------------------------

@desc_bp.route("/admin/desc", methods=["GET", "POST"])
def admin_desc():
    _requiere_admin()
    from core.models import (
        db, Tienda, InventarioDescSnapshot, Producto, InventarioPeriodo,
        ExcelImportado, ExcelDetalle, FacturaCompra, FacturaCompraDetalle,
    )

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
    excel_id_arg = request.args.get("excel_id", type=int)
    snapshot_id_arg = request.args.get("snapshot_id", type=int)
    active_doc_tab = request.args.get("doc_tab", "inventario")
    if active_doc_tab not in {"inventario", "facturas", "datos", "historial"}:
        active_doc_tab = "inventario"
    if request.args.get("ver_datos") == "1":
        active_doc_tab = "datos"
    periodo_seleccionado = next((p for p in periodos_disponibles if p.id == periodo_id_arg), None)
    if periodo_seleccionado is None and periodos_disponibles:
        periodo_seleccionado = periodos_disponibles[0]

    excel_seleccionado = None
    excel_detalles = []
    snapshot_seleccionado = None
    snapshot_detalles = []
    facturas_periodo = []
    factura_detalles = []
    if periodo_seleccionado is not None:
        if excel_id_arg:
            excel_seleccionado = ExcelImportado.query.filter_by(
                id=excel_id_arg,
                periodo_id=periodo_seleccionado.id,
                cliente_id=cliente_id,
            ).first()
        else:
            excel_seleccionado = (
                ExcelImportado.query
                .filter_by(
                    periodo_id=periodo_seleccionado.id,
                    cliente_id=cliente_id,
                )
                .filter(ExcelImportado.estado_validacion.in_(("ok", "pendiente_vinculacion")))
                .order_by(ExcelImportado.id.desc())
                .first()
            )
        if excel_seleccionado is not None:
            from core.excel_importer import corregir_vinculaciones_empaque
            if corregir_vinculaciones_empaque(excel_seleccionado.id):
                db.session.commit()
                flash(
                    "Se desvincularon productos cuya cantidad de empaque no coincide con el Excel; requieren revisión.",
                    "warning",
                )
            excel_detalles = (
                ExcelDetalle.query
                .filter_by(excel_id=excel_seleccionado.id)
                .order_by(ExcelDetalle.grupo, ExcelDetalle.artdescrip, ExcelDetalle.id)
                .all()
            )
        facturas_periodo = (
            FacturaCompra.query
            .filter_by(periodo_id=periodo_seleccionado.id, cliente_id=cliente_id)
            .order_by(FacturaCompra.orden_carga.asc(), FacturaCompra.id.asc())
            .all()
        )
        if facturas_periodo:
            ids_facturas = [factura.id for factura in facturas_periodo]
            factura_detalles = (
                FacturaCompraDetalle.query
                .join(FacturaCompra)
                .filter(FacturaCompraDetalle.factura_id.in_(ids_facturas))
                .order_by(
                    FacturaCompra.orden_carga.asc(), FacturaCompra.id.asc(),
                    FacturaCompraDetalle.id.asc(),
                )
                .all()
            )

    # Historial de snapshots para mostrar en la UI
    snapshots = (InventarioDescSnapshot.query
                 .filter_by(cliente_id=cliente_id)
                 .order_by(InventarioDescSnapshot.creado.desc())
                 .limit(10).all())
    historial_vistas = {}
    for snapshot in snapshots:
        periodo_hist = (
            InventarioPeriodo.query
            .filter_by(
                cliente_id=cliente_id,
                tienda_id=snapshot.tienda_id,
                fecha_hasta=snapshot.fecha_proceso,
            )
            .order_by(InventarioPeriodo.id.desc())
            .first()
        )
        excel_hist = None
        if periodo_hist:
            excel_hist = (
                ExcelImportado.query
                .filter_by(periodo_id=periodo_hist.id, cliente_id=cliente_id)
                .order_by(ExcelImportado.id.desc())
                .first()
            )
        historial_vistas[snapshot.id] = {
            "periodo_id": periodo_hist.id if periodo_hist else None,
            "excel_id": excel_hist.id if excel_hist else None,
        }

    if snapshot_id_arg:
        snapshot_seleccionado = next(
            (snapshot for snapshot in snapshots if snapshot.id == snapshot_id_arg), None
        )
        if snapshot_seleccionado:
            try:
                stock_historico = json.loads(snapshot_seleccionado.stock_final_json or "{}")
            except (TypeError, ValueError):
                stock_historico = {}
            snapshot_detalles = sorted(
                ({"producto": nombre, "stock_final": valor} for nombre, valor in stock_historico.items()),
                key=lambda fila: fila["producto"],
            )
            vista_snapshot = historial_vistas.get(snapshot_seleccionado.id, {})
            if not vista_snapshot.get("excel_id"):
                # No mezclar el snapshot antiguo con el Excel más reciente que
                # se selecciona por defecto para el período actual.
                excel_seleccionado = None
                excel_detalles = []

    if request.method == "POST":
        archivo       = request.files.get("archivo")
        periodo_id    = request.form.get("periodo_id", type=int)

        periodo = (
            InventarioPeriodo.query
            .filter_by(id=periodo_id, cliente_id=cliente_id)
            .first()
        )
        if periodo is None:
            flash("Selecciona un período contable válido para procesar la documentación oficial.", "warning")
            return redirect(url_for("desc.admin_desc"))

        volver_al_periodo = request.form.get("return_to") == "periodo"

        def redirigir_importacion(*, ver_datos=False):
            if volver_al_periodo:
                return redirect(url_for("admin_periodo_detalle", periodo_id=periodo.id))
            destino = url_for(
                "desc.admin_desc",
                periodo_id=periodo.id,
                doc_tab="datos" if ver_datos else "inventario",
                **({"ver_datos": 1} if ver_datos else {}),
            )
            return redirect(destino + ("#datos-extraidos-card" if ver_datos else ""))

        tienda_id = periodo.tienda_id
        fecha_ini = periodo.fecha_desde
        fecha_fin = periodo.fecha_hasta
        if not archivo or not archivo.filename:
            flash("Selecciona un archivo Excel antes de continuar.", "error")
            return redirigir_importacion()

        fname = archivo.filename
        if not (fname.lower().endswith(".xls") or fname.lower().endswith(".xlsx")):
            flash("Solo se permiten archivos .xlsx o .xls", "error")
            return redirigir_importacion()

        try:
            contenido = archivo.read()
            filas_raw = _leer_excel(contenido, fname)

            if len(filas_raw) < 2:
                flash("El archivo no contiene datos.", "error")
                return redirigir_importacion()

            # Documentación Oficial y Auditoría deben usar exactamente el mismo
            # inventario. Antes solo se generaba la descarga/snapshot y la
            # auditoría quedaba sin ExcelDetalle, por lo que Compras aparecía 0.
            from core.excel_importer import importar_excel
            excel_anteriores = (
                ExcelImportado.query
                .filter_by(periodo_id=periodo.id, cliente_id=cliente_id)
                .filter(ExcelImportado.estado_validacion.in_(("ok", "pendiente_vinculacion")))
                .all()
            )
            excel_imp, advertencias_excel = importar_excel(
                periodo_id=periodo.id,
                cliente_id=cliente_id,
                usuario=session.get("usuario", "administrador"),
                filename=fname,
                contenido=contenido,
            )
            for excel_anterior in excel_anteriores:
                excel_anterior.estado_validacion = "reemplazado"

            # Determinar mes para regla de continuidad
            mes = fecha_fin[:7]   # YYYY-MM

            # Datos del período seleccionado (período vs inventario oficial)
            sm   = _stock_map_periodo(periodo.id)
            vm   = _ventas_map(tienda_id, fecha_ini, fecha_fin, periodo.id) if tienda_id else {}
            pm   = _precios_map()
            prev = _snapshot_anterior(tienda_id, mes) if tienda_id else None

            # Procesar
            filas_proc, sf_dict, resumen = _procesar_filas(
                filas_raw, sm, vm, prev, pm)

            if not filas_proc:
                db.session.rollback()
                flash("No se encontraron filas válidas para procesar.", "warning")
                return redirigir_importacion()

            # Guardar snapshot
            if tienda_id and sf_dict:
                _guardar_snapshot(tienda_id, mes, fecha_fin, sf_dict)

            db.session.commit()

            # Resumen flash
            continuidad = "snapshot anterior" if prev else "sistema (InventarioItem)"
            flash(
                f"Procesadas {resumen['total']} filas "
                f"({resumen['excluidos']} excluidas por grupo). "
                f"SI desde período ({periodo.numero}) / {continuidad}: {resumen['si_snap'] + resumen['si_sys']} prods. "
                f"VR desde sistema: {resumen['vr_sys']} prods. "
                f"Inventario oficial #{excel_imp.id} registrado para auditoría.",
                "success",
            )
            for advertencia in advertencias_excel[:5]:
                flash(advertencia, "warning")
            if len(advertencias_excel) > 5:
                flash(
                    f"... y {len(advertencias_excel) - 5} advertencia(s) de vinculación más.",
                    "warning",
                )

            return redirigir_importacion(ver_datos=True)

        except Exception as exc:
            db.session.rollback()
            flash(f"Error al procesar: {exc}", "error")
            return redirigir_importacion()

    from core.azure_document import AzureDocumentConfig

    estado_sync = estado_sincronizacion_catalogo(cliente_id, detallado=True)
    return render_template(
        "admin_desc.html",
        tiendas=tiendas,
        tiendas_map=tiendas_map,
        periodos_disponibles=periodos_disponibles,
        periodo_seleccionado=periodo_seleccionado,
        active_doc_tab=active_doc_tab,
        excel_seleccionado=excel_seleccionado,
        excel_detalles=excel_detalles,
        excel_historico=bool(excel_seleccionado and excel_seleccionado.estado_validacion == "reemplazado"),
        snapshot_seleccionado=snapshot_seleccionado,
        snapshot_detalles=snapshot_detalles,
        facturas_periodo=facturas_periodo,
        azure_document_status=AzureDocumentConfig.from_env().public_status(),
        factura_detalles=factura_detalles,
        productos_factura=Producto.query.order_by(Producto.categoria, Producto.nombre).all(),
        facturas_pendientes=sum(
            1 for detalle in factura_detalles
            if detalle.estado_vinculacion not in ("vinculado", "aplicado", "fuera_rango")
        ),
        estado_sync=estado_sync,
        mostrar_datos=request.args.get("ver_datos") == "1",
        snapshots=snapshots,
        historial_vistas=historial_vistas,
        inventarios_procesados=InventarioDescSnapshot.query.count(),
        ultimo_snapshot=(snapshots[0] if snapshots else None),
        total_productos=Producto.query.count(),
        categorias_registradas=Producto.query.with_entities(Producto.categoria).distinct().count(),
        grupos_excluidos_count=len(GRUPOS_EXCLUIDOS),
        reglas_activas=3,
        hoy=date.today().isoformat(),
        primer_dia=date.today().replace(day=1).isoformat(),
    )


def _guardar_analisis_automatico(factura):
    """Analiza una factura y deja el resultado listo para el commit actual."""
    from core.azure_document import (
        AzureDocumentConfig, AzureDocumentError, analyze_pdf, local_ocr_result,
    )
    from core.models import utc_now

    config = AzureDocumentConfig.from_env()
    if config.configured:
        resultado = analyze_pdf(factura.archivo_pdf, config)
    elif not config.enabled:
        resultado = local_ocr_result(factura)
    else:
        raise AzureDocumentError(
            "Azure AI está activado, pero faltan el endpoint o la clave de Document Intelligence."
        )
    precision = (resultado.get("precision") or {}).get("porcentaje")
    factura.analisis_json = json.dumps(resultado, ensure_ascii=False)
    factura.analisis_motor = str(resultado.get("motor") or "")[:40]
    factura.analisis_precision = float(precision) if precision is not None else None
    factura.analisis_estado = str(resultado.get("estado") or "completado")[:30]
    factura.analisis_fecha = utc_now()
    return resultado, config


@desc_bp.route("/admin/documentacion/facturas/importar", methods=["POST"])
def desc_facturas_importar():
    """Importa hasta 20 facturas PDF en una sola operación."""
    _requiere_admin()
    from core.models import db, FacturaCompra, InventarioPeriodo
    from core.factura_ocr import (
        FacturaError, MAX_FACTURAS_POR_CARGA, MAX_TOTAL_BYTES, importar_factura,
    )

    cliente_id = session.get("cliente_id", "C001")
    periodo_id = request.form.get("periodo_id", type=int)
    periodo = InventarioPeriodo.query.filter_by(
        id=periodo_id, cliente_id=cliente_id,
    ).first()
    if periodo is None:
        flash("Selecciona un período contable válido.", "warning")
        return redirect(url_for("desc.admin_desc"))

    archivos = [archivo for archivo in request.files.getlist("facturas_pdf") if archivo.filename]
    if not archivos:
        flash("Selecciona al menos una factura PDF.", "warning")
        return redirect(url_for("desc.admin_desc", periodo_id=periodo.id, doc_tab="facturas") + "#facturas-card")
    if len(archivos) > MAX_FACTURAS_POR_CARGA:
        flash(f"Puedes cargar hasta {MAX_FACTURAS_POR_CARGA} facturas por operación.", "error")
        return redirect(url_for("desc.admin_desc", periodo_id=periodo.id, doc_tab="facturas") + "#facturas-card")

    contenidos = []
    total_bytes = 0
    for archivo in archivos:
        if not archivo.filename.lower().endswith(".pdf"):
            flash(f"{archivo.filename}: solo se permiten archivos PDF.", "error")
            return redirect(url_for("desc.admin_desc", periodo_id=periodo.id, doc_tab="facturas") + "#facturas-card")
        contenido = archivo.read()
        total_bytes += len(contenido)
        contenidos.append((archivo.filename, contenido))
    if total_bytes > MAX_TOTAL_BYTES:
        flash("El conjunto de facturas supera el límite de 60 MB.", "error")
        return redirect(url_for("desc.admin_desc", periodo_id=periodo.id, doc_tab="facturas") + "#facturas-card")

    importadas = 0
    avisos = []
    ultima_factura = (
        FacturaCompra.query
        .filter_by(periodo_id=periodo.id, cliente_id=cliente_id)
        .order_by(FacturaCompra.orden_carga.desc(), FacturaCompra.id.desc())
        .first()
    )
    siguiente_orden = max(
        int(ultima_factura.orden_carga or 0) if ultima_factura else 0,
        FacturaCompra.query.filter_by(
            periodo_id=periodo.id, cliente_id=cliente_id
        ).count(),
    )
    try:
        for posicion, (nombre, contenido) in enumerate(contenidos, start=1):
            factura, advertencias = importar_factura(
                periodo=periodo, cliente_id=cliente_id,
                usuario=session.get("usuario", "administrador"),
                nombre_archivo=nombre, contenido=contenido,
                orden_carga=siguiente_orden + posicion,
            )
            importadas += int(factura is not None)
            avisos.extend(advertencias)
            if factura is not None:
                db.session.flush()
                try:
                    _guardar_analisis_automatico(factura)
                except Exception as exc:
                    factura.analisis_estado = "error"
                    avisos.append(
                        f"{nombre}: la factura fue cargada, pero el análisis automático no pudo completarse."
                    )
        db.session.commit()
    except FacturaError as exc:
        db.session.rollback()
        flash(f"No se pudieron importar las facturas: {exc}", "error")
        return redirect(url_for("desc.admin_desc", periodo_id=periodo.id, doc_tab="facturas") + "#facturas-card")
    except Exception:
        db.session.rollback()
        flash("Ocurrió un error al guardar las facturas; no se almacenaron datos parciales.", "error")
        return redirect(url_for("desc.admin_desc", periodo_id=periodo.id, doc_tab="facturas") + "#facturas-card")

    flash(f"{importadas} factura(s) procesada(s). Revisa las compras detectadas antes de aplicarlas.", "success")
    for aviso in avisos[:8]:
        flash(aviso, "warning")
    if len(avisos) > 8:
        flash(f"Hay {len(avisos) - 8} advertencia(s) adicionales en la tabla de revisión.", "warning")
    return redirect(url_for("desc.admin_desc", periodo_id=periodo.id, doc_tab="facturas") + "#facturas-card")


@desc_bp.route("/admin/documentacion/facturas/detalle/<int:detalle_id>", methods=["POST"])
def desc_factura_detalle_actualizar(detalle_id):
    """Permite confirmar el producto y la conversión antes de aplicar Compras."""
    _requiere_admin()
    from core.models import db, FacturaCompra, FacturaCompraDetalle, Producto

    cliente_id = session.get("cliente_id", "C001")
    detalle = (
        FacturaCompraDetalle.query.join(FacturaCompra)
        .filter(FacturaCompraDetalle.id == detalle_id, FacturaCompra.cliente_id == cliente_id)
        .first()
    )
    if detalle is None:
        abort(404)
    producto_id = request.form.get("producto_id", type=int)
    producto = db.session.get(Producto, producto_id) if producto_id else None
    try:
        cantidad = float(request.form.get("cantidad_facturada", detalle.cantidad_facturada))
        factor = float(request.form.get("factor_conversion", detalle.factor_conversion))
    except (TypeError, ValueError):
        flash("Cantidad o factor de conversión inválidos.", "error")
        return redirect(url_for("desc.admin_desc", periodo_id=detalle.factura.periodo_id, doc_tab="facturas") + "#facturas-card")
    if (
        producto is None or not math.isfinite(cantidad) or not math.isfinite(factor)
        or cantidad < 0 or factor <= 0
    ):
        flash("Selecciona un producto y utiliza valores de conversión válidos.", "error")
        return redirect(url_for("desc.admin_desc", periodo_id=detalle.factura.periodo_id, doc_tab="facturas") + "#facturas-card")
    permitidas = {"Impulsivo", "Por Kilos"} if detalle.factura.proveedor == "Helacor" else {"Extras"}
    if producto.categoria not in permitidas:
        flash(f"{detalle.factura.proveedor} solo puede vincular productos de {', '.join(sorted(permitidas))}.", "error")
        return redirect(url_for("desc.admin_desc", periodo_id=detalle.factura.periodo_id, doc_tab="facturas") + "#facturas-card")
    detalle.producto_id = producto.id
    detalle.producto_nombre = producto.nombre
    detalle.cantidad_facturada = cantidad
    from core.factura_ocr import calcular_compras_unidades, factor_conversion_catalogo
    factor_catalogo = (
        factor_conversion_catalogo(producto, cliente_id)
        if detalle.factura.proveedor == "Helacor" and detalle.confianza != "Confirmada"
        else None
    )
    fuente_factor = "Vinculación y conversión confirmadas por administrador"
    if factor_catalogo is not None:
        factor, fuente_catalogo = factor_catalogo
        fuente_factor = f"Conversión automática desde {fuente_catalogo}"
    detalle.factor_conversion = factor
    detalle.compras_calculadas = calcular_compras_unidades(cantidad, factor)
    detalle.estado_vinculacion = "fuera_rango" if detalle.factura.estado == "fuera_rango" else "vinculado"
    detalle.confianza = "Confirmada"
    detalle.observacion = fuente_factor
    db.session.commit()
    flash(f"Compra de {producto.nombre} actualizada.", "success")
    return redirect(url_for("desc.admin_desc", periodo_id=detalle.factura.periodo_id, doc_tab="facturas") + "#facturas-card")


@desc_bp.route("/admin/documentacion/facturas/aplicar", methods=["POST"])
def desc_facturas_aplicar():
    """Reemplaza Compras del Excel por las unidades confirmadas de las facturas."""
    _requiere_admin()
    from core.models import db, InventarioPeriodo
    from core.factura_ocr import FacturaError, aplicar_compras_facturas

    cliente_id = session.get("cliente_id", "C001")
    periodo = InventarioPeriodo.query.filter_by(
        id=request.form.get("periodo_id", type=int), cliente_id=cliente_id,
    ).first()
    if periodo is None:
        abort(404)
    try:
        resumen = aplicar_compras_facturas(
            periodo, cliente_id, session.get("usuario", "administrador")
        )
        db.session.commit()
    except FacturaError as exc:
        db.session.rollback()
        flash(str(exc), "warning")
        return redirect(url_for("desc.admin_desc", periodo_id=periodo.id, doc_tab="facturas") + "#facturas-card")
    except Exception:
        db.session.rollback()
        flash("No se aplicaron las compras; la operación fue revertida completamente.", "error")
        return redirect(url_for("desc.admin_desc", periodo_id=periodo.id, doc_tab="facturas") + "#facturas-card")
    mensaje = f"Compras actualizadas desde facturas: {resumen['cambios']} producto(s)."
    if resumen["no_encontrados"]:
        mensaje += f" {len(resumen['no_encontrados'])} producto(s) no existen en el inventario XLS/XLSX."
    flash(mensaje, "success")
    return redirect(url_for("desc.admin_desc", periodo_id=periodo.id, doc_tab="datos", ver_datos=1) + "#datos-extraidos-card")


@desc_bp.route("/admin/documentacion/facturas/<int:factura_id>/pdf")
def desc_factura_pdf(factura_id):
    _requiere_admin()
    from core.models import FacturaCompra
    factura = FacturaCompra.query.filter_by(
        id=factura_id, cliente_id=session.get("cliente_id", "C001")
    ).first()
    if factura is None:
        abort(404)
    response = send_pdf_response(
        io.BytesIO(factura.archivo_pdf), mimetype="application/pdf",
        download_name=factura.nombre_archivo, as_attachment=False,
    )
    response.headers["Content-Security-Policy"] = "sandbox"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@desc_bp.route("/admin/documentacion/facturas/<int:factura_id>/descargar")
def desc_factura_descargar(factura_id):
    _requiere_admin()
    from core.models import FacturaCompra

    factura = FacturaCompra.query.filter_by(
        id=factura_id, cliente_id=session.get("cliente_id", "C001")
    ).first()
    if factura is None:
        abort(404)
    response = send_pdf_response(
        io.BytesIO(factura.archivo_pdf),
        mimetype="application/pdf",
        download_name=factura.nombre_archivo,
        as_attachment=True,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@desc_bp.route("/admin/documentacion/periodos/<int:periodo_id>/facturas/descargar")
def desc_facturas_periodo_descargar(periodo_id):
    """Descarga la factura del período o un ZIP cuando contiene varias."""
    _requiere_admin()
    from core.models import FacturaCompra, InventarioPeriodo

    cliente_id = session.get("cliente_id", "C001")
    periodo = InventarioPeriodo.query.filter_by(
        id=periodo_id, cliente_id=cliente_id,
    ).first()
    if periodo is None:
        abort(404)
    facturas = (
        FacturaCompra.query
        .filter_by(periodo_id=periodo.id, cliente_id=cliente_id)
        .order_by(FacturaCompra.orden_carga.asc(), FacturaCompra.id.asc())
        .all()
    )
    if not facturas:
        abort(404)
    if len(facturas) == 1:
        factura = facturas[0]
        response = send_pdf_response(
            io.BytesIO(factura.archivo_pdf),
            mimetype="application/pdf",
            download_name=factura.nombre_archivo,
            as_attachment=True,
        )
    else:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archivo_zip:
            for posicion, factura in enumerate(facturas, start=1):
                nombre = secure_filename(factura.nombre_archivo) or f"factura-{factura.id}.pdf"
                archivo_zip.writestr(f"{posicion:02d}-{nombre}", factura.archivo_pdf)
        stream.seek(0)
        response = send_pdf_response(
            stream,
            mimetype="application/zip",
            download_name=f"facturas-periodo-{periodo.numero}.zip",
            as_attachment=True,
        )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@desc_bp.route(
    "/admin/documentacion/facturas/<int:factura_id>/analisis",
    methods=["GET", "POST"],
)
def desc_factura_analisis(factura_id):
    _requiere_admin()
    from core.azure_document import AzureDocumentConfig, AzureDocumentError
    from core.models import FacturaCompra, db

    factura = FacturaCompra.query.filter_by(
        id=factura_id, cliente_id=session.get("cliente_id", "C001")
    ).first()
    if factura is None:
        abort(404)

    config = AzureDocumentConfig.from_env()
    public_status = config.public_status()
    if request.method == "GET":
        if not factura.analisis_json:
            return jsonify(
                ok=True,
                estado="sin_analisis",
                configuracion=public_status,
            )
        try:
            resultado = json.loads(factura.analisis_json)
        except (TypeError, ValueError):
            resultado = None
        if not isinstance(resultado, dict):
            return jsonify(
                ok=False,
                estado="resultado_invalido",
                error="El análisis guardado no tiene un formato válido.",
                configuracion=public_status,
            ), 500
        return jsonify(
            ok=True,
            estado=factura.analisis_estado or "completado",
            resultado=resultado,
            configuracion=public_status,
        )

    try:
        resultado, config = _guardar_analisis_automatico(factura)
        public_status = config.public_status()
        db.session.commit()
        return jsonify(
            ok=True,
            estado=factura.analisis_estado,
            resultado=resultado,
            configuracion=public_status,
        )
    except AzureDocumentError as exc:
        db.session.rollback()
        return jsonify(
            ok=False,
            estado="error",
            error=str(exc),
            configuracion=public_status,
        ), 503 if config.enabled and not config.configured else 502
    except Exception:
        db.session.rollback()
        return jsonify(
            ok=False,
            estado="error",
            error="No se pudo completar el análisis del documento.",
            configuracion=public_status,
        ), 500


_CAMPOS_EXCEL_TEXTO = {
    "articulo": 40,
    "artdescrip": 255,
    "grupo": 120,
    "grudescrip": 120,
    "motivo_exclusion": 120,
}
_CAMPOS_EXCEL_NUMERO = {
    "stockinicial", "compras", "otrosingresos",
    "otrassalidas", "stockfinal", "ventateorica", "ventareal",
    "diferencia", "importedesvio", "kilos", "unidades",
}


class ConflictoEdicionExcel(RuntimeError):
    pass


def _normalizar_celda_excel(campo, valor_raw):
    if campo in _CAMPOS_EXCEL_TEXTO:
        valor = str(valor_raw or "").strip()[:_CAMPOS_EXCEL_TEXTO[campo]]
        if campo == "articulo" and not valor:
            raise ValueError("El código del artículo no puede quedar vacío.")
        return None if campo == "motivo_exclusion" and not valor else valor
    if campo in _CAMPOS_EXCEL_NUMERO:
        try:
            valor = float(valor_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"El campo {campo} debe ser numérico.") from exc
        if not math.isfinite(valor):
            raise ValueError(f"El campo {campo} debe contener un número finito.")
        return valor
    if campo == "excluido_auditoria":
        if isinstance(valor_raw, bool):
            return valor_raw
        if str(valor_raw).strip().lower() in {"true", "1", "sí", "si"}:
            return True
        if str(valor_raw).strip().lower() in {"false", "0", "no", ""}:
            return False
        raise ValueError("El campo excluido_auditoria debe ser booleano.")
    raise ValueError(f"El campo {campo} no puede editarse.")


@desc_bp.route("/admin/desc/excel/<int:excel_id>/datos", methods=["POST"])
def desc_excel_datos_guardar(excel_id):
    """Actualiza solo celdas modificadas y registra el antes/después de cada fila."""
    _requiere_admin()
    from core.models import (
        db, ExcelImportado, ExcelDetalle, ExcelDetalleEdicion, InventarioPeriodo,
        Producto,
    )

    cliente_id = session.get("cliente_id", "C001")
    excel = ExcelImportado.query.filter_by(id=excel_id, cliente_id=cliente_id).first()
    if excel is None:
        abort(404)
    periodo = db.session.get(InventarioPeriodo, excel.periodo_id)
    if periodo is None or periodo.cliente_id != cliente_id:
        abort(404)

    payload = request.get_json(silent=True) or {}
    filas = payload.get("filas")
    if not isinstance(filas, list) or not filas:
        return jsonify(ok=False, error="No hay celdas modificadas para guardar."), 400
    if len(filas) > 5000:
        return jsonify(ok=False, error="La edición supera el límite de 5.000 filas."), 400

    ids = []
    for item in filas:
        try:
            ids.append(int(item.get("id")))
        except (AttributeError, TypeError, ValueError):
            return jsonify(ok=False, error="Se recibió una fila inválida."), 400
    detalles = {
        fila.id: fila for fila in ExcelDetalle.query.filter(
            ExcelDetalle.excel_id == excel.id,
            ExcelDetalle.id.in_(ids),
        ).all()
    }
    if len(detalles) != len(set(ids)):
        abort(404)

    total_celdas = 0
    identidad_modificada = False
    try:
        for item in filas:
            detalle = detalles[int(item["id"])]
            valores = item.get("valores")
            originales = item.get("originales") or {}
            if not isinstance(valores, dict):
                raise ValueError("Formato de edición inválido.")
            cambios = {}
            for campo, valor_raw in valores.items():
                valor = _normalizar_celda_excel(campo, valor_raw)
                anterior = getattr(detalle, campo)
                if campo in originales:
                    original = _normalizar_celda_excel(campo, originales[campo])
                    actual_normalizado = _normalizar_celda_excel(campo, anterior)
                    if actual_normalizado != original:
                        raise ConflictoEdicionExcel(
                            f"La fila «{detalle.artdescrip or detalle.articulo}» cambió en otra sesión. Recarga los datos antes de guardar."
                        )
                if anterior != valor:
                    cambios[campo] = {"anterior": anterior, "nuevo": valor}
                    setattr(detalle, campo, valor)

            if cambios:
                if {"articulo", "artdescrip"} & cambios.keys():
                    identidad_modificada = True
                    producto_anterior = (
                        db.session.get(Producto, detalle.producto_id)
                        if detalle.producto_id else None
                    )
                    if producto_anterior is not None and "articulo" in cambios:
                        codigo_anterior = str(
                            cambios["articulo"]["anterior"] or ""
                        ).strip()
                        if str(producto_anterior.codigo_articulo or "").strip() == codigo_anterior:
                            producto_anterior.codigo_articulo = None
                    detalle.producto_id = None
                    detalle.producto_nombre_interno = None
                    detalle.estado_vinculacion = "pendiente"
                total_celdas += len(cambios)
                db.session.add(ExcelDetalleEdicion(
                    cliente_id=cliente_id,
                    periodo_id=periodo.id,
                    excel_id=excel.id,
                    detalle_id=detalle.id,
                    usuario=session.get("usuario", "administrador"),
                    cambios_json=json.dumps(cambios, ensure_ascii=False),
                ))

        if total_celdas == 0:
            return jsonify(ok=True, filas=0, celdas=0, message="No había cambios nuevos.")
        pendientes = ExcelDetalle.query.filter(
            ExcelDetalle.excel_id == excel.id,
            ExcelDetalle.excluido_auditoria.is_(False),
            ExcelDetalle.estado_vinculacion != "vinculado",
        ).count()
        excel.productos_nuevos = pendientes
        excel.estado_validacion = "pendiente_vinculacion" if pendientes else "ok"
        db.session.commit()
        estado_sync = estado_sincronizacion_catalogo(cliente_id, detallado=True)
        requiere_sync = estado_sync["total"] > 0
        return jsonify(
            ok=True,
            filas=len(filas),
            celdas=total_celdas,
            requiere_sincronizacion=requiere_sync,
            sincronizacion=estado_sync,
            message=(
                f"Se guardaron {total_celdas} celda(s). "
                + (
                    "Revisa la sincronización del catálogo antes de ejecutar Auditoría."
                    if requiere_sync else
                    (
                        "La fila sin producto coincidente se descartará automáticamente."
                        if identidad_modificada else
                        "Auditoría usará estos valores en su próxima ejecución."
                    )
                )
            ),
        )
    except ConflictoEdicionExcel as exc:
        db.session.rollback()
        return jsonify(ok=False, error=str(exc)), 409
    except ValueError as exc:
        db.session.rollback()
        return jsonify(ok=False, error=str(exc)), 400
    except Exception:
        db.session.rollback()
        return jsonify(ok=False, error="No se pudieron guardar las modificaciones."), 500



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
    "Familiar 1":                      "Familiar nº 1 (chocolate/d.leche/americana)",
    "Familiar 2":                      "Familiar nº 2 (chocolate/frutilla/dulce de leche)",
    "Familiar 3":                      "Familiar nº 3 (vainilla/frutilla/granizado)",
    "Familiar 4":                      "Familiar nº 4 (d.leche/frutilla/vainilla)",
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
    "Cucurucho Nacional x54":          "Cucuruchón nacional x 78 u",
    "Cucharita Grido":                 "Cucharita coloridax 1000 grs.",
    "Delicia":                         "Barra delicia chocolate y mani",
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
    Devuelve el plan de cambios del catálogo.
    Incluye renombres y productos nuevos todavía no publicados al empleado.
    """
    from core.models import Producto
    existentes = {_norm(p.nombre): p for p in Producto.query.all()}
    plan = []
    for nombre_sys, nombre_excel in RENOMBRAR_CATALOGO.items():
        prod = existentes.get(_norm(nombre_sys))
        destino_existe = existentes.get(_norm(nombre_excel))
        if prod is None:
            plan.append({
                "de": nombre_sys,
                "a": nombre_excel,
                "accion": "sin_cambios" if destino_existe else "no_existe",
                "id": destino_existe.id if destino_existe else None,
            })
            continue
        # ¿El nombre destino ya existe?
        if destino_existe and destino_existe.id == prod.id and prod.nombre == nombre_excel:
            plan.append({"de": nombre_sys, "a": nombre_excel,
                         "accion": "sin_cambios", "id": prod.id})
            continue
        if destino_existe and destino_existe.id != prod.id:
            plan.append({"de": nombre_sys, "a": nombre_excel,
                         "accion": "eliminar_duplicado", "id": prod.id,
                         "id_destino": destino_existe.id})
        else:
            plan.append({"de": nombre_sys, "a": nombre_excel,
                         "accion": "renombrar", "id": prod.id})
    ids_a_eliminar = {
        item["id"] for item in plan if item["accion"] == "eliminar_duplicado"
    }
    nuevos = []
    for producto in Producto.query.filter_by(visible_empleado=False).order_by(
        Producto.nombre
    ).all():
        if producto.id in ids_a_eliminar:
            continue
        nuevos.append({
            "de": producto.nombre,
            "a": "Publicar en el catálogo de empleados",
            "accion": "nuevo_producto",
            "id": producto.id,
        })
    return nuevos + plan


def estado_sincronizacion_catalogo(cliente_id, *, detallado=True):
    """Resume cambios del catálogo y filas vigentes del Excel pendientes de vincular."""
    from core.excel_importer import (
        contar_detalles_pendientes,
        contar_detalles_revinculables,
    )

    plan = _calcular_plan_renombrado()
    renombres = sum(
        item["accion"] in {"renombrar", "eliminar_duplicado"}
        for item in plan
    )
    nuevos_productos = sum(
        item["accion"] == "nuevo_producto"
        for item in plan
    )
    pendientes = contar_detalles_pendientes(cliente_id)
    revinculables = contar_detalles_revinculables(cliente_id) if detallado else 0
    return {
        "renombres": renombres,
        "nuevos_productos": nuevos_productos,
        "pendientes": pendientes,
        "revinculables": revinculables,
        "sin_producto": max(0, pendientes - revinculables),
        # Las filas sin producto coincidente se descartan. Solo un cambio que
        # realmente puede aplicarse debe encender la notificación y el botón.
        "total": renombres + nuevos_productos + revinculables,
        "aplicables": renombres + nuevos_productos + revinculables,
    }


@desc_bp.route("/admin/desc/sincronizar", methods=["GET", "POST"])
def desc_sincronizar():
    _requiere_admin()
    from core.models import db, Producto, InventarioItem, ProductoPrecio, InventarioDescSnapshot

    if request.method == "POST":
        plan = _calcular_plan_renombrado()
        requiere_version_nueva = any(
            item["accion"] in {"renombrar", "nuevo_producto"}
            for item in plan
        )
        version_nueva = int(
            db.session.query(db.func.max(Producto.catalogo_version)).scalar() or 0
        ) + (1 if requiere_version_nueva else 0)
        renombrados = 0
        eliminados  = 0
        publicados  = 0
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
                    prod.catalogo_version = version_nueva
                    renombrados += 1

                elif item["accion"] == "eliminar_duplicado":
                    # El nombre nuevo ya existe → eliminar el viejo (seed duplicado)
                    prod_viejo = db.session.get(Producto, item["id"])
                    if prod_viejo is not None:
                        db.session.delete(prod_viejo)
                        eliminados += 1

                elif item["accion"] == "nuevo_producto":
                    producto_nuevo = db.session.get(Producto, item["id"])
                    if producto_nuevo is not None and not producto_nuevo.visible_empleado:
                        producto_nuevo.visible_empleado = True
                        producto_nuevo.catalogo_version = version_nueva
                        publicados += 1

            except Exception as e:
                errores.append(f"{item['de']}: {e}")

        from core.excel_importer import (
            _ultimos_excel_validos,
            descartar_detalles_sin_producto,
            revincular_detalles_pendientes,
        )
        revinculados = revincular_detalles_pendientes(
            session.get("cliente_id", "C001")
        )
        descartados = 0
        for excel_vigente in _ultimos_excel_validos(session.get("cliente_id", "C001")):
            descartados += descartar_detalles_sin_producto(excel_vigente.id)
        db.session.commit()
        msg = (
            f"Sincronizado: {renombrados} renombrados, "
            f"{eliminados} duplicados eliminados, {publicados} producto(s) nuevo(s) "
            f"publicado(s), {revinculados} fila(s) del Excel vinculada(s) y "
            f"{descartados} fila(s) sin producto descartada(s)."
        )
        if errores:
            msg += f" Errores: {'; '.join(errores)}"
        flash(msg, "success" if not errores else "warning")
        return redirect(url_for("desc.desc_sincronizar", completado=1))

    plan = _calcular_plan_renombrado()
    estado_sync = estado_sincronizacion_catalogo(
        session.get("cliente_id", "C001"),
        detallado=True,
    )
    return render_template(
        "admin_sincronizar.html",
        plan=plan,
        pendientes_revinculables=estado_sync["revinculables"],
        pendientes_sin_producto=estado_sync["sin_producto"],
        completado=request.args.get("completado") == "1",
    )



