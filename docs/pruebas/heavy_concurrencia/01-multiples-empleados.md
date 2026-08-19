# Heavy 01: múltiples empleados

## Escenario

Tres empleados intentan cargar y sincronizar al mismo tiempo el mismo producto, tienda y período, partiendo de la versión `1`.

## Resultado esperado y obtenido

- Exactamente una operación prevalece y crea la versión `2`.
- Las otras dos terminan como conflictos controlados.
- No se producen errores `database locked`.
- Todos los hilos finalizan antes del límite de 20 segundos.
- `inventario_items` conserva la carga ganadora sincronizada.
- `conteo_detalle` contiene una única fila con la misma cantidad y usuario.
- El historial contiene el movimiento original y una sola sobreescritura.

Resultado: **Aprobado en 5/5 ejecuciones**. Sin pérdidas, doble conteo ni bloqueos eternos.
