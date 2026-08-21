# Reinicio de períodos contables

**Objetivo:** eliminar todos los períodos y sus datos dependientes sin borrar los datos maestros ni los movimientos operativos.

**Validaciones:**

- Se eliminan períodos, conteos, borradores, importaciones Excel, auditorías, justificaciones y consultas explicativas.
- Inventario, historial y delivery se conservan, pero quedan desvinculados del período eliminado.
- Clientes, usuarios, tiendas y productos permanecen intactos.
- Antes del borrado se crea un respaldo SQLite recuperable.
- Las URLs repetidas en `.env` se procesan una sola vez.

Automatización: `tests/test_reset_periodos_contables.py`.

## Reinicio del inventario actual

`scripts/reset_inventario_actual.py` elimina las filas operativas de `inventario_items`, pero conserva productos, usuarios, tiendas e historial. Esto evita que cantidades antiguas se incorporen accidentalmente a un período nuevo.
