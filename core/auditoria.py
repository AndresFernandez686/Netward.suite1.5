"""
Motor de auditoría automática de inventario.
Ejecuta las 17 validaciones del prompt en orden de prioridad y genera
AuditoriaResultado con causa sugerida, evidencia y nivel de confianza.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Optional
from sqlalchemy import and_, or_

from .models import (
    db, InventarioPeriodo, ConteoDetalle, AjusteInventario, InventarioItem,
    ExcelDetalle, AuditoriaResultado, Justificacion,
    RegistroAveriado, RegistroVencimiento, ProductoPrecio,
    ProductoRelacionado,
)

# ─── Constantes ──────────────────────────────────────────────────────────────
CAUSAS = [
    "Compensación entre períodos",
    "Inconsistencia de continuidad",
    "Compra mal cargada",
    "Error de conteo",
    "Producto vencido",
    "Merma o averiado",
    "Producto relacionado incoherente",
    "Canje no registrado",
    "Pendiente de revisión",
]

SEVERIDAD_UMBRAL_MEDIO = 5        # diferencia > 5 unidades → Revisar
SEVERIDAD_UMBRAL_CRITICO = 20     # diferencia > 20 unidades → Crítico
COMPRA_RATIO_ALTO = 3.0           # compra > 3× promedio = sospechosa
COMPRA_RATIO_BAJO = 0.3           # compra < 30 % promedio = sospechosa
STOCK_ABSURDO = 1_000_000_000      # valor fuera de rango razonable; probable Excel corrupto


# ─── Helpers internos ────────────────────────────────────────────────────────

def _norm(nombre: str) -> str:
    return nombre.strip().lower()


def _periodos_anteriores(periodo: InventarioPeriodo, n: int = 4) -> list[InventarioPeriodo]:
    """Últimos n períodos cerrados/conciliados/auditados de la misma tienda, más recientes primero."""
    return (
        InventarioPeriodo.query
        .filter_by(cliente_id=periodo.cliente_id, tienda_id=periodo.tienda_id)
        .filter(InventarioPeriodo.estado.in_(["Cerrado", "Excel Importado", "Conciliado", "Auditado"]))
        .filter(InventarioPeriodo.id < periodo.id)
        .order_by(InventarioPeriodo.id.desc())
        .limit(n)
        .all()
    )


def _stock_final_anterior(periodo: InventarioPeriodo, producto_nombre: str) -> Optional[float]:
    """
    Stock final del producto en el último período cerrado anterior.
    Se calcula como conteo_final del AuditoriaResultado si existe,
    o como conteo_final del ConteoDetalle + ajustes si no.
    """
    pnorm = _norm(producto_nombre)
    anteriores = _periodos_anteriores(periodo, 1)
    if not anteriores:
        return None
    prev = anteriores[0]
    ar = AuditoriaResultado.query.filter_by(
        periodo_id=prev.id, producto_nombre=producto_nombre
    ).first()
    if ar:
        return ar.conteo_final

    # Fallback: conteo_detalle + ajustes
    cd = ConteoDetalle.query.filter_by(
        periodo_id=prev.id, producto_nombre=producto_nombre
    ).first()
    if not cd:
        # Buscar sin sensibilidad a mayúsculas
        cd = (ConteoDetalle.query
              .filter_by(periodo_id=prev.id)
              .filter(db.func.lower(ConteoDetalle.producto_nombre) == pnorm)
              .first())
    if not cd:
        return None
    total_ajuste = db.session.query(
        db.func.coalesce(db.func.sum(AjusteInventario.cantidad_ajustada), 0)
    ).filter_by(periodo_id=prev.id, producto_nombre=producto_nombre).scalar()
    return (cd.total_unidad_base or 0) + float(total_ajuste)


def _promedio_compras(periodo: InventarioPeriodo, producto_nombre: str, n: int = 4) -> float:
    """Promedio de compras del producto en los últimos n períodos conciliados."""
    anteriores = _periodos_anteriores(periodo, n)
    compras = []
    for prev in anteriores:
        # Buscar en AuditoriaResultado
        ar = AuditoriaResultado.query.filter_by(
            periodo_id=prev.id, producto_nombre=producto_nombre
        ).first()
        if ar:
            compras.append(ar.compras)
            continue
        # Buscar en ExcelDetalle (del Excel del período anterior)
        from .models import ExcelImportado
        ei = ExcelImportado.query.filter_by(periodo_id=prev.id).order_by(ExcelImportado.id.desc()).first()
        if ei:
            ed = (ExcelDetalle.query
                  .filter_by(excel_id=ei.id)
                  .filter(
                      db.func.lower(ExcelDetalle.producto_nombre_interno) == _norm(producto_nombre)
                  ).first())
            if ed:
                compras.append(ed.compras or 0)
    return sum(compras) / len(compras) if compras else 0.0


def _ventas_delivery_periodo(periodo: InventarioPeriodo, producto_nombre: str) -> float:
    """Ventas del módulo delivery para el producto en el rango del período (solo informativo)."""
    from .models import DeliveryVenta
    rows = (
        DeliveryVenta.query
        .filter_by(cliente_id=periodo.cliente_id, tienda_id=periodo.tienda_id)
        .filter(or_(
            DeliveryVenta.periodo_id == periodo.id,
            and_(
                DeliveryVenta.periodo_id.is_(None),
                DeliveryVenta.estado_periodo != "fuera_rango",
                DeliveryVenta.fecha >= periodo.fecha_desde,
                DeliveryVenta.fecha <= periodo.fecha_hasta,
            ),
        ))
        .filter(db.func.lower(DeliveryVenta.producto) == _norm(producto_nombre))
        .all()
    )
    return sum(float(r.cantidad or 0) for r in rows)


def _mermas_vencidos(periodo: InventarioPeriodo, producto_nombre: str,
                     tienda_id: str) -> tuple[float, float]:
    """Suma de mermas y vencidos registrados para el producto en el período."""
    pnorm = _norm(producto_nombre)
    averiados = (
        RegistroAveriado.query
        .filter_by(cliente_id=periodo.cliente_id, tienda_id=tienda_id, sinc_estado="sincronizado")
        .filter(RegistroAveriado.fecha >= periodo.fecha_desde)
        .filter(RegistroAveriado.fecha <= periodo.fecha_hasta)
        .filter(db.func.lower(RegistroAveriado.producto) == pnorm)
        .all()
    )
    vencidos = (
        RegistroVencimiento.query
        .filter_by(cliente_id=periodo.cliente_id, tienda_id=tienda_id, sinc_estado="sincronizado")
        .filter(RegistroVencimiento.fecha >= periodo.fecha_desde)
        .filter(RegistroVencimiento.fecha <= periodo.fecha_hasta)
        .filter(db.func.lower(RegistroVencimiento.producto) == pnorm)
        .all()
    )
    total_merma = sum(r.cantidad_unidades or r.cantidad for r in averiados)
    total_venc = sum(r.cantidad_unidades or r.cantidad for r in vencidos)
    return total_merma, total_venc


def _compensacion_conteo(periodo: InventarioPeriodo, producto_nombre: str,
                         diferencia_actual: float) -> tuple[bool, str, float]:
    """
    Detecta compensación de error de conteo dentro del mismo mes.
    Devuelve (detectado, texto_evidencia, diferencia_anterior_compensada).
    """
    if abs(diferencia_actual) < 1:
        return False, "", 0.0
    mes_actual = periodo.fecha_desde[:7]  # YYYY-MM
    anteriores = (
        InventarioPeriodo.query
        .filter_by(cliente_id=periodo.cliente_id, tienda_id=periodo.tienda_id)
        .filter(InventarioPeriodo.fecha_desde.like(f"{mes_actual}%"))
        .filter(InventarioPeriodo.id < periodo.id)
        .all()
    )
    for prev in anteriores:
        ar = AuditoriaResultado.query.filter_by(
            periodo_id=prev.id, producto_nombre=producto_nombre
        ).first()
        if ar and ar.diferencia:
            ratio = abs(diferencia_actual + ar.diferencia) / (abs(ar.diferencia) + 1e-9)
            if ratio < 0.15:
                return True, (
                    f"La diferencia actual ({diferencia_actual:+.1f}) compensa casi exactamente "
                    f"la diferencia del inventario {prev.numero} ({ar.diferencia:+.1f}) "
                    f"dentro del mismo mes."
                ), float(ar.diferencia)
            if ratio < 0.5:
                return True, (
                    f"La diferencia actual ({diferencia_actual:+.1f}) compensa parcialmente "
                    f"la diferencia del inventario {prev.numero} ({ar.diferencia:+.1f})."
                ), float(ar.diferencia)
    return False, "", 0.0


def _precio_unitario(producto_nombre: str, excel_row: Optional[ExcelDetalle]) -> tuple[Optional[float], str]:
    """Devuelve (costo_unitario, fuente_costo). Fuente: 'Excel oficial' | 'Precio interno' | 'Sin costo'."""
    if excel_row and excel_row.artcosto:
        return float(excel_row.artcosto), "Excel oficial"
    # Buscar por producto_id primero (estable), luego por nombre como fallback
    from .models import Producto
    p = (Producto.query
         .filter(db.func.lower(Producto.nombre) == _norm(producto_nombre))
         .first())
    if p:
        pp = ProductoPrecio.query.filter_by(producto_id=p.id).first()
    else:
        pp = None
    if pp is None:
        pp = (ProductoPrecio.query
              .filter(db.func.lower(ProductoPrecio.producto_nombre) == _norm(producto_nombre))
              .first())
    if pp and pp.precio:
        return float(pp.precio), "Precio interno"
    return None, "Sin costo"


# ─── Motor principal ──────────────────────────────────────────────────────────

def ejecutar_auditoria(periodo: InventarioPeriodo) -> list[AuditoriaResultado]:
    """
    Ejecuta el motor de auditoría completo para un período.
    Borra resultados anteriores del período y regenera todos.
    Retorna la lista de AuditoriaResultado creados.
    """
    # Borrar resultados anteriores
    AuditoriaResultado.query.filter_by(periodo_id=periodo.id).delete()
    db.session.flush()

    # Obtener Excel del período (el más reciente)
    from .models import ExcelImportado
    excel_imp = (ExcelImportado.query
                 .filter_by(periodo_id=periodo.id)
                 .order_by(ExcelImportado.id.desc())
                 .first())

    # Mapa producto → fila Excel (producto_id como clave primaria; nombre como fallback)
    excel_map: dict[str, ExcelDetalle] = {}
    excel_raw_map: dict[str, ExcelDetalle] = {}
    if excel_imp:
        for row in ExcelDetalle.query.filter_by(
            excel_id=excel_imp.id, excluido_auditoria=False
        ).all():
            nombre_fila = row.producto_nombre_interno or row.artdescrip
            if nombre_fila:
                excel_raw_map[_norm(nombre_fila)] = row
            if row.estado_vinculacion != "vinculado":
                continue
            if row.producto_id:
                # Resolver nombre del producto por ID (clave estable)
                from .models import Producto
                p = db.session.get(Producto, row.producto_id)
                if p:
                    excel_map[_norm(p.nombre)] = row
            elif row.producto_nombre_interno:
                excel_map[_norm(row.producto_nombre_interno)] = row

    # Conteos del período
    conteos = ConteoDetalle.query.filter_by(periodo_id=periodo.id).all()
    # Ajustes del período
    ajustes_raw = AjusteInventario.query.filter_by(periodo_id=periodo.id).all()
    ajustes_map: dict[str, float] = {}
    ajuste_usuario_map: dict[str, str] = {}
    ajuste_fecha_map: dict[str, str] = {}
    for aj in ajustes_raw:
        k = _norm(aj.producto_nombre)
        # Solo los ajustes con impacta_stock=True modifican el conteo_final
        if getattr(aj, "impacta_stock", True):
            ajustes_map[k] = ajustes_map.get(k, 0) + (aj.cantidad_ajustada or 0)
        ajuste_usuario_map[k] = aj.usuario_admin
        ajuste_fecha_map[k] = aj.fecha_ajuste.strftime("%Y-%m-%d") if aj.fecha_ajuste else ""

    # Todos los productos a auditar = unión de conteos + filas Excel
    nombres: set[str] = {c.producto_nombre for c in conteos}
    if excel_imp:
        for row in ExcelDetalle.query.filter_by(excel_id=excel_imp.id).all():
            n = row.producto_nombre_interno or row.artdescrip
            if n:
                nombres.add(n)
    # Delivery también debe dejar evidencia aunque falten Excel e inventario.
    from .models import DeliveryVenta
    ventas_delivery_periodo = (
        DeliveryVenta.query
        .filter_by(cliente_id=periodo.cliente_id, tienda_id=periodo.tienda_id)
        .filter(or_(
            DeliveryVenta.periodo_id == periodo.id,
            and_(
                DeliveryVenta.periodo_id.is_(None),
                DeliveryVenta.estado_periodo != "fuera_rango",
                DeliveryVenta.fecha >= periodo.fecha_desde,
                DeliveryVenta.fecha <= periodo.fecha_hasta,
            ),
        ))
        .all()
    )
    nombres.update(v.producto for v in ventas_delivery_periodo if v.producto)

    resultados: list[AuditoriaResultado] = []

    for nombre in sorted(nombres):
        pnorm = _norm(nombre)
        conteo = next((c for c in conteos if _norm(c.producto_nombre) == pnorm), None)
        conteo_valido = conteo is not None and bool(conteo.fue_cargado)
        excel_row = excel_map.get(pnorm)
        excel_raw = excel_raw_map.get(pnorm)
        sin_vinculacion = (
            excel_raw is not None
            and excel_raw.estado_vinculacion != "vinculado"
        )
        ajuste = ajustes_map.get(pnorm, 0.0)

        conteo_empleado = float(conteo.total_unidad_base) if conteo else 0.0
        conteo_final = conteo_empleado + ajuste

        # 1. Continuidad
        stock_anterior = _stock_final_anterior(periodo, nombre)
        stock_inicial_excel = float(excel_row.stockinicial) if excel_row else 0.0
        stock_excel_invalido = bool(
            excel_row
            and (
                not math.isfinite(stock_inicial_excel)
                or stock_inicial_excel < 0
                or abs(stock_inicial_excel) > STOCK_ABSURDO
            )
        )
        alerta_continuidad = False
        if stock_anterior is not None and excel_row:
            if abs(stock_anterior - stock_inicial_excel) > 0.5:
                alerta_continuidad = True

        # Stock inicial actual
        stock_inicial = stock_anterior if stock_anterior is not None else stock_inicial_excel

        # 2. Datos del Excel
        compras = float(excel_row.compras) if excel_row else 0.0
        otros_ingresos = float(excel_row.otrosingresos) if excel_row else 0.0
        otras_salidas = float(excel_row.otrassalidas) if excel_row else 0.0
        ventas_excel = float(excel_row.ventareal) if excel_row else 0.0
        stock_final_excel = float(excel_row.stockfinal) if excel_row else 0.0

        # Delivery reemplaza la Venta Real del Excel cuando tiene movimientos.
        ventas_delivery = _ventas_delivery_periodo(periodo, nombre)
        ventas = ventas_delivery if ventas_delivery > 0 else ventas_excel

        # 3. Mermas y vencidos registrados
        total_merma, total_venc = _mermas_vencidos(periodo, nombre, periodo.tienda_id)

        # 4. Stock esperado
        stock_esperado = (
            stock_inicial + compras + otros_ingresos
            - ventas - otras_salidas
            - total_merma - total_venc
        )

        # 5. Diferencia: conteo_final vs stock_esperado
        diferencia = conteo_final - stock_esperado
        if abs(diferencia) < 0.01:
            tipo_diferencia = "correcto"
        elif diferencia < 0:
            tipo_diferencia = "faltante"
        else:
            tipo_diferencia = "sobrante"

        # 6. Costo y fuente
        costo_unit, fuente_costo = _precio_unitario(nombre, excel_row)
        impacto = abs(diferencia) * costo_unit if costo_unit and diferencia != 0 else 0.0

        # 7. Promedio compras histórico
        prom_compras = _promedio_compras(periodo, nombre)

        # 8. Severidad
        if abs(diferencia) == 0:
            severidad = "Correcto"
        elif abs(diferencia) <= SEVERIDAD_UMBRAL_MEDIO:
            severidad = "Observación"
        elif abs(diferencia) <= SEVERIDAD_UMBRAL_CRITICO:
            severidad = "Revisar"
        else:
            severidad = "Crítico"

        # ── Motor de causa sugerida (prioridad del prompt) ──────────────────
        causa = "Pendiente de revisión"
        evidencia = ""
        confianza = "Bajo"

        # Variables para evidencia estructurada
        factor_desvio = round(compras / prom_compras, 2) if prom_compras > 0 else 0.0
        comp_detectada, comp_evidencia, dif_anterior = _compensacion_conteo(
            periodo,
            nombre,
            diferencia,
        )
        compensacion_total = (
            comp_detectada
            and abs(diferencia + dif_anterior) < 0.01
        )

        # Detectar doble descuento: ajuste negativo coexiste con merma/vencidos registrados
        ajuste_negativo = ajuste < 0
        tiene_merma_o_vencido = (total_merma + total_venc) > 0
        alerta_doble_descuento = ajuste_negativo and tiene_merma_o_vencido

        if abs(diferencia) < 0.01:
            causa = "Sin diferencia"
            evidencia = "El conteo final coincide con el stock esperado."
            confianza = "Alto"
        elif compensacion_total:
            causa = "Compensación entre períodos"
            evidencia = comp_evidencia
            confianza = "Alto"
        elif alerta_continuidad:
            causa = "Inconsistencia de continuidad"
            evidencia = (
                f"El stock inicial del Excel ({stock_inicial_excel:.1f}) no coincide con "
                f"el stock final del período anterior ({stock_anterior:.1f}). "
                f"Revisar ajuste manual, compra fuera de período o error de arrastre."
            )
            confianza = "Alto"
        elif prom_compras > 0 and compras > prom_compras * COMPRA_RATIO_ALTO:
            ratio = round(compras / prom_compras, 1)
            causa = "Compra mal cargada"
            evidencia = (
                f"La compra registrada ({compras:.1f}) es {ratio}× superior al promedio "
                f"de las últimas semanas ({prom_compras:.1f}). "
                f"Posible error de unidad (caja vs. unidad) o decimal incorrecto."
            )
            confianza = "Alto"
        elif prom_compras > 0 and compras < prom_compras * COMPRA_RATIO_BAJO and compras > 0:
            causa = "Compra mal cargada"
            evidencia = (
                f"La compra registrada ({compras:.1f}) es muy inferior al promedio "
                f"({prom_compras:.1f}). Posible carga incompleta o error de cantidad."
            )
            confianza = "Medio"
        else:
            # Verificar compensación de conteo
            if comp_detectada:
                causa = "Error de conteo"
                evidencia = comp_evidencia
                confianza = "Alto" if "casi exactamente" in comp_evidencia else "Medio"
            elif total_venc > 0 or total_merma > 0:
                faltante_restante = abs(diferencia) - total_merma - total_venc
                if faltante_restante <= 0:
                    causa = "Producto vencido" if total_venc >= total_merma else "Merma o averiado"
                    evidencia = (
                        f"Merma registrada: {total_merma:.1f} unidades. "
                        f"Vencidos registrados: {total_venc:.1f} unidades. "
                        f"Explica la diferencia completa."
                    )
                    confianza = "Alto"
                else:
                    causa = "Merma o averiado"
                    evidencia = (
                        f"Merma: {total_merma:.1f}, Vencidos: {total_venc:.1f}. "
                        f"Diferencia pendiente sin justificar: {faltante_restante:.1f} unidades."
                    )
                    confianza = "Medio"
            else:
                causa = "Pendiente de revisión"
                evidencia = (
                    "No se encontraron registros de merma, vencimiento, "
                    "compras sospechosas ni compensaciones claras. Requiere revisión manual."
                )
                confianza = "Bajo"

        # Verificar productos relacionados (genera evidencia adicional, no cambia causa)
        rel_alertas = _verificar_relacionados(periodo, nombre, conteo_final, excel_row)
        if rel_alertas and causa == "Pendiente de revisión":
            causa = "Producto relacionado incoherente"
            evidencia = rel_alertas
            confianza = "Medio"

        # Advertir posible doble descuento (ajuste negativo + merma/vencidos)
        if alerta_doble_descuento:
            aviso = (
                f"⚠ Posible doble descuento: existe un ajuste negativo ({ajuste:+.1f}) "
                f"y mermas/vencidos registrados ({total_merma + total_venc:.1f} unidades). "
                f"Si el ajuste justifica la misma baja que las mermas, "
                f"marcá el ajuste con 'No impacta stock'."
            )
            evidencia = (aviso + " | " + evidencia) if evidencia else aviso

        if compensacion_total:
            tipo_diferencia = "compensado"
            severidad = "Correcto"
            impacto = 0.0

        estado_auditoria = (
            "Sin diferencia real" if compensacion_total
            else "Sin diferencia" if abs(diferencia) < 0.01
            else "Sugerido" if causa != "Pendiente de revisión"
            else "Pendiente"
        )

        # Estados defensivos: no convertir fuentes faltantes o corruptas en
        # diferencias reales. Se conserva la fila para que el usuario pueda
        # corregirla y volver a ejecutar la auditoría.
        item_inventario = (
            InventarioItem.query
            .filter_by(
                cliente_id=periodo.cliente_id,
                tienda_id=periodo.tienda_id,
                periodo_id=periodo.id,
            )
            .filter(db.func.lower(InventarioItem.producto) == pnorm)
            .first()
        )
        ume_faltante = bool(
            item_inventario is not None
            and not str(item_inventario.ume or "").strip()
        )
        sin_excel = excel_raw is None
        sin_inventario = not conteo_valido

        if sin_vinculacion:
            causa = "Pendiente de revisión"
            evidencia = "Producto del Excel pendiente de vinculación. Requiere revisión manual."
            confianza = "Bajo"
            estado_auditoria = "Pendiente"
        elif stock_excel_invalido:
            causa = "Pendiente de revisión"
            evidencia = (
                f"Stock inicial del Excel fuera de rango ({stock_inicial_excel:g}). "
                "Posible archivo corrupto; requiere revisión manual."
            )
            confianza = "Bajo"
            estado_auditoria = "Pendiente"
        elif ume_faltante:
            causa = "Pendiente de revisión"
            evidencia = "Producto sin UME definida; requiere revisión antes de conciliar."
            confianza = "Bajo"
            estado_auditoria = "Pendiente"
        elif sin_excel or sin_inventario:
            faltantes = []
            if sin_excel:
                faltantes.append("Excel oficial")
            if sin_inventario:
                faltantes.append("conteo de inventario")
            causa = "Pendiente de revisión"
            evidencia = (
                f"Sin datos de {' y '.join(faltantes)}. "
                "No se calcula una diferencia real; requiere revisión manual."
            )
            confianza = "Bajo"
            estado_auditoria = "Sin datos"
            tipo_diferencia = "correcto"
            severidad = "Observación"
            impacto = 0.0

        ar = AuditoriaResultado(
            periodo_id=periodo.id,
            cliente_id=periodo.cliente_id,
            producto_nombre=nombre,
            categoria=conteo.categoria if conteo else "",
            articulo_codigo=excel_raw.articulo if excel_raw else "",
            stock_inicial_anterior=stock_anterior if stock_anterior is not None else 0,
            stock_inicial_excel=stock_inicial_excel,
            alerta_continuidad=alerta_continuidad,
            compras=compras,
            promedio_compras_historico=round(prom_compras, 2),
            ventas=ventas,
            otros_ingresos=otros_ingresos,
            otras_salidas=otras_salidas,
            stock_final_excel=stock_final_excel,
            stock_esperado=round(stock_esperado, 2),
            conteo_empleado=round(conteo_empleado, 2),
            ajuste_admin=round(ajuste, 2),
            conteo_final=round(conteo_final, 2),
            diferencia=round(diferencia, 2),
            tipo_diferencia=tipo_diferencia,
            costo_unitario=costo_unit,
            impacto=round(impacto, 2),
            fuente_costo=fuente_costo,
            # Evidencia estructurada
            factor_desvio_compra=factor_desvio,
            diferencia_anterior_compensada=dif_anterior,
            cantidad_merma=round(total_merma, 2),
            cantidad_vencida=round(total_venc, 2),
            cantidad_averiada=round(total_merma, 2),            ventas_delivery=round(ventas_delivery, 2),            causa_sugerida=causa,
            evidencia=evidencia,
            nivel_confianza=confianza,
            severidad=severidad,
            # Sugerido = motor encontró una causa; Pendiente = sin evidencia
            estado_auditoria=estado_auditoria,
            usuario_conteo=conteo.usuario if conteo else "",
            usuario_ajuste=ajuste_usuario_map.get(pnorm, ""),
            fecha_ajuste=ajuste_fecha_map.get(pnorm, ""),
        )
        db.session.add(ar)
        resultados.append(ar)

    db.session.flush()

    # Solo se concilia automáticamente si existe al menos un resultado y
    # ninguno quedó sin las fuentes mínimas para calcularlo.
    if resultados and all(r.estado_auditoria != "Sin datos" for r in resultados):
        periodo.estado = "Conciliado"
    db.session.flush()

    return resultados


def _verificar_relacionados(
    periodo: InventarioPeriodo,
    producto_nombre: str,
    conteo_principal: float,
    excel_row: Optional[ExcelDetalle],
) -> str:
    """Genera texto de alerta si productos relacionados no cuadran."""
    relaciones = (
        ProductoRelacionado.query
        .filter_by(cliente_id=periodo.cliente_id, producto_principal=producto_nombre, activo=True)
        .all()
    )
    if not relaciones:
        return ""
    alertas = []
    for rel in relaciones:
        conteo_rel_row = ConteoDetalle.query.filter_by(
            periodo_id=periodo.id, producto_nombre=rel.producto_relacionado
        ).first()
        if not conteo_rel_row:
            continue
        conteo_rel = conteo_rel_row.total_unidad_base or 0
        esperado_rel = conteo_principal * rel.ratio_esperado
        if esperado_rel == 0:
            continue
        desviacion = abs(conteo_rel - esperado_rel) / esperado_rel
        if desviacion > rel.tolerancia:
            alertas.append(
                f"Se contaron {conteo_principal:.0f} unidades de '{producto_nombre}' "
                f"pero solo {conteo_rel:.0f} de '{rel.producto_relacionado}' "
                f"(esperado: {esperado_rel:.0f}, desviación: {desviacion*100:.0f}%)."
            )
    return " | ".join(alertas)


def marcar_resultado_revisado(
    resultado: AuditoriaResultado,
    usuario: str,
) -> Justificacion:
    """Marca un resultado como revisado y registra quién realizó el cambio."""
    traza = Justificacion(
        resultado_id=resultado.id,
        cliente_id=resultado.cliente_id,
        causa="Marcado como revisado",
        cantidad_justificada=0,
        importe_justificado=0,
        observacion="Resultado revisado manualmente sin modificar los datos históricos.",
        usuario=usuario,
    )
    db.session.add(traza)
    resultado.estado_auditoria = "Revisado"
    return traza


# ─── Reporte gerencial ────────────────────────────────────────────────────────

def build_reporte_gerencial(periodo: InventarioPeriodo) -> dict:
    """Arma el contexto para la vista del reporte gerencial."""
    resultados = (
        AuditoriaResultado.query
        .filter_by(periodo_id=periodo.id)
        .filter(AuditoriaResultado.tipo_diferencia == "faltante")
        .order_by(AuditoriaResultado.impacto.desc())
        .all()
    )
    total_perdida = sum(r.impacto for r in resultados)
    por_causa: dict[str, dict] = {}
    for r in resultados:
        c = r.causa_sugerida
        if c not in por_causa:
            por_causa[c] = {"cantidad": 0, "importe": 0.0}
        por_causa[c]["cantidad"] += 1
        por_causa[c]["importe"] += r.impacto

    alertas_criticas = [r for r in resultados if r.severidad == "Crítico"]
    cargas = (
        ConteoDetalle.query
        .filter_by(periodo_id=periodo.id, fue_cargado=True)
        .order_by(ConteoDetalle.categoria, ConteoDetalle.producto_nombre)
        .all()
    )

    # KPI causa dominante: la causa con mayor importe acumulado
    causa_dominante = None
    if por_causa:
        top_causa = max(por_causa.items(), key=lambda x: x[1]["importe"])
        causa_dominante = {"nombre": top_causa[0], "importe": top_causa[1]["importe"], "cantidad": top_causa[1]["cantidad"]}
    periodo_anterior = (
        InventarioPeriodo.query
        .filter(
            InventarioPeriodo.cliente_id == periodo.cliente_id,
            InventarioPeriodo.tienda_id == periodo.tienda_id,
            InventarioPeriodo.id != periodo.id,
            InventarioPeriodo.fecha_desde < periodo.fecha_desde,
        )
        .order_by(InventarioPeriodo.fecha_desde.desc())
        .first()
    )
    comparacion = None
    if periodo_anterior:
        res_ant = (
            AuditoriaResultado.query
            .filter_by(periodo_id=periodo_anterior.id)
            .filter(AuditoriaResultado.tipo_diferencia == "faltante")
            .all()
        )
        perdida_anterior = sum(r.impacto for r in res_ant)
        faltantes_actual = len(resultados)
        faltantes_anterior = len(res_ant)
        criticos_actual = len(alertas_criticas)
        criticos_anterior = sum(1 for r in res_ant if r.severidad == "Crítico")
        delta = total_perdida - perdida_anterior
        if delta > 0:
            tendencia, flecha, clase = "empeoró", "↑", "danger"
        elif delta < 0:
            tendencia, flecha, clase = "mejoró", "↓", "success"
        else:
            tendencia, flecha, clase = "igual", "=", "secondary"
        porcentaje = round(abs(delta) / perdida_anterior * 100, 1) if perdida_anterior else None
        comparacion = {
            "periodo_anterior": periodo_anterior,
            "perdida_anterior": perdida_anterior,
            "faltantes_anterior": faltantes_anterior,
            "faltantes_actual": faltantes_actual,
            "delta_faltantes": faltantes_actual - faltantes_anterior,
            "criticos_anterior": criticos_anterior,
            "criticos_actual": criticos_actual,
            "delta_criticos": criticos_actual - criticos_anterior,
            "delta": delta,
            "delta_perdida": delta,
            "porcentaje": porcentaje,
            "tendencia": tendencia,
            "flecha": flecha,
            "clase": clase,
        }

    return {
        "periodo": periodo,
        "faltantes": resultados,
        "total_perdida": total_perdida,
        "por_causa": por_causa,
        "causa_dominante": causa_dominante,
        "alertas_criticas": alertas_criticas,
        "cargas": cargas,
        "comparacion": comparacion,
    }


def justificar_resultado(
    resultado: AuditoriaResultado,
    periodo: InventarioPeriodo,
    *,
    causa: str,
    cantidad: float,
    observacion: str,
    usuario: str,
) -> Justificacion:
    """Registra una justificación y actualiza el estado del resultado/período."""
    justificacion = Justificacion(
        resultado_id=resultado.id,
        cliente_id=resultado.cliente_id,
        causa=causa,
        cantidad_justificada=cantidad,
        importe_justificado=cantidad * (resultado.costo_unitario or 0),
        observacion=observacion,
        usuario=usuario,
    )
    db.session.add(justificacion)
    resultado.estado_auditoria = "Justificado"
    db.session.flush()

    pendientes = AuditoriaResultado.query.filter(
        AuditoriaResultado.periodo_id == periodo.id,
        AuditoriaResultado.estado_auditoria.in_(["Pendiente", "Sugerido"]),
        AuditoriaResultado.tipo_diferencia != "correcto",
    ).count()
    if pendientes == 0 and periodo.estado == "Conciliado":
        periodo.estado = "Auditado"
    return justificacion
