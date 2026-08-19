# Errores 05: producto no vinculado

Se importó un XLSX válido con código `X-404` y descripción inexistente en el catálogo.

Esperado y obtenido:

- `estado_validacion="pendiente_vinculacion"`.
- `productos_nuevos=1`.
- Detalle en estado `sin_producto` y sin `producto_id`.
- Una advertencia de vinculación manual.

**APROBADO**.

Prueba: `test_producto_no_vinculado_deja_excel_pendiente`.
