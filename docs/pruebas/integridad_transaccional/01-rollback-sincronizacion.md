# Rollback total de sincronización

## Escenario

Se prepararon dos productos pendientes y un período abierto. La sincronización propagó los conteos y cambió temporalmente los estados; inmediatamente antes del `commit` se inyectó un error de base de datos.

## Validaciones

- No quedó ningún `conteo_detalle` parcial.
- Los dos `inventario_items` continuaron en estado `pendiente`.
- Ningún ítem quedó marcado como `sincronizado`.
- No quedó un `sincronizacion_log` falso.
- El período volvió a estado `Abierto`.

## Resultado

**APROBADO**: se aplicó rollback total. La operación cumple la regla “todo o nada” y puede reintentarse sin pérdida ni doble conteo.

Prueba: `test_fallo_intermedio_de_sincronizacion_revierte_todo`.
