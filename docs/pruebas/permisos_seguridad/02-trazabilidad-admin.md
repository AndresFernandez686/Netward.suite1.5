# Cambios históricos administrativos trazables

## Validaciones

- Un conteo de un período cerrado no se sobrescribe directamente.
- La corrección se guarda como `ajustes_inventario` con diferencia, motivo, observación y usuario administrador.
- La acción “Marcar revisado” crea una `justificacion` con usuario y fecha.
- Las justificaciones validan que el resultado pertenezca al período indicado.

## Resultado

**APROBADO**: los valores históricos originales permanecen intactos y cada intervención administrativa deja una evidencia consultable.

Pruebas:

- `test_admin_corrige_periodo_historico_mediante_ajuste_trazable`.
- `test_marcar_revisado_crea_trazabilidad_del_admin`.
