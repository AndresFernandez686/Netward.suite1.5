# Inventario administrativo del último período

**Objetivo:** asegurar que las tarjetas de inventario representen la actualización contable más reciente de cada sucursal.

**Validaciones:**

- Se utiliza el último período en estado `Cargado`, `Cerrado`, `Excel Importado`, `Conciliado` o `Auditado`.
- Un período todavía `Abierto` o `Pendiente` no reemplaza la última carga válida.
- Cuando se seleccionan todas las tiendas, se suma únicamente el último período cargado de cada sucursal.
- Los datos de otras empresas quedan excluidos.
- Un producto cargado explícitamente con cantidad cero cuenta como cargado.

Automatización: `tests/test_admin_inventario_periodos.py`.
