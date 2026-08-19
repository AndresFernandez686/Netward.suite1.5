# Excel oficial 05: vinculación parcial

## Objetivo

Comprobar la vinculación cuando la descripción externa contiene el nombre completo del producto más información adicional.

## Preparación y pasos

1. Registrar `Helado Chocolate`.
2. Importar `Helado Chocolate presentación 1 litro` sin código.
3. Consultar el detalle.

## Resultado esperado

- El detalle queda `vinculado`.
- Se asigna el `producto_id` de `Helado Chocolate`.

## Resultado obtenido

**APROBADO.** El producto fue resuelto por coincidencia parcial.

Prueba: `test_vinculacion_por_nombre_parcial`.
