# Excel oficial 07: cálculo de Venta Teórica

## Objetivo

Validar la fórmula:

`VT = SI + Compras + Otros Ingresos - SF - Otras Salidas`

## Datos y pasos

- SI = 10
- Compras = 5
- Otros Ingresos = 2
- SF = 8
- Otras Salidas = 1

Se procesa la fila mediante `_procesar_filas()`.

## Resultado esperado

`VT = 10 + 5 + 2 - 8 - 1 = 8`.

## Resultado obtenido

**APROBADO.** La Venta Teórica calculada fue 8.

Prueba: `test_calculo_venta_teorica`.
