# Módulo: Exportación Final de Auditoría (Excel)

> **Objetivo:** El Excel exportado debe permitir al administrador hacer análisis completos **sin volver a trabajar manualmente en Excel**. Un solo archivo, todas las columnas, listo para filtrar y analizar.

---

## Secciones requeridas y estado actual

### 1. Trazabilidad completa

| Columna | Estado | Nombre en export actual |
|---|---|---|
| Período (número) | ✅ | `Inventario` |
| Fecha Desde / Fecha Hasta | ✅ | `Fecha Desde`, `Fecha Hasta` |
| Producto | ✅ | `Producto` |
| Código Producto | ✅ | `Código Producto` |
| Usuario Conteo | ✅ | `Usuario Conteo` |
| Fecha Conteo | ❌ No incluida | — |
| Usuario Ajuste | ✅ | `Usuario Ajuste` |
| Fecha Ajuste | ✅ | `Fecha Ajuste` |
| Usuario Justificación | ❌ No incluida | — |
| Fecha Justificación | ❌ No incluida | — |

---

### 2. Datos de inventario

| Columna | Estado | Nombre en export actual |
|---|---|---|
| Stock Inicial Anterior | ✅ | `Stock Inicial Anterior` |
| Stock Inicial Excel | ✅ | `Stock Inicial Excel` |
| Compras | ✅ | `Compras` |
| Ventas | ✅ | `Ventas (Excel oficial)` |
| Otros Ingresos | ✅ | `Otros Ingresos` |
| Otras Salidas | ✅ | `Otras Salidas` |
| Stock Esperado | ✅ | `Stock Esperado Sistema` |
| Conteo Empleado | ✅ | `Conteo Empleado` |
| Ajuste Admin | ✅ | `Ajuste Admin` |
| Conteo Final | ✅ | `Conteo Final` |

---

### 3. Resultado de auditoría

| Columna | Estado | Nombre en export actual |
|---|---|---|
| Diferencia | ✅ | `Diferencia` |
| Tipo Diferencia (Faltante/Sobrante/Correcto) | ✅ | `Tipo Diferencia` |
| Impacto Económico | ✅ | `Impacto` |
| Severidad | ✅ Implementado | `Severidad` |
| Alerta Continuidad | ✅ | `Alerta Continuidad` |

---

### 4. Diagnóstico automático

| Columna | Estado | Nombre en export actual |
|---|---|---|
| Causa Sugerida | ✅ | `Posible Causa Principal` |
| Evidencia | ✅ | `Evidencia` |
| Nivel de Confianza | ✅ | `Nivel de Confianza` |

**Ejemplo de fila correcta:**

| Causa Sugerida | Evidencia | Nivel de Confianza |
|---|---|---|
| Compra mal cargada | La compra es 8 veces superior al promedio histórico | Alto |

---

### 5. Justificación humana

| Columna | Estado | Observación |
|---|---|---|
| Justificación Manual | ✅ Implementado | `jus.causa` |
| Observación | ✅ Implementado | `jus.observacion` |
| Estado Auditoría | ✅ | `Estado Auditoría` |

**Bug confirmado:** en `admin_auditoria_exportar()` (`app.py` ~línea 2140), `jus` se consulta con:
```python
jus = (Justificacion.query.filter_by(resultado_id=r.id)
       .order_by(Justificacion.id.desc()).first())
```
pero sus campos **nunca se escriben en la fila**. Deben agregarse al final del array `row[]`.

**Ejemplo de fila correcta:**

| Justificación Manual | Observación | Estado Auditoría |
|---|---|---|
| Error de conteo | Caja encontrada posteriormente | Justificado |

---

### 6. Filtrable

El administrador debe poder filtrar el export por:

| Filtro | Estado |
|---|---|
| Producto | ❌ No hay filtro pre-export — se filtra en Excel manualmente |
| Período | ❌ El export es por período fijo, no multi-período |
| Causa | ❌ No hay filtro pre-export |
| Confianza | ❌ No hay filtro pre-export |
| Tipo Diferencia / Severidad | ❌ No hay filtro pre-export |

**Opción A (simple):** Activar `AutoFilter` en openpyxl sobre la fila de encabezado:
```python
ws.auto_filter.ref = ws.dimensions
```
Esto habilita los filtros nativos de Excel en todas las columnas sin cambiar el backend.

**Opción B (completa):** Agregar parámetros GET a la ruta de exportación (`causa=`, `confianza=`, `tipo=`) para filtrar `resultados` antes de escribir el Excel.

---

## Resumen de pendientes

| # | Problema | Dificultad |
|---|---|---|
| 1 | ~~Agregar columna `Severidad`~~ | ✅ Hecho |
| 2 | Agregar `Fecha Conteo` | Campo no existe en el modelo `AuditoriaResultado` — requiere migración |
| 3 | ~~Agregar `Justificación Manual` y `Observación` desde `jus`~~ | ✅ Hecho |
| 4 | ~~Agregar `Usuario Justificación` y `Fecha Justificación`~~ | ✅ Hecho |
| 5 | ~~Activar AutoFilter nativo de Excel~~ | ✅ Hecho |
| 6 | Filtros pre-export por causa/confianza/tipo | Media — parámetros GET + filtro en query |

---

## Archivos relevantes

| Archivo | Rol |
|---|---|
| `app.py` → `admin_auditoria_exportar()` (~línea 2084) | Genera el Excel — aquí van todos los cambios |
| `core/models.py` → `AuditoriaResultado`, `Justificacion` | Fuente de datos |
| `templates/admin_auditoria.html` | Botón de exportación |
