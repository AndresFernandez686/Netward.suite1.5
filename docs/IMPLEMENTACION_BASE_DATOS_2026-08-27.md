# Implementación de integridad y migración de base de datos

Fecha de implementación: 27 de agosto de 2026.

## Resultado

Se unificó el acceso de administrador y empleado en una sola base por empresa.
La configuración activa utiliza únicamente `DATABASE_URL`; las variables
`DATABASE_URL_EMPLEADO` y `DATABASE_URL_ADMIN` quedaron retiradas.

La base SQLite activa fue respaldada, reparada y migrada a la revisión Alembic
`20260827_02`. El archivo histórico `netward_admin.db` no se eliminó y queda
fuera del flujo de la aplicación.

## Cambios aplicados

### Tipos compatibles

- `PortableJSONText` conserva la interfaz de texto usada por el código.
- SQLite almacena los JSON como `TEXT` y valida el contenido al guardar.
- PostgreSQL almacena los mismos campos como `JSONB`.
- `LargeBinary` continúa produciendo `BLOB` en SQLite y `BYTEA` en PostgreSQL.
- La conversión cubre snapshots, borradores, ediciones de Excel, análisis de PDF
  y contexto del asistente.

### Integridad

- Las conexiones de la aplicación ejecutan `PRAGMA foreign_keys=ON` en SQLite.
- Alembic crea las claves foráneas e índices declarados que falten.
- Las referencias huérfanas opcionales se convierten en `NULL` antes de crear la
  restricción; una referencia obligatoria inválida detiene la migración.
- Se reparó una referencia real de `stock_thresholds` hacia un producto ausente.
- La categoría histórica `Extras` se normaliza a `Fanee`.

### Alembic

Archivos principales:

- `alembic.ini`
- `migrations/env.py`
- `migrations/versions/20260827_01_esquema_unificado.py`
- `migrations/versions/20260827_02_indice_excel_cliente.py`

En PostgreSQL la aplicación ya no crea ni altera tablas al arrancar. Exige que
primero se ejecute:

```powershell
.venv\Scripts\python.exe -m alembic upgrade head
```

SQLite mantiene la creación automática para desarrollo, pero su esquema también
puede y debe registrarse con Alembic.

### Respaldos

El script `scripts/database_maintenance.py` permite:

- respaldo consistente mediante la API de SQLite;
- reparación con restauración automática si algo falla;
- comprobación de `integrity_check` y claves foráneas;
- restauración temporal y comparación completa por hashes;
- `pg_dump` en formato custom;
- restauración PostgreSQL en una base temporal y comparación por hashes.

## Pruebas ejecutadas

Sobre una copia exacta de `instance/netward_empleado.db`:

1. `alembic upgrade head` completado.
2. Restauración desde respaldo completada.
3. Coincidencia exacta de tablas, filas y hashes.
4. Sin referencias huérfanas.
5. Sin tablas, claves foráneas ni índices declarados faltantes.

Sobre la base activa, después del respaldo:

```text
integrity: ok
foreign_key_errors: []
alembic_version: 20260827_02
missing_tables: []
missing_foreign_keys: []
missing_indexes: []
```

Pruebas automáticas:

- 32 pruebas críticas de mantenimiento, migración, PDF, Excel, permisos y flujo:
  aprobadas.
- Suite completa: 193 ejecutadas, 190 aprobadas.
- Un fallo de formato JSON detectado inicialmente fue corregido.
- Dos pruebas masivas excedieron el límite de 60 segundos en este equipo:
  79,76 s para 1.000 productos y 141,62 s para 5.000 movimientos. No presentaron
  corrupción ni resultados incorrectos; requieren una revisión de rendimiento
  independiente.

## Respaldos creados

- `backups/database/netward_empleado_20260827T155247Z.sqlite3`: estado anterior
  a reparar la referencia huérfana.
- `backups/database/netward_empleado_20260827T155307Z.sqlite3`: estado migrado,
  restaurado y verificado en la revisión inicial.
- `backups/database/netward_empleado_20260827T155939Z.sqlite3`: estado final en
  `20260827_02`, restaurado y verificado por hashes.

No se ejecutó un simulacro PostgreSQL real porque este equipo no tiene servidor,
`pg_dump` ni `pg_restore` configurados. El controlador `psycopg2` y el flujo de
simulacro quedaron instalados y listos. Para cerrar esa validación se necesita
una URL de una instancia PostgreSQL aislada y las herramientas cliente.

## Procedimiento de producción

1. Crear una base PostgreSQL vacía y exclusiva para la empresa.
2. Configurar `DATABASE_URL`.
3. Ejecutar el respaldo SQLite final.
4. Ejecutar `alembic upgrade head` sobre PostgreSQL.
5. Ejecutar el migrador en modo `--dry-run` y luego sin esa opción.
6. Ejecutar `verificar_migracion.py`.
7. Ejecutar `verify-postgres`.
8. Iniciar Netward y realizar pruebas de login, inventario, Excel, PDF, auditoría
   y descarga de facturas.
9. Mantener el SQLite original en modo solo lectura hasta aprobar la operación.
