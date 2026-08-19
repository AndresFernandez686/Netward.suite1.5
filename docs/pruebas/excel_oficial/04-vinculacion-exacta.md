# Excel oficial 04: vinculación exacta

## Objetivo

Verificar la vinculación por nombre exacto, ignorando mayúsculas y espacios repetidos.

## Preparación y pasos

1. Registrar el producto interno `Helado Chocolate`.
2. Importar la descripción `  HELADO   CHOCOLATE ` sin código.
3. Consultar el detalle importado.

## Resultado esperado

- `estado_vinculacion="vinculado"`.
- `producto_id` corresponde al producto interno.
- `producto_nombre_interno="Helado Chocolate"`.

## Resultado obtenido

**APROBADO.** La normalización permitió la coincidencia exacta.

Prueba: `test_vinculacion_por_nombre_exacto`.
