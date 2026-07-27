# Cambio a Arquitectura Multiempresa (Multi-Tenant)

## Objetivo del cambio
Se adaptó Netward para soportar múltiples empresas (clientes), donde cada cliente puede tener una o varias heladerías (sucursales), evitando mezclar datos entre empresas.

Estructura objetivo:

- Cliente A -> 1 o varias sucursales
- Cliente B -> 1 o varias sucursales
- Cliente C -> 1 o varias sucursales

## Qué se implementó

### 1) Nuevo modelo de empresa
Se creó la entidad `Cliente` con:

- `id`
- `nombre`
- `plan`
- `estado`
- `fecha_creacion`

Archivo:
- `core/models.py`

### 2) Columna `cliente_id` en entidades principales
Se agregó `cliente_id` (con default `C001` para compatibilidad) en:

- `tiendas`
- `usuarios`
- `inventario_items`
- `historial`
- `inventario_snapshots`
- `delivery_productos`
- `delivery_ventas`
- `stock_thresholds`
- `producto_precios`
- `inventario_desc_snapshots`
- `registros_averiados`
- `registros_vencimiento`
- `sincronizacion_log`

Archivo:
- `core/models.py`

### 3) Seed inicial multiempresa
Se agregó un cliente inicial y se asociaron tiendas/usuarios por `cliente_id`:

- `CLIENTES_DEFAULT` con `C001` (Cliente Demo)
- `TIENDAS_DEFAULT` ahora incluye `cliente_id`
- `USUARIOS_DEFAULT` ahora incluye `cliente_id`

Archivo:
- `core/seed_data.py`

### 4) Migración automática de esquema (sin Alembic)
En el arranque se ejecuta una migración liviana para SQLite:

- Crea tabla `clientes` si no existe
- Agrega columna `cliente_id` si falta en tablas existentes
- Crea índices básicos (`tiendas.cliente_id`, `usuarios.cliente_id`)

Funciones agregadas:

- `_add_column_if_missing(...)`
- `ensure_multitenant_schema()`

Archivo:
- `app.py`

### 5) Sesión por cliente en login
Al iniciar sesión se guarda:

- `session["cliente_id"]`

Además:

- El selector global de tiendas del admin valida tiendas del cliente activo
- El contexto global (notificaciones/topbar) se filtra por cliente

Archivo:
- `app.py`

### 6) Aislamiento inicial en Admin (usuarios y tiendas)
Se filtró por cliente en:

- Lista de usuarios
- Creación de usuarios
- Eliminación de usuarios (bloquea si es de otro cliente)
- Configuración de tiendas
- Crear/activar/default de tiendas

Archivo:
- `app.py`

## Compatibilidad con datos existentes
Para no romper instalaciones actuales:

- Se asigna `C001` como cliente por defecto en datos existentes
- Las columnas nuevas se agregan con default compatible

Esto permite ejecutar el sistema sin migración manual inicial.

## Estado actual
El núcleo multiempresa quedó implementado y funcional en:

- Modelo de datos
- Seed
- Login/sesión
- Gestión de usuarios/tiendas en admin

## Pendiente recomendado (siguiente fase)
Para aislamiento completo por tenant, conviene filtrar por `cliente_id` en todas las consultas de módulos operativos/admin:

- Dashboard
- Inventario (admin/empleado)
- Historial
- Alertas
- Vencimientos
- Averiados
- Sincronización
- Delivery
- Exportaciones

## Riesgos y observaciones

1. Unicidad global heredada:
   - Hoy `username` sigue siendo único global en la tabla.
   - Si se desea mismo username en clientes distintos, hay que pasar a unicidad compuesta (`cliente_id`, `username`).

2. Productos/precios/umbrales:
   - Si cada cliente tendrá catálogos o precios independientes, se debe reforzar el filtrado por `cliente_id` en todos esos módulos.

3. Migración robusta a producción:
   - Para producción, se recomienda migración versionada (Alembic) para trazabilidad y rollback.

## Resumen ejecutivo
Con este cambio, Netward deja de estar orientado a una sola empresa y pasa a una base multiempresa. Ya existe separación estructural por cliente y aislamiento inicial en autenticación y administración de usuarios/tiendas. Queda como siguiente fase completar el filtrado por tenant en todos los reportes y operaciones para un aislamiento total de datos entre empresas.
