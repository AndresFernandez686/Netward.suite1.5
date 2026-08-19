# Excel oficial 03: productos no vinculados

## Objetivo

Comprobar que una importación con productos desconocidos quede pendiente de revisión manual.

## Preparación y pasos

1. Crear un XLSX válido con código y descripción inexistentes.
2. Ejecutar `importar_excel()`.
3. Consultar la cabecera y el detalle.

## Resultado esperado

- Se conservan la cabecera y el detalle importados.
- `estado_validacion="pendiente_vinculacion"`.
- `productos_nuevos=1`.
- El detalle queda `sin_producto` y genera una advertencia.

## Resultado obtenido

**APROBADO.** La importación quedó pendiente y no se vinculó a un producto incorrecto.

Prueba: `test_producto_no_vinculado_deja_importacion_pendiente`.
