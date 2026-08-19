# Excel oficial 06: producto sin coincidencia

## Objetivo

Evitar que una descripción sin coincidencia se vincule automáticamente a un producto incorrecto.

## Preparación y pasos

1. Mantener únicamente `Helado Chocolate` en el catálogo de prueba.
2. Importar `Salsa de frutilla especial` sin código.
3. Revisar el detalle y la cabecera.

## Resultado esperado

- `producto_nombre_interno` y `producto_id` quedan vacíos.
- El detalle queda `sin_producto`.
- La cabecera queda `pendiente_vinculacion`.

## Resultado obtenido

**APROBADO.** No se produjo una vinculación falsa.

Prueba: `test_vinculacion_sin_coincidencia_queda_pendiente`.
