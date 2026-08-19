# Delivery fuera del rango del período

## Escenario

Se crearon dos períodos consecutivos. Una venta del 12/08 pertenecía al segundo período y otra del 20/08 no pertenecía a ninguno.

## Validaciones

- La venta del 12/08 quedó con `periodo_id` del segundo período y estado `en_rango`.
- La venta del 20/08 quedó sin `periodo_id` y estado `fuera_rango`.
- El primer período recibió cero ventas delivery.
- El segundo período recibió únicamente las cuatro unidades de su rango.
- La venta fuera de rango no se incorporó a ninguna auditoría.
- La pantalla de delivery muestra una etiqueta “Fuera de rango”.

## Resultado

**APROBADO**: no se mezclaron períodos y la venta fuera de tiempo quedó identificada explícitamente.

Prueba: `test_delivery_se_asigna_por_fecha_y_fuera_rango_no_se_mezcla`.
