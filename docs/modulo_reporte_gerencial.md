# Módulo: Reporte Gerencial

> **En una frase:** El reporte gerencial debe mostrar **qué se perdió, cuánto dinero representa, por qué ocurrió y si el negocio está mejorando o empeorando respecto al período anterior.**

---

## Principio de diseño: qué NO mostrar

El gerente no necesita — y no debe ver — datos técnicos de auditoría:

| Campo técnico | Por qué no va en gerencia |
|---|---|
| `stockinicial` | Dato operativo de conteo |
| `ventateorica` | Cálculo interno de auditoría |
| `otrosingresos` / `otrassalidas` | Detalles de movimientos contables |
| `conteo_detalle` | Registro raw del empleado |
| `excel_detalles` | Export para auditor, no para gerente |

Esos campos pertenecen a la vista de **Auditoría** (`admin_auditoria.html`), nunca al reporte gerencial.

---

## Checklist del reporte ideal (10/10)

- [ ] Resumen ejecutivo
- [ ] Total perdido
- [ ] Top productos con pérdida
- [ ] Resumen por causa
- [ ] Alertas críticas
- [ ] Comparación contra período anterior
- [ ] Recomendación o conclusión automática

---

El reporte gerencial responde **5 preguntas clave** en menos de un minuto, dando al gerente una visión clara de pérdidas, causas y tendencias por período de inventario.

---

## 1. ¿Cuánto dinero se perdió?

### Lo que el sistema hace hoy
- KPI principal: **Total pérdida estimada** (Gs.) calculado en `build_reporte_gerencial()` como suma de `AuditoriaResultado.impacto` donde `tipo_diferencia == "faltante"`.
- KPI secundario: conteo de productos con faltante.
- KPI terciario: conteo de alertas críticas.
- KPI cuarto: duración del período en días.

### Lo que falta
- Desglose de pérdida por **categoría** (Impulsivo / Por Kilos / Extras).
- Porcentaje de pérdida sobre el **valor total del inventario** del período.
- Comparación nominal con el período anterior (ver sección 5).

---

## 2. ¿Qué productos generaron la mayor pérdida?

### Lo que el sistema hace hoy
- Tabla completa de faltantes ordenada por `impacto DESC`.
- Columnas: producto, categoría, faltante (unid.), costo unitario, valor perdido, causa, evidencia, confianza, estado auditoría.

### Lo que falta
- Vista resumida **Top 5 / Top 10** (selector) con solo tres columnas: Producto · Cantidad faltante · Impacto económico (Gs.).
- Gráfico de barras horizontales con los N productos de mayor impacto.

---

## 3. ¿Cuál fue la causa principal?

### Lo que el sistema hace hoy
- Tabla `por_causa`: causa → cantidad de productos + importe total en Gs.
- Causas posibles: Compra mal cargada · Error de conteo · Merma · Vencido · Pendiente de revisión.
- Fila de totales con suma global.

### Lo que falta
- Ordenamiento explícito por importe descendente (actualmente el diccionario no garantiza orden en la vista).
- Gráfico de torta/dona con la distribución por causa.
- Indicador de **causa dominante** destacado como KPI (ej. "La causa principal fue _Error de conteo_ con Gs. X").

---

## 4. ¿Qué fue crítico?

### Lo que el sistema hace hoy
- Tabla de **alertas críticas** (`severidad == "Crítico"`), con fondo rojo por fila, mostrando: producto, faltante, impacto, causa sugerida, nivel de confianza.

### Lo que falta
- Ranking explícito de:
  - **Mayor impacto económico** (top 1 producto con más Gs. perdidos).
  - **Mayor diferencia** (top 1 producto con más unidades faltantes).
  - **Mayor riesgo** (top 1 por criticidad × confianza).
- Estos tres pueden mostrarse como KPI cards destacadas encima de la tabla de críticos.

---

## 5. ¿Está mejorando o empeorando?

### Lo que el sistema hace hoy
- No implementado.

### Lo que falta — spec completo

Requiere comparar el período actual contra el período anterior de la misma tienda/cliente.

**Datos a comparar:**

| Métrica | Período anterior | Período actual | Δ |
|---|---|---|---|
| Total pérdida (Gs.) | — | — | ↑ / ↓ |
| Productos con faltante | — | — | ↑ / ↓ |
| Alertas críticas | — | — | ↑ / ↓ |

**Lógica de implementación:**
1. En `build_reporte_gerencial()`, buscar el período anterior con:
   ```python
   periodo_anterior = InventarioPeriodo.query.filter(
       InventarioPeriodo.cliente_id == periodo.cliente_id,
       InventarioPeriodo.tienda_id == periodo.tienda_id,
       InventarioPeriodo.id != periodo.id,
       InventarioPeriodo.fecha_desde < periodo.fecha_desde,
   ).order_by(InventarioPeriodo.fecha_desde.desc()).first()
   ```
2. Si existe, calcular mismas métricas y exponer `comparacion` en el contexto.
3. Mostrar flechas ↑ (rojo) / ↓ (verde) / = (gris) junto a cada KPI.

---

## Estado de implementación

| Pregunta | Estado |
|---|---|
| 1. ¿Cuánto dinero se perdió? | ✅ Básico implementado — falta desglose por categoría |
| 2. ¿Qué productos generaron la mayor pérdida? | ⚠️ Tabla completa — falta vista Top 5/10 + gráfico |
| 3. ¿Cuál fue la causa principal? | ⚠️ Tabla implementada — falta KPI causa dominante + gráfico |
| 4. ¿Qué fue crítico? | ⚠️ Tabla críticos implementada — faltan KPI cards mayor impacto/diferencia/riesgo |
| 5. ¿Está mejorando o empeorando? | ❌ No implementado |

---

## Archivos relevantes

| Archivo | Rol |
|---|---|
| `core/auditoria.py` → `build_reporte_gerencial()` | Lógica de datos del reporte |
| `templates/admin_reporte_gerencial.html` | Vista del reporte |
| `app.py` → `admin_reporte_gerencial()` (línea 2073) | Ruta Flask |
| `core/models.py` → `AuditoriaResultado`, `InventarioPeriodo` | Modelos de datos |
