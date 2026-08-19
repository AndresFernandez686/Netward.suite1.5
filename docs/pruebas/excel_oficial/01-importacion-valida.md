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

Prueba: `test_importar_excel_valido_crea_cabecera_y_detalle`.
