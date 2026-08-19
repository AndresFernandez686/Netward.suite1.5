# Períodos 03: cierre con productos pendientes

## Objetivo

Confirmar que un período no pueda cerrarse mientras exista un producto con `fue_cargado=False`.

## Preparación y pasos

1. Crear un período abierto.
2. Agregar un detalle con cantidad 0 y `fue_cargado=False`.
3. Ejecutar `cerrar_periodo(periodo)` sin forzar.

## Resultado esperado

- La operación devuelve `cerrado=False`.
- Se informa el producto pendiente.
- El estado sigue siendo `Abierto`.
- `fecha_cierre` permanece vacía.

## Resultado obtenido

**APROBADO.** El cierre fue rechazado y el período no sufrió cambios.

Prueba: `test_cierre_falla_con_pendientes_y_pasa_con_todo_cargado`.
