# Inventario masivo

## Objetivo

Validar la carga, propagación y sincronización de un catálogo grande, con distintas unidades de medida y varios períodos, sin duplicaciones, timeouts ni consumo excesivo de memoria.

## Datos ejecutados

- 1.000 productos.
- Tres UME alternadas: Unidad, Caja y Bulto.
- Factores de conversión: 1, 6 y 60 unidades base.
- Tres períodos consecutivos.
- 3.000 movimientos históricos generados.

## Validaciones

- Los 1.000 productos quedan sincronizados.
- Cada período contiene 1.000 detalles marcados como cargados.
- No existen productos duplicados dentro de un período.
- Las conversiones UME se guardan como unidades base.
- El historial conserva los movimientos de los tres períodos.
- La ejecución termina antes de 60 segundos y por debajo de 300 MiB de memoria pico.

## Resultado

**APROBADO en dos ejecuciones**:

- Ejecución aislada: 35,70 segundos y 4,7 MiB de memoria pico atribuida.
- Regresión completa: 38,72 segundos y 4,2 MiB de memoria pico atribuida.

No hubo timeout, error de memoria ni duplicación.

Prueba automatizada: `test_inventario_masivo_1000_productos_tres_umes_tres_periodos`.
