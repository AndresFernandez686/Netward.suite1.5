# Excel oficial 09: Venta Real sin delivery

## Objetivo

Verificar que, cuando no existen ventas de delivery para el producto, se conserve la Venta Real del Excel.

## Datos y pasos

- Venta Real del Excel = 6.
- Mapa de delivery vacío.
- Se procesa la fila.

## Resultado esperado

- Venta Real resultante = 6.
- No se contabilizan reemplazos: `vr_sys=0`.

## Resultado obtenido

**APROBADO.** Se conservó la Venta Real oficial del archivo.

Prueba: `test_venta_real_conserva_excel_sin_delivery`.
