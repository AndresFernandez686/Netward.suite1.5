# Excel oficial 01: importación válida

## Objetivo

Comprobar la creación de la cabecera `excel_importados` y un `excel_detalles` por producto para un XLSX válido.

## Preparación y pasos

1. Crear un XLSX con todos los encabezados reconocidos y un producto existente.
2. Ejecutar `importar_excel()`.
3. Consultar la cabecera y sus detalles.

## Resultado esperado

- Se crea `excel_importados` con identificador.
- Se crea exactamente un `excel_detalles`.
- `estado_validacion="ok"`.
- `productos_nuevos=0` y sin advertencias.

## Resultado obtenido

**APROBADO.** La cabecera, el detalle y el estado fueron correctos.

También se validó el archivo definitivo `templates/exceltest/andresdefinitivo.xls`:

- 22 productos tienen compras mayores que cero.
- La suma de compras de productos auditables es 4.270.
- `Almendrado x unidad` conserva 48 unidades compradas.
- El procesamiento desde Desc. registra el mismo archivo en `excel_importados` y
  `excel_detalles`, evitando que la auditoría reemplace las compras por cero.

Pruebas: `test_importar_excel_valido_crea_cabecera_y_detalle` y
`test_excel_definitivo_conserva_compras_reales`.
