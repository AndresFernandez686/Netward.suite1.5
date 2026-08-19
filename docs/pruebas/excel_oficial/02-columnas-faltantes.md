# Excel oficial 02: columnas faltantes

## Objetivo

Validar que un archivo sin columnas identificadoras de producto sea rechazado y no deje registros parciales.

## Preparación y pasos

1. Crear un XLSX que solo contenga `stockinicial` y `compras`.
2. Ejecutar `importar_excel()`.
3. Revisar las tablas de importación.

## Resultado esperado

- Se genera `ValueError` indicando que no se detectaron las columnas correctas.
- No se crea `excel_importados`.
- No se crea ningún `excel_detalles`.

## Resultado obtenido

**APROBADO.** El archivo incompleto fue rechazado sin datos residuales.

Prueba: `test_importar_excel_con_columnas_faltantes_es_rechazado`.
