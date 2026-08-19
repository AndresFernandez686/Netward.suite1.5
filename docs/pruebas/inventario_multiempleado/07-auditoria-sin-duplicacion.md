# Auditoría sin duplicación

Empleado A sincroniza `7`; después Empleado B sobreescribe y sincroniza `9`.

- `conteo_detalle` conserva una sola fila para el producto.
- El conteo final usado por auditoría es `9`.
- El usuario del conteo es Empleado B.
- Con stock esperado `9`, la diferencia es `0`; no se genera sobrante falso.

Resultado: **Aprobado**.
