# Pruebas de inventario multi-empleado

Fecha: 2026-08-19. Resultado: **10/10 pruebas aprobadas**.

La implementación conserva una única carga válida por producto y período. Cada modificación usa una versión; una versión obsoleta genera un conflicto que debe confirmarse nuevamente.

1. [Continuidad entre empleados](01-continuidad-entre-empleados.md)
2. [Producto ya cargado](02-popup-producto-cargado.md)
3. [Sobreescritura](03-sobreescritura.md)
4. [Cancelación](04-cancelacion.md)
5. [Sincronización](05-sincronizacion.md)
6. [Conflicto simultáneo](06-conflicto-simultaneo.md)
7. [Auditoría sin duplicación](07-auditoria-sin-duplicacion.md)
8. [Reporte gerencial](08-reporte-gerencial.md)
9. [Borradores compartidos](09-borradores-compartidos.md)
10. [Aislamiento por empresa y tienda](10-aislamiento-empresa-tienda.md)

Suite: `tests/test_inventario_multiempleado.py`.
