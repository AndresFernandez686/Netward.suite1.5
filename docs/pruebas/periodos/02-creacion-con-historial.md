# Períodos 02: creación con historial

## Objetivo

Validar que un período nuevo recupere la carga más reciente incluida en su rango de fechas.

## Preparación y pasos

1. Registrar dos movimientos del mismo producto, con cantidades 7 y 11.
2. Crear un período cuyo rango incluya ambos movimientos.
3. Ejecutar `retroalimentar_periodo_desde_items(periodo)`.
4. Consultar el detalle generado.

## Resultado esperado

- Se importa un producto.
- Se conserva la última cantidad: 11.
- `fue_cargado=True`.
- El período cambia a `Cargado`.

## Resultado obtenido

**APROBADO.** Se recuperó la última carga y el estado del detalle fue correcto.

Prueba: `test_crear_periodo_con_historial_importa_ultima_carga`.
