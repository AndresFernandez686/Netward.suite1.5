# Módulo: Migración a PostgreSQL

## Archivos
| Archivo | Propósito |
|---|---|
| `migracion/01_schema_completo.sql` | DDL completo para PostgreSQL (todas las tablas, en orden de FK) |
| `migracion/02_modulo_auditoria.sql` | Solo tablas del módulo de auditoría (para instancias ya existentes) |
| `migracion/03_indices_rendimiento.sql` | Índices compuestos para producción |
| `migracion/04_rollback.sql` | DROP CASCADE en orden inverso |
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
→ producto_precios → delivery_productos → inventario_items
→ historial → inventario_snapshots → inventario_desc_snapshots
→ delivery_ventas → registros_averiados → registros_vencimiento
→ sincronizacion_log → configuracion_sistema
→ inventario_periodos → conteo_detalle → ajustes_inventario
→ excel_importados → excel_detalles → auditoria_resultados
→ justificaciones → productos_relacionados
```

## Uso rápido
```bash
# 1. Crear schema
psql -U user -d netward -f migracion/01_schema_completo.sql
psql -U user -d netward -f migracion/03_indices_rendimiento.sql

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
`tiendas`, `productos`, `delivery_productos`, `registros_averiados`,
`registros_vencimiento`, `conteo_detalle`, `auditoria_resultados`, `productos_relacionados`
