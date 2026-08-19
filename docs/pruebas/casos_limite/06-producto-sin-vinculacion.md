# Producto sin vinculación

Se auditó una fila del Excel sin correspondencia con el catálogo interno.

Resultado: **APROBADO**. La importación permaneció en `pendiente_vinculacion` y el resultado en `Pendiente`, sin usar esa fila para calcular una diferencia falsa.

Prueba: `test_producto_no_vinculado_permanece_pendiente`.
