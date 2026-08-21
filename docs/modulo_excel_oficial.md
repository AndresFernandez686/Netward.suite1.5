# Módulo: Importación de Excel Oficial

## Tablas involucradas
| Tabla | Descripción |
|---|---|
| `excel_importados` | Cabecera del archivo importado: archivo, fecha, usuario, estado_validacion |
| `excel_detalles` | Una fila por producto del Excel: columnas oficiales + vínculo interno |
| `excel_detalle_ediciones` | Historial de celdas modificadas: usuario, fecha y valores anterior/nuevo |

## Relaciones
```
excel_importados.periodo_id → inventario_periodos.id
excel_detalles.excel_id     → excel_importados.id
excel_detalle_ediciones.detalle_id → excel_detalles.id
excel_detalles.producto_nombre_interno → referencia lógica a productos.nombre
```

## Columnas clave del Excel externo
| Columna | Uso en auditoría |
|---|---|
| `articulo` | Clave de vinculación (código estable del sistema externo) |
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

La vinculación también compara cantidades de presentación escritas como `x54`,
`x 78` o `×120`. Si ambos nombres contienen una cantidad y no coincide, el código,
el alias y la similitud textual no pueden forzar la relación. La fila queda
pendiente para evitar que Auditoría mezcle presentaciones diferentes.

## Rutas principales
| Método | Ruta | Acción |
|---|---|---|
| POST | `/admin/periodos/<id>/excel/importar` | Sube archivo, parsea, crea `excel_importados` + `excel_detalles` |
| POST | `/admin/periodos/<id>/excel/<excel_id>/vincular` | Asigna `producto_nombre_interno` manualmente |
| POST | `/admin/desc/excel/<excel_id>/datos` | Guarda las celdas modificadas en la cuadrícula |

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

## Visor y editor de datos extraídos

En **Excel oficial**, el botón **Ver datos extraídos** muestra el último archivo
válido del período seleccionado. La cuadrícula presenta todas las columnas
extraídas, permite buscar por código o producto y editar las celdas como una tabla.

El navegador envía únicamente las filas modificadas. El servidor valida que el
Excel pertenezca a la empresa y al período activos, guarda los cambios directamente
en `excel_detalles` y registra el antes/después en `excel_detalle_ediciones`.

Auditoría lee esas mismas filas en su próxima ejecución; no existe una copia
intermedia. Los resultados ya calculados no se alteran silenciosamente: después de
editar hay que volver a ejecutar Auditoría.
