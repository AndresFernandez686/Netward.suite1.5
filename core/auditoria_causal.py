"""Explicaciones causales legibles para resultados de auditoría."""
from __future__ import annotations

from typing import Any


def explicar_causa_diferencia(resultado: Any) -> dict[str, Any]:
    """Explica el desbalance sin convertir hipótesis en hechos."""
    esperado = float(resultado.stock_esperado or 0)
    fisico = float(resultado.conteo_final or 0)
    diferencia = float(resultado.diferencia or 0)
    magnitud = abs(diferencia)
    teorica = float(resultado.venta_teorica or 0)
    real = float(resultado.ventas or 0)
    estado = str(resultado.estado_auditoria or "")
    causa = str(resultado.causa_sugerida or "Pendiente de revisión")
    confianza = str(resultado.nivel_confianza or "Bajo")
    evidencia = str(resultado.evidencia or "").strip()

    if estado == "Sin datos":
        return {
            "nivel": "sin_datos", "etiqueta": "Causa no evaluable",
            "causa_principal": "Faltan fuentes obligatorias", "certeza": "No evaluable",
            "por_que_no_coincide": (
                "Los números no pueden conciliarse oficialmente porque falta el Excel oficial, "
                "el conteo físico o ambos. Los ceros del motor son valores técnicos, no prueba "
                "de que no hubo movimientos."
            ),
            "resumen": evidencia or "Faltan fuentes para evaluar la diferencia.",
            "hipotesis": [],
            "verificaciones": [
                "Vincular la fila correcta del producto en el Excel oficial.",
                "Confirmar el conteo físico y su unidad de medida.",
                "Reejecutar la auditoría después de completar las fuentes.",
            ],
        }

    if abs(diferencia) < 0.01:
        return {
            "nivel": "conciliado", "etiqueta": "Sin diferencia",
            "causa_principal": "Los movimientos y el conteo coinciden", "certeza": "Alta",
            "por_que_no_coincide": "No existe un desbalance residual que explicar.",
            "resumen": f"El stock esperado ({esperado:g}) coincide con el stock físico ({fisico:g}).",
            "hipotesis": [], "verificaciones": [],
        }

    if diferencia < 0:
        mecanismo = (
            f"Con los movimientos registrados debían quedar {esperado:g} unidades, pero el "
            f"conteo encontró {fisico:g}. Faltan {magnitud:g} unidades para conciliar. "
            f"El inventario refleja una salida de {teorica:g}, mayor que la venta real "
            f"registrada de {real:g}."
        )
        hipotesis = [
            {"causa": "Conteo físico menor o incompleto",
             "por_que": "Un conteo final subestimado aumenta directamente el faltante.",
             "verificar": "Recontar y confirmar unidad, caja y factor de conversión."},
            {"causa": "Venta o salida no registrada",
             "por_que": "Una venta, canje, traslado o consumo omitido deja stock sin explicar.",
             "verificar": "Comparar ventas, Delivery, canjes, traslados y otras salidas."},
            {"causa": "Stock inicial, compra o ingreso sobreestimado",
             "por_que": "Una entrada duplicada infla el stock que debía quedar.",
             "verificar": "Revisar stock inicial, facturas, compras, otros ingresos y conversiones."},
        ]
    else:
        mecanismo = (
            f"Con los movimientos registrados debían quedar {esperado:g} unidades, pero el "
            f"conteo encontró {fisico:g}. Hay {magnitud:g} unidades más de las que explican "
            f"los registros. La venta real de {real:g} supera la salida reconstruida de {teorica:g}."
        )
        hipotesis = [
            {"causa": "Entrada, compra o stock inicial no registrado",
             "por_que": "Un ingreso ausente hace que el sistema espere menos stock del existente.",
             "verificar": "Revisar stock inicial, facturas, compras, recepciones y otros ingresos."},
            {"causa": "Venta real duplicada o sobreestimada",
             "por_que": "Ventas registradas de más reducen artificialmente el stock esperado.",
             "verificar": "Comparar Excel, Delivery y comprobantes para detectar duplicados."},
            {"causa": "Conteo físico mayor o unidad incorrecta",
             "por_que": "Un conteo sobreestimado genera unidades sin origen documentado.",
             "verificar": "Recontar y validar UME y factores caja/unidad o kilo/unidad."},
        ]

    generica = causa in {"", "Pendiente de revisión", "Sin diferencia"}
    respaldada = not generica and confianza in {"Alto", "Medio"}
    if respaldada:
        resumen = (
            f"La evidencia apunta a '{causa}' con confianza {confianza.lower()}. "
            f"{evidencia or 'Debe confirmarse con el documento operativo correspondiente.'}"
        )
    else:
        resumen = (
            "El sistema demuestra dónde se rompe la conciliación, pero todavía no puede "
            "atribuirla a una causa única. Las posibilidades deben verificarse antes de concluir."
        )
    return {
        "nivel": "probable" if respaldada else "no_determinada",
        "etiqueta": "Causa probable respaldada" if respaldada else "Causa a confirmar",
        "causa_principal": causa if respaldada else "Pendiente de comprobación",
        "certeza": confianza if respaldada else "Baja",
        "por_que_no_coincide": mecanismo,
        "resumen": resumen,
        "hipotesis": hipotesis,
        "verificaciones": [item["verificar"] for item in hipotesis],
    }
