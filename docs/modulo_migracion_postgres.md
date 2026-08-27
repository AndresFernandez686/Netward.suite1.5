# Migración y operación de base de datos

Netward utiliza una sola base de datos por empresa. Los roles administrador y
empleado comparten esa base; la separación entre empresas se realiza desplegando
una instancia y una base diferentes para cada empresa.

## Fuente oficial del esquema

Alembic es la única fuente vigente para crear o actualizar el esquema:

```powershell
$env:DATABASE_URL="postgresql+psycopg2://usuario:clave@host/base_empresa"
.venv\Scripts\python.exe -m alembic upgrade head
```

Los archivos SQL numerados de `migracion/` quedan únicamente como historial de
instalaciones anteriores. No deben aplicarse para crear una instalación nueva.

La aplicación rechaza el arranque sobre PostgreSQL si no existe
`alembic_version` o si no corresponde con la revisión esperada.

## Migración de datos SQLite a PostgreSQL

```powershell
# 1. Crear el esquema PostgreSQL.
$env:DATABASE_URL="postgresql+psycopg2://usuario:clave@host/base_empresa"
.venv\Scripts\python.exe -m alembic upgrade head

# 2. Revisar origen sin escribir.
.venv\Scripts\python.exe migracion\migrate_sqlite_to_postgres.py `
  --sqlite instance\netward_empleado.db --pg $env:DATABASE_URL --dry-run

# 3. Migrar hacia una base vacía.
.venv\Scripts\python.exe migracion\migrate_sqlite_to_postgres.py `
  --sqlite instance\netward_empleado.db --pg $env:DATABASE_URL

# 4. Exigir conteos exactos, hashes, columnas, FK y secuencias.
.venv\Scripts\python.exe migracion\verificar_migracion.py `
  --sqlite instance\netward_empleado.db --pg $env:DATABASE_URL
```

La importación se ejecuta en una sola transacción: si falla una tabla, un JSON o
una secuencia, PostgreSQL revierte toda la carga y no deja una migración parcial.

Los JSON se almacenan como `TEXT` validado en SQLite y `JSONB` en PostgreSQL.
Los PDF se almacenan como `BLOB` en SQLite y `BYTEA` en PostgreSQL.

## Respaldos y simulacros

SQLite:

```powershell
.venv\Scripts\python.exe scripts\database_maintenance.py backup-sqlite
.venv\Scripts\python.exe scripts\database_maintenance.py verify-sqlite
.venv\Scripts\python.exe scripts\database_maintenance.py audit-sqlite
```

PostgreSQL requiere `pg_dump` y `pg_restore` instalados:

```powershell
.venv\Scripts\python.exe scripts\database_maintenance.py backup-postgres `
  --url $env:DATABASE_URL
.venv\Scripts\python.exe scripts\database_maintenance.py verify-postgres `
  --url $env:DATABASE_URL
```

`verify-postgres` crea una base temporal con nombre aleatorio, restaura el dump,
compara todas las tablas por número de filas y hash y elimina la base temporal.
El usuario de mantenimiento necesita permiso `CREATEDB` para ese simulacro.

Los respaldos se guardan en `backups/database/`. Deben copiarse cifrados a un
almacenamiento externo y conservarse según la política de la empresa.
