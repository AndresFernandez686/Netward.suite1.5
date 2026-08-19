# Producto sin UME

Se simuló un registro legado/corrupto de inventario cuya UME es nula.

Resultado: **APROBADO**. El motor no falló y dejó el producto `Pendiente`, con evidencia explícita de UME faltante y revisión requerida.

Prueba: `test_producto_sin_ume_no_rompe_y_requiere_revision`.
