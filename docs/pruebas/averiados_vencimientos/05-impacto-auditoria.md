# Averiados y vencimientos 05: impacto en auditoría

## Fórmula

`Stock esperado = stock base - mermas - vencidos`.

## Datos

- Stock base: 100.
- Averiados sincronizados: 2 cajas × 12 = 24 unidades.
- Vencidos sincronizados: 1 caja × 12 = 12 unidades.

## Resultado esperado

`100 - 24 - 12 = 64`.

## Resultado obtenido

El motor registró `cantidad_merma=24`, `cantidad_vencida=12`, `stock_esperado=64` y diferencia 0 frente al conteo. **APROBADO**.

Prueba: `test_averiados_y_vencidos_reducen_stock_esperado`.
