# Módulo: Períodos de Inventario (Auditoría correlativa)

## Tablas involucradas
| Tabla | Descripción |
|---|---|
| `inventario_periodos` | Período semanal/quincenal con estado y fechas |
| `conteo_detalle` | Un registro por producto por período; distingue `fue_cargado=True/False` |
| `ajustes_inventario` | Ajustes administrativos posteriores al conteo del empleado |

## Relaciones
```
inventario_periodos (1) ──< conteo_detalle       (FK: periodo_id)
inventario_periodos (1) ──< ajustes_inventario   (FK: periodo_id)
inventario_periodos (1) ──< excel_importados     (FK: periodo_id)
inventario_periodos (1) ──< auditoria_resultados (FK: periodo_id)
```

## Estados del período
```
Abierto → Pendiente → Sincronizado → Cerrado → Conciliado → Auditado
```
- **Abierto**: disponible para carga
- **Cerrado**: no editable por empleado (manual o automático)
- **Conciliado**: Excel oficial importado
- **Auditado**: motor de auditoría ejecutado

## Regla de continuidad
```
stock_final(período N) = stock_inicial(período N+1)
```
Si no coincide con el Excel, `alerta_continuidad = True` en `auditoria_resultados`.

## Regla crítica: 0 ≠ sin cargar
| Valor | Significado |
|---|---|
| `total_unidad_base = 0` con `fue_cargado = True` | Empleado confirmó que no hay stock |
| `fue_cargado = False` | Producto no contado — no permite cierre |

## Rutas principales
| Método | Ruta | Acción |
|---|---|---|
| GET | `/admin/periodos` | Lista períodos |
| POST | `/admin/periodos/crear` | Crea período nuevo (auto-numerado por tienda) |
| GET | `/admin/periodos/<id>` | Detalle: conteos, ajustes, Excel, botones de acción |
| POST | `/admin/periodos/<id>/cerrar` | Cierra el período (valida productos sin cargar) |
| POST | `/admin/periodos/<id>/conteo/manual` | Carga conteo directo desde admin |
| POST | `/admin/periodos/<id>/ajuste` | Agrega ajuste sin sobrescribir conteo original |

## Auto-cierre automático
- Configurado en `configuracion_sistema` (clave `autoclose_horas`, default 24)
- APScheduler corre cada 30 min → cierra períodos cuyo `fecha_hasta + horas` ya pasó
- Ruta de configuración: `GET/POST /admin/periodos/config/autoclose`

## Módulo backend
- `core/scheduler.py` — job `job_autoclose_periodos()`, `get/set_autoclose_horas()`
- `core/sync_bridge.py` — `propagar_conteo_a_periodo()` al sincronizar · `retroalimentar_periodo_desde_items()` al crear

## Flujo
```
Admin crea período con rango de fechas
   ↓ retroalimentar_periodo_desde_items()
     Lee HistorialMovimiento dentro del rango → inserta en conteo_detalle
     (si no hay historial: usa InventarioItem sincronizados actuales)

Empleado carga y sincroniza (después o en paralelo)
   ↓ propagar_conteo_a_periodo(): upsert en conteo_detalle
   período pasa a estado='Pendiente'

Admin cierra el período (o auto-cierre por scheduler)
```

## Garantía de datos
Si el empleado cargó **antes** de que el período fuera creado, las cargas no se pierden:
`retroalimentar_periodo_desde_items()` las jala desde `historial` al momento de crear.
