# Módulo: Delivery

## Tablas involucradas
| Tabla | Descripción |
|---|---|
| `delivery_productos` | Catálogo de productos disponibles para delivery: `nombre`, `precio`, `es_promocion`, `activo` |
| `delivery_ventas` | Venta registrada: `fecha`, `producto`, `cantidad`, `precio_unitario`, `total`, `usuario`, `tienda_id` |

## Relaciones
- `delivery_ventas.tienda_id` → `tiendas.id`
- `delivery_ventas.producto` → referencia lógica a `delivery_productos.nombre`
- El motor de auditoría usa `delivery_ventas` como fuente de ventas reales del período

## Rutas empleado
| Método | Ruta | Acción |
|---|---|---|
| GET/POST | `/empleado/delivery` | Ver catálogo activo y registrar venta |

## Rutas admin
| Método | Ruta | Acción |
|---|---|---|
| GET/POST | `/admin/delivery` | CRUD catálogo de productos |
| POST | `/admin/delivery/<id>/toggle` | Activar/desactivar producto |

## Uso en el inventario descriptivo (legacy)
En el proceso `/admin/desc`, las ventas de `delivery_ventas` reemplazan la columna `ventareal` del Excel oficial para el rango de fechas seleccionado.

## Módulo backend
- `core/empleado.py` — `build_delivery_context()`, `registrar_venta_delivery()`
