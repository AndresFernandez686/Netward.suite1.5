# Stock inicial enorme

Se auditó un producto con stock inicial y conteo de `1.000.000.000.001` unidades.

Resultado: **APROBADO**. El cálculo no se desbordó ni lanzó excepciones. El valor quedó en estado `Pendiente`, causa `Pendiente de revisión` y evidencia de stock fuera de rango.

Prueba: `test_stock_inicial_enorme_no_desborda_y_requiere_revision`.
