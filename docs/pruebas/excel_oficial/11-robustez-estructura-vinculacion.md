# Excel oficial 11: robustez de estructura y vinculación

## Objetivo

Verificar que la extracción no dependa del número de fila ni de la posición de
las columnas, y que un nombre parecido no vincule productos incorrectos.

## Casos validados

1. Columnas reordenadas: cada dato se obtiene por encabezado.
2. Producto desplazado por una fila nueva: conserva stock, compras, ingresos,
   salidas, venta real y diferencia.
3. Código numérico de XLS (`100.0`) frente al código de catálogo (`100`): se
   normaliza y vincula correctamente.
4. Nombre exacto normalizado: tolera mayúsculas, acentos, símbolos y espacios.
5. Alias oficial conocido: por ejemplo, `Almendrado x unidad` se vincula con
   `Alfajor Almendrado`.
6. Coincidencia ambigua: una descripción que contiene `chocolate` no se asocia
   automáticamente al producto genérico `Chocolate`.
7. Producto nuevo: queda `pendiente_vinculacion`, conserva todos los valores del
   Excel en auditoría y requiere revisión manual.
8. Columna obligatoria ausente: la importación falla con un mensaje explícito;
   no convierte toda la columna en cero.
9. Números localizados: admite `1.234,50`, `1,234.50` y negativos entre paréntesis.

## Columnas obligatorias

- `artdescrip`
- `stockinicial`
- `compras`
- `otrosingresos`
- `otrassalidas`
- `stockfinal`
- `ventareal`

`artcosto`, `ventateorica` y `diferencia` se extraen cuando existen, pero no se
exigen porque el costo puede estar ausente y los dos últimos valores son
recalculables.

## Excel definitivo

Sobre `templates/exceltest/andresdefinitivo.xls` se comprobaron 22 productos con
compras y una suma auditable de 4.270 unidades. Las filas nuevas o sin equivalente
inequívoco quedan pendientes en lugar de vincularse por aproximación riesgosa.

## Resultado

**APROBADO.** Las pruebas funcionales de Excel, auditoría y errores finalizaron
correctamente. La prueba pesada de historial conservó resultados correctos, pero
superó su umbral de rendimiento local: 93,50 s frente a 60 s.
