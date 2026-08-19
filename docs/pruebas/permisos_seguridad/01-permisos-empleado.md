# Empleado sin acceso a auditoría ni Excel

## Validaciones

- La política rechaza `empleado` cuando una operación exige `administrador`.
- Importar y vincular Excel exigen el rol `administrador`.
- Ver, ejecutar, justificar y marcar auditorías exigen `administrador`.
- El reporte gerencial y la exportación de auditoría exigen `administrador`.
- La vinculación valida empresa, período, archivo y detalle para impedir acceso cruzado mediante identificadores manipulados.

## Resultado

**APROBADO**: el empleado no puede ver ni modificar Excel o auditoría desde las rutas protegidas.

Prueba: `test_empleado_no_tiene_permiso_y_rutas_sensibles_exigen_admin`.
