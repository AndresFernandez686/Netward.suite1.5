# Red inestable durante guardado y sincronización

## Escenario

Se interrumpió la conexión inmediatamente antes del `commit` durante “Guardar inventario” y posteriormente durante “Sincronizar”. Ambas operaciones se reintentaron después de recuperar la conexión.

## Validaciones

- El guardado fallido no dejó `inventario_items`, historial ni snapshots parciales.
- El carrito permanece disponible para reintentar.
- El segundo guardado creó exactamente un producto y un movimiento.
- La sincronización fallida no creó `conteo_detalle` ni marcó el producto como enviado.
- El reintento sincronizó exactamente una vez, sin duplicación.
- La interfaz informa que hubo un problema de conexión, que los datos no fueron enviados y que se puede reintentar.

## Resultado

**APROBADO**: mensajes claros, rollback completo y reintento exitoso sin corrupción.

Prueba: `test_red_inestable_revierte_guardado_y_sync_y_permite_reintentar`.
