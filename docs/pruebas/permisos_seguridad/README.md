# Pruebas de permisos y seguridad

Fecha: 2026-08-19. Resultado: **4/4 pruebas aprobadas**.

El sistema utiliza los roles internos `empleado` y `administrador`. El rol `superadmin` fue excluido de estas pruebas porque no existe en la aplicación.

1. [Empleado sin acceso a auditoría ni Excel](01-permisos-empleado.md)
2. [Cambios históricos administrativos trazables](02-trazabilidad-admin.md)
3. [Datos maliciosos y caracteres especiales](03-datos-maliciosos.md)

Suite: `tests/test_permisos_seguridad.py`.
