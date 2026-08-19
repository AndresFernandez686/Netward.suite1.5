# Historial extenso y períodos correlativos

## Objetivo

Comprobar que el motor de auditoría continúa correcto y estable con miles de movimientos y varios períodos relacionados entre sí.

## Datos ejecutados

- 500 productos vinculados.
- 5.000 movimientos históricos.
- Cuatro períodos correlativos.
- 500 resultados por período; 2.000 resultados de auditoría en total.
- Período 1: diferencia de -20 por producto.
- Período 2: diferencia de +20 por producto, compensada contra el anterior.
- Período 3: diferencia cero, manteniendo continuidad mediante otras salidas.
- Período 4: diferencia de -5 por producto.

## Validaciones

- Los 5.000 movimientos permanecen disponibles.
- El motor genera exactamente 2.000 resultados, sin duplicaciones.
- Los 500 productos del segundo período quedan como `compensado`, severidad `Correcto` y estado `Sin diferencia real`.
- Los 500 productos del cuarto período quedan como `faltante`.
- La auditoría termina antes de 60 segundos y por debajo de 300 MiB de memoria pico.

## Resultado

**APROBADO en dos ejecuciones**:

- Ejecución aislada: 51,95 segundos y 8,0 MiB de memoria pico atribuida.
- Regresión completa: 49,76 segundos y 7,1 MiB de memoria pico atribuida.

La correlación, la compensación y el último período conservaron resultados estables.

Prueba automatizada: `test_historial_5000_movimientos_y_500_productos_correlativos`.
