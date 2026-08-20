# Módulo: Migración a PostgreSQL

## Archivos
| Archivo | Propósito |
|---|---|
| `migracion/01_schema_completo.sql` | DDL completo para PostgreSQL (todas las tablas, en orden de FK) |
| `migracion/02_modulo_auditoria.sql` | Solo tablas del módulo de auditoría (para instancias ya existentes) |
| `migracion/03_indices_rendimiento.sql` | Índices compuestos para producción |
| `migracion/04_rollback.sql` | DROP CASCADE en orden inverso |
| `migracion/05_multiempleado.sql` | Actualización idempotente del inventario multi-empleado |
| `migracion/06_delivery_periodos.sql` | Asociación de ventas delivery con períodos y estado fuera de rango |
| `migracion/07_asistente_ia.sql` | Trazabilidad de consultas del asistente explicativo |
| `migracion/migrate_sqlite_to_postgres.py` | Migra datos SQLite → PostgreSQL con conversión de tipos |
| `migracion/verificar_migracion.py` | Compara conteos y verifica secuencias SERIAL |

## Diferencias SQLite → PostgreSQL
| SQLite | PostgreSQL |
|---|---|
| `INTEGER PRIMARY KEY` | `SERIAL PRIMARY KEY` |
| `BOOLEAN` (0/1) | `BOOLEAN` (true/false) |
| `FLOAT` | `DOUBLE PRECISION` |
| `DATETIME` | `TIMESTAMP` |
| No FK enforcement | FK enforced — importar en orden |

## Orden de migración (respeta FK)
```
clientes → tiendas → usuarios → productos → stock_thresholds
→ producto_precios → delivery_productos → inventario_periodos
→ inventario_snapshots → inventario_items → historial → inventario_desc_snapshots
→ delivery_ventas → registros_averiados → registros_vencimiento
→ sincronizacion_log → configuracion_sistema
→ conteo_detalle → ajustes_inventario
→ excel_importados → excel_detalles → auditoria_resultados
→ asistente_ia_consultas → justificaciones → productos_relacionados
```

## Uso rápido
```bash
# 1. Crear schema
psql -U user -d netward -f migracion/01_schema_completo.sql
psql -U user -d netward -f migracion/03_indices_rendimiento.sql

# Solo para una base existente anterior al inventario multi-empleado
psql -U user -d netward -f migracion/05_multiempleado.sql
psql -U user -d netward -f migracion/06_delivery_periodos.sql
psql -U user -d netward -f migracion/07_asistente_ia.sql

# 2. Dry-run (ver cuántas filas hay)
python migracion/migrate_sqlite_to_postgres.py --pg "postgresql://..." --dry-run

# 3. Migrar datos
python migracion/migrate_sqlite_to_postgres.py --pg "postgresql://..."

# 4. Verificar
python migracion/verificar_migracion.py --pg "postgresql://..."

# 5. Activar en .env
DATABASE_URL=postgresql://user:pass@host:5432/netward
```

## Tablas con columnas booleanas que se convierten
`tiendas`, `productos`, `delivery_productos`, `inventario_items`,
`registros_averiados`, `registros_vencimiento`, `conteo_detalle`,
`auditoria_resultados`, `productos_relacionados`

## Cambio multi-empleado

No se agregó una tabla nueva. Se ampliaron:

- `inventario_items`: período, último usuario, versión y marca de sobreescritura.
- `historial`: período, snapshot, tipo de movimiento, valores anteriores y versión.
- `conteo_detalle`: primera carga, número de sincronizaciones, sobreescritura y última versión.

En instalaciones nuevas los campos forman parte de `01_schema_completo.sql`. En una base PostgreSQL existente se ejecuta `05_multiempleado.sql` antes de usar la nueva versión.

## Cambio delivery por período

`delivery_ventas` incorpora `periodo_id` y `estado_periodo`. En bases existentes se debe ejecutar `06_delivery_periodos.sql`; las ventas nuevas quedan como `en_rango`, `fuera_rango` o `sin_periodo`.

## Cambio del asistente explicativo

`asistente_ia_consultas` registra quién consultó, el período o producto, el proveedor, el modelo, el contexto y la respuesta. No almacena claves de API. En bases existentes se debe ejecutar `07_asistente_ia.sql`.
