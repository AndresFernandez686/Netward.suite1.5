# Módulo: Importación de Excel Oficial

## Tablas involucradas
| Tabla | Descripción |
|---|---|
| `excel_importados` | Cabecera del archivo importado: archivo, fecha, usuario, estado_validacion |
| `excel_detalles` | Una fila por producto del Excel: columnas oficiales + vínculo interno |

## Relaciones
```
excel_importados.periodo_id → inventario_periodos.id
excel_detalles.excel_id     → excel_importados.id
excel_detalles.producto_nombre_interno → referencia lógica a productos.nombre
```

## Columnas clave del Excel externo
| Columna | Uso en auditoría |
|---|---|
| `articulo` | Clave de vinculación (código estable del sistema externo) |
| `artcosto` | Costo unitario oficial (prioridad sobre precio interno) |
| `stockinicial` | Stock inicial según sistema externo |
| `compras` | Compras del período |
| `ventareal` | Ventas reales del período |
| `stockfinal` | Stock final del sistema externo |

## Vinculación de productos
1. El importador normaliza `artdescrip` (lowercase, sin espacios extra)
2. Busca coincidencia exacta en `productos.nombre`
3. Si no encuentra: busca coincidencia parcial
4. Si tampoco: guarda `producto_nombre_interno = NULL` y marca `estado_validacion = 'pendiente_vinculacion'`
5. Admin vincula manualmente por `POST /admin/periodos/<id>/excel/<excel_id>/vincular`

## Rutas principales
| Método | Ruta | Acción |
|---|---|---|
| POST | `/admin/periodos/<id>/excel/importar` | Sube archivo, parsea, crea `excel_importados` + `excel_detalles` |
| POST | `/admin/periodos/<id>/excel/<excel_id>/vincular` | Asigna `producto_nombre_interno` manualmente |

## Flujo
```
Admin sube .xlsx/.xls
   ↓
core/excel_importer.py detecta columnas automáticamente
   ↓
Excluye grupos: canjes, congelados, frizzio, promociones, limpieza
   ↓
Por cada fila: intenta vincular articulo → producto interno
   ↓
Guarda excel_importados + excel_detalles
   ↓
periodo.estado → 'Conciliado'
```

## Módulo backend
- `core/excel_importer.py` — `importar_excel()`, `_detectar_columnas()`, `_build_nombre_map()`

## Notas
- No se crean productos automáticamente — siempre requieren revisión del admin
- El sistema acepta `.xlsx` (openpyxl) y `.xls` (xlrd)
- `articulo` es la clave estable; `artdescrip` puede variar entre archivos
