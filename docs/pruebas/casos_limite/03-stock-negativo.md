# Stock inicial negativo

Se auditó una fila de Excel corrupta con stock inicial `-25`.

Resultado: **APROBADO**. El motor no se detuvo, conservó la trazabilidad del cálculo y marcó el resultado `Pendiente`, con advertencia de archivo posiblemente corrupto y revisión manual requerida.

Prueba: `test_stock_inicial_negativo_no_rompe_y_requiere_revision`.
