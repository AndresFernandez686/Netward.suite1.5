# Módulo: Inventario del Empleado (Carga móvil)

## Tablas involucradas
| Tabla | Descripción |
|---|---|
| `inventario_items` | Stock actual por tienda/producto; estado `pendiente` o `sincronizado` |
| `historial` | Registro de cada movimiento individual |
| `inventario_snapshots` | Resumen de una sesión de carga: fecha, tienda, usuario, total_items |

## Relaciones
- `inventario_items.tienda_id` → `tiendas.id`
- `inventario_items.cliente_id` → `clientes.id`
- `historial.tienda_id` → `tiendas.id`
- `inventario_snapshots` → referencia lógica a `historial` por (tienda_id, fecha, usuario)

## Constraint clave
```sql
UNIQUE (tienda_id, categoria, producto)  -- inventario_items
```
Solo existe un registro de stock por producto/tienda. Guardar actualiza `cantidad`.

## Rutas principales
| Método | Ruta | Acción |
|---|---|---|
| GET | `/empleado/inventario` | Pantalla de carga con carrito por categoría |
| POST | `/empleado/carrito/agregar` | Agrega ítem al carrito de sesión (no BD aún) |
| POST | `/empleado/carrito/guardar` | Persiste carrito → `inventario_items` + `historial` + `inventario_snapshots` |
| POST | `/empleado/sincronizar` | Marca `sinc_estado = 'sincronizado'`, propaga a `conteo_detalle` |

## Flujo
```
Empleado agrega producto al carrito (session Flask)
   ↓
Guardar: upsert en inventario_items (sinc_estado='pendiente')
       + INSERT en historial (1 fila por ítem)
       + INSERT/UPDATE inventario_snapshots
   ↓
Sincronizar: UPDATE sinc_estado → 'sincronizado'
           + sync_bridge: copia a conteo_detalle del período activo
```

## Conversión de unidades
```
Caja  → cantidad × unidades_por_caja
Bulto → cantidad × unidades_por_bulto
```
El resultado se guarda como unidades en `inventario_items.cantidad`.

## Módulo backend
- `core/empleado.py` — `add_carrito_item()`, `build_carrito_guardado()`, `procesar_sincronizacion()`
- `core/sync_bridge.py` — propaga al período de auditoría activo automáticamente al sincronizar
