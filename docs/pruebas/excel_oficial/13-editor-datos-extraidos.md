# Edición de datos extraídos

## Objetivo

Confirmar que el administrador puede revisar y corregir las filas persistidas del
Excel oficial y que Auditoría utiliza exactamente los valores corregidos.

## Prueba

1. Importar un Excel oficial dentro de un período.
2. Pulsar **Ver datos extraídos**.
3. Verificar que aparecen todas las filas y columnas extraídas.
4. Modificar Compras, Costo y descripción de un producto.
5. Comprobar que las celdas y la fila se marcan como modificadas.
6. Guardar las modificaciones.
7. Volver a ejecutar Auditoría.

## Resultado esperado

- Solo se envían y actualizan las filas modificadas.
- `excel_detalles` conserva los nuevos valores.
- `excel_detalle_ediciones` registra administrador, fecha y valores anterior/nuevo.
- Un administrador de otra empresa no puede leer ni modificar esas filas.
- Una edición simultánea de la misma celda devuelve conflicto y no pisa el cambio ajeno.
- Auditoría toma Compras, Costo, stocks, ingresos, salidas y Venta Real desde la
  versión editada.
- Los resultados anteriores no cambian hasta volver a ejecutar Auditoría.

Automatización: `tests/test_excel_editor.py`.
