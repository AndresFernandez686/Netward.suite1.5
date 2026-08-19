# Delivery 03: reemplazo de Venta Real en auditoría

## Preparación

- Venta Real del Excel: 9.
- Ventas delivery dentro del período: 4.
- Stock inicial: 10.
- Conteo final: 6.

## Resultado esperado

El motor debe reemplazar la Venta Real del Excel por delivery:

- `ventas_delivery=4`.
- `ventas=4`.
- `stock_esperado=10-4=6`.
- `diferencia=6-6=0`.

## Resultado obtenido

Todos los valores coincidieron. **APROBADO**.

La primera ejecución reveló que el motor conservaba el valor 9 del Excel. Se corrigió `core/auditoria.py` para usar delivery cuando existan movimientos y conservar Excel como alternativa cuando no existan.

Prueba: `test_auditoria_reemplaza_venta_real_con_delivery`.
