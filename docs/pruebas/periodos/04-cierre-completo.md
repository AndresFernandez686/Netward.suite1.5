# Períodos 04: cierre con todos los productos cargados

## Objetivo

Confirmar que el período se cierre cuando todos sus detalles están confirmados, incluso si una cantidad válida es cero.

## Preparación y pasos

1. Crear un período abierto con un detalle.
2. Marcar el detalle con `fue_cargado=True`.
3. Ejecutar `cerrar_periodo(periodo)`.

## Resultado esperado

- La operación devuelve `cerrado=True`.
- No existen productos pendientes.
- El estado cambia a `Cerrado`.
- Se registra `fecha_cierre`.

## Resultado obtenido

**APROBADO.** El período fue cerrado correctamente.

Prueba: `test_cierre_falla_con_pendientes_y_pasa_con_todo_cargado`.
