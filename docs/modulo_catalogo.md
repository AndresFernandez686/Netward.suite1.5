# Módulo: Catálogo y Productos

## Tablas involucradas
| Tabla | Descripción |
|---|---|
| `productos` | Catálogo base: `id`, `nombre`, `categoria`, `visible_empleado` |
| `producto_precios` | Precio y conversiones: `producto_nombre`, `precio`, `unidades_por_caja`, `unidades_por_bulto` |
| `stock_thresholds` | Umbrales de alerta: `producto`, `critico`, `medio` |

## Relaciones
- `producto_precios.producto_nombre` → referencia lógica a `productos.nombre` (sin FK explícita, match por nombre lowercase)
- `stock_thresholds.producto` → referencia lógica a `productos.nombre`
- `productos` no tiene `cliente_id`; el catálogo es compartido por todos los usuarios

## Rutas principales
| Método | Ruta | Acción |
|---|---|---|
| GET/POST | `/admin/configuracion` | Lista productos por categoría, crear/eliminar |
| POST | `/admin/producto/crear` | Inserta en `productos` |
| POST | `/admin/producto/<id>/eliminar` | Borra de `productos` (solo si no tiene historial) |
| GET/POST | `/admin/precios` | CRUD en `producto_precios` |

## Flujo
```
Admin crea producto (productos)
   ↓
Admin carga precio + conversiones (producto_precios)
   ↓
Empleado ve solo productos con visible_empleado=True
   ↓
Sistema convierte Caja/Bulto usando unidades_por_caja / unidades_por_bulto
```

## Módulo backend
- `core/catalogo.py` — `get_productos_db(include_hidden)`, `activar_catalogo_pendiente_empleado()`
- `core/admin_inventario.py` — `_productos_por_categoria()`, `_precios_lookup()`
- `core/empleado.py` — `convertir_ume()` usa `ProductoPrecio`

## Notas
- Ocultar un producto (`visible_empleado=False`) no borra su historial
- La conversión de Caja/Bulto requiere que exista un registro en `producto_precios`
- Si no hay precio cargado, el sistema funciona pero no calcula valor monetario
