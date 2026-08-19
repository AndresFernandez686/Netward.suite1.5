# Borradores compartidos entre empleados

Empleado A agrega `Alfajor Almendrado = 7` a su carrito, pero aún no presiona **Guardar inventario**.

- Empleado B ve `7 unidades cargadas por Empleado A` con la marca `Pendiente de guardar`.
- Si B intenta cargar el mismo producto, recibe el pop-up de conflicto.
- Si cancela, el borrador de A permanece sin cambios.
- Si acepta, el producto se retira del borrador de A y pasa al carrito de B.
- Al guardar B, existe una única carga vigente.

Resultado: **Aprobado**.
