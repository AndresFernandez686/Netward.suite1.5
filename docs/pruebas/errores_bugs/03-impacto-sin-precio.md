# Errores 03: impacto de producto sin precio

Se auditó un producto con diferencia 5, sin costo en el Excel y sin precio interno.

Esperado y obtenido:

- `costo_unitario=None`.
- `impacto=0`.
- La diferencia se conserva y no causa una excepción.

**APROBADO**.

Prueba: `test_producto_sin_precio_tiene_impacto_cero`.
