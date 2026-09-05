# Módulo: Averiados y Vencimientos

## Tablas involucradas
| Tabla | Descripción |
|---|---|
| `registros_averiados` | Productos dañados registrados por empleado |
| `registros_vencimiento` | Productos próximos a vencer registrados por empleado |

## Campos comunes
- `tienda_id`, `usuario`, `fecha`, `producto`, `categoria`
- `cantidad` (en UME original) + `cantidad_unidades` (convertida)
- `sinc_estado`: `pendiente` → `sincronizado`
- `revisado`: `False` → admin lo vio (`True`)

## Diferencia entre tablas
`registros_vencimiento` agrega `fecha_vencimiento` (cuándo vence el producto).

## Relaciones con auditoría
El motor de auditoría (`core/auditoria.py`) consulta ambas tablas al calcular la venta teórica:
```python
mermas_averiados = sum(r.cantidad_unidades for r in registros_averiados del período)
vencidos         = sum(r.cantidad_unidades for r in registros_vencimiento del período)
venta_teorica  -= mermas_averiados + vencidos
```
Esto las descuenta una sola vez como bajas no imputables al empleado. La diferencia
residual se calcula luego como `venta_real - venta_teorica`: un resultado positivo
es sobrante y uno negativo es faltante.

## Rutas empleado
| Método | Ruta | Acción |
|---|---|---|
| GET/POST | `/empleado/averiado` | Registrar producto averiado |
| POST | `/empleado/averiado/<id>/eliminar` | Eliminar (solo pendiente) |
| GET/POST | `/empleado/vencimiento` | Registrar producto próximo a vencer |
| POST | `/empleado/vencimiento/<id>/eliminar` | Eliminar (solo pendiente) |

## Rutas admin
| Método | Ruta | Acción |
|---|---|---|
| GET | `/admin/averiados` | Lista con filtros; marca `revisado=True` al ver |
| POST | `/admin/averiados/revisar` | Marca en lote como revisados |
| GET | `/admin/vencimientos` | Igual para vencimientos |
| POST | `/admin/vencimientos/revisar` | Marca en lote |

## Notificaciones en sidebar
- `notif_averiados` = `count(sinc_estado='sincronizado', revisado=False)`
- `notif_vencimientos` = ídem para vencimientos
- Se inyectan en todas las plantillas vía `@app.context_processor`

## Módulo backend
- `core/empleado.py` — `registrar_averiado()`, `registrar_vencimiento()`
- `core/admin_vencimientos.py` — `build_admin_vencimientos_context()`
