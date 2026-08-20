-- =============================================================================
-- Netward Suite 1.4 — Schema completo para PostgreSQL
-- Ejecutar con: psql -U <usuario> -d <base_de_datos> -f 01_schema_completo.sql
--
-- Orden de creación respeta todas las FK.
-- Las columnas SERIAL se mapean desde INTEGER PRIMARY KEY de SQLAlchemy.
-- Los BOOLEAN de SQLite (0/1) se almacenan como BOOLEAN nativo en Postgres.
-- =============================================================================

-- ── Seguridad: ejecutar en transacción ──────────────────────────────────────
BEGIN;

-- ── Extensión para UUIDs si se necesita en el futuro ────────────────────────
-- CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- TABLAS BASE (multi-tenant)
-- =============================================================================

CREATE TABLE IF NOT EXISTS clientes (
    id          VARCHAR(10)  PRIMARY KEY,
    nombre      VARCHAR(160) NOT NULL UNIQUE,
    plan        VARCHAR(40)  NOT NULL DEFAULT 'basico',
    estado      VARCHAR(20)  NOT NULL DEFAULT 'activo',   -- activo | suspendido
    fecha_creacion VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS tiendas (
    id          VARCHAR(10)  PRIMARY KEY,
    cliente_id  VARCHAR(10)  NOT NULL DEFAULT 'C001' REFERENCES clientes(id),
    nombre      VARCHAR(120) NOT NULL,
    direccion   VARCHAR(255) NOT NULL DEFAULT 'Direccion no especificada',
    activa      BOOLEAN      NOT NULL DEFAULT TRUE,
    es_default  BOOLEAN      NOT NULL DEFAULT FALSE,
    fecha_creacion VARCHAR(20)
);
CREATE INDEX IF NOT EXISTS ix_tiendas_cliente_id ON tiendas(cliente_id);

CREATE TABLE IF NOT EXISTS usuarios (
    id            SERIAL       PRIMARY KEY,
    username      VARCHAR(80)  NOT NULL UNIQUE,
    password_hash VARCHAR(256),
    cliente_id    VARCHAR(10)  NOT NULL DEFAULT 'C001' REFERENCES clientes(id),
    rol           VARCHAR(20)  NOT NULL,               -- empleado | administrador
    tienda_id     VARCHAR(10)                          -- ALL para administradores
);
CREATE INDEX IF NOT EXISTS ix_usuarios_cliente_id ON usuarios(cliente_id);

CREATE TABLE IF NOT EXISTS productos (
    id               SERIAL      PRIMARY KEY,
    nombre           VARCHAR(160) NOT NULL,
    categoria        VARCHAR(40)  NOT NULL,            -- Impulsivo | Por Kilos | Extras
    visible_empleado BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_producto_categoria UNIQUE (nombre, categoria)
);

-- =============================================================================
-- INVENTARIO OPERATIVO
-- =============================================================================

CREATE TABLE IF NOT EXISTS inventario_items (
    id              SERIAL       PRIMARY KEY,
    cliente_id      VARCHAR(10)  NOT NULL DEFAULT 'C001',
    tienda_id       VARCHAR(10)  NOT NULL REFERENCES tiendas(id),
    categoria       VARCHAR(40)  NOT NULL,
    producto        VARCHAR(160) NOT NULL,
    cantidad        DOUBLE PRECISION DEFAULT 0,
    ume             VARCHAR(30)  NOT NULL DEFAULT 'Unidad',
    tipo_inventario VARCHAR(20)  NOT NULL DEFAULT 'Diario',
    fecha           VARCHAR(20),
    sinc_estado     VARCHAR(20)  NOT NULL DEFAULT 'pendiente',  -- pendiente | sincronizado
    periodo_id      INTEGER,
    usuario_ultima_carga VARCHAR(80) NOT NULL DEFAULT '',
    version         INTEGER      NOT NULL DEFAULT 1,
    fue_sobreescrito BOOLEAN     NOT NULL DEFAULT FALSE,
    actualizado     TIMESTAMP    DEFAULT NOW(),
    CONSTRAINT uq_inv_item UNIQUE (tienda_id, categoria, producto)
);
CREATE INDEX IF NOT EXISTS ix_inventario_items_cliente_id ON inventario_items(cliente_id);

CREATE TABLE IF NOT EXISTS historial (
    id              SERIAL       PRIMARY KEY,
    cliente_id      VARCHAR(10)  NOT NULL DEFAULT 'C001',
    fecha           VARCHAR(20)  NOT NULL,
    hora            VARCHAR(20)  NOT NULL DEFAULT '',
    usuario         VARCHAR(80)  NOT NULL,
    categoria       VARCHAR(40)  NOT NULL,
    producto        VARCHAR(160) NOT NULL,
    cantidad        DOUBLE PRECISION DEFAULT 0,
    modo            VARCHAR(30)  NOT NULL DEFAULT '',
    tipo_inventario VARCHAR(20)  NOT NULL DEFAULT 'Diario',
    detalle         VARCHAR(255) NOT NULL DEFAULT '',
    tienda_id       VARCHAR(10)  NOT NULL DEFAULT 'T001',
    snapshot_id     INTEGER,
    periodo_id      INTEGER,
    tipo_movimiento VARCHAR(30)  NOT NULL DEFAULT 'original',
    usuario_anterior VARCHAR(80) NOT NULL DEFAULT '',
    cantidad_anterior DOUBLE PRECISION,
    version         INTEGER      NOT NULL DEFAULT 1,
    creado          TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_historial_cliente_id ON historial(cliente_id);

CREATE TABLE IF NOT EXISTS inventario_snapshots (
    id              SERIAL      PRIMARY KEY,
    cliente_id      VARCHAR(10) NOT NULL DEFAULT 'C001',
    fecha           VARCHAR(20) NOT NULL,
    tienda_id       VARCHAR(10) NOT NULL,
    usuario         VARCHAR(80) NOT NULL,
    tipo_inventario VARCHAR(20) NOT NULL DEFAULT 'Diario',
    total_items     INTEGER     NOT NULL DEFAULT 0,
    creado          TIMESTAMP   DEFAULT NOW(),
    CONSTRAINT uq_snapshot_fecha_usuario UNIQUE (tienda_id, fecha, usuario)
);
CREATE INDEX IF NOT EXISTS ix_snapshots_cliente_id ON inventario_snapshots(cliente_id);

CREATE TABLE IF NOT EXISTS inventario_desc_snapshots (
    id              SERIAL      PRIMARY KEY,
    cliente_id      VARCHAR(10) NOT NULL DEFAULT 'C001',
    tienda_id       VARCHAR(10) NOT NULL,
    mes             VARCHAR(7)  NOT NULL,   -- YYYY-MM
    fecha_proceso   VARCHAR(20) NOT NULL,
    stock_final_json TEXT        NOT NULL,  -- JSON {nombre_lower: float}
    creado          TIMESTAMP   DEFAULT NOW(),
    CONSTRAINT uq_desc_snapshot UNIQUE (tienda_id, mes, fecha_proceso)
);
CREATE INDEX IF NOT EXISTS ix_desc_snapshots_cliente_id ON inventario_desc_snapshots(cliente_id);

-- =============================================================================
-- DELIVERY
-- =============================================================================

CREATE TABLE IF NOT EXISTS delivery_productos (
    id          SERIAL       PRIMARY KEY,
    cliente_id  VARCHAR(10)  NOT NULL DEFAULT 'C001',
    nombre      VARCHAR(160) NOT NULL UNIQUE,
    precio      DOUBLE PRECISION NOT NULL DEFAULT 0,
    es_promocion BOOLEAN     NOT NULL DEFAULT FALSE,
    activo      BOOLEAN      NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS ix_delivery_productos_cliente_id ON delivery_productos(cliente_id);

CREATE TABLE IF NOT EXISTS delivery_ventas (
    id              SERIAL       PRIMARY KEY,
    cliente_id      VARCHAR(10)  NOT NULL DEFAULT 'C001',
    fecha           VARCHAR(20)  NOT NULL,
    hora            VARCHAR(20)  NOT NULL DEFAULT '',
    producto        VARCHAR(160) NOT NULL,
    cantidad        INTEGER      NOT NULL DEFAULT 1,
    precio_unitario DOUBLE PRECISION NOT NULL DEFAULT 0,
    total           DOUBLE PRECISION NOT NULL DEFAULT 0,
    usuario         VARCHAR(80)  NOT NULL,
    tienda_id       VARCHAR(10)  NOT NULL DEFAULT 'T001',
    periodo_id      INTEGER,
    estado_periodo  VARCHAR(20)  NOT NULL DEFAULT 'sin_periodo'
);
CREATE INDEX IF NOT EXISTS ix_delivery_ventas_cliente_id ON delivery_ventas(cliente_id);
CREATE INDEX IF NOT EXISTS ix_delivery_ventas_periodo_id ON delivery_ventas(periodo_id);

-- =============================================================================
-- CONFIGURACIÓN Y UMBRALES
-- =============================================================================

CREATE TABLE IF NOT EXISTS stock_thresholds (
    id         SERIAL       PRIMARY KEY,
    cliente_id VARCHAR(10)  NOT NULL DEFAULT 'C001',
    producto   VARCHAR(160) NOT NULL UNIQUE,
    critico    DOUBLE PRECISION NOT NULL DEFAULT 0,
    medio      DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_stock_thresholds_cliente_id ON stock_thresholds(cliente_id);

CREATE TABLE IF NOT EXISTS producto_precios (
    id               SERIAL       PRIMARY KEY,
    cliente_id       VARCHAR(10)  NOT NULL DEFAULT 'C001',
    producto_nombre  VARCHAR(160) NOT NULL UNIQUE,
    categoria        VARCHAR(40)  NOT NULL,
    precio           DOUBLE PRECISION,
    precio_por_caja  DOUBLE PRECISION,
    unidades_por_caja  DOUBLE PRECISION,
    unidades_por_bulto DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS ix_producto_precios_cliente_id ON producto_precios(cliente_id);

-- =============================================================================
-- AVERIADOS Y VENCIMIENTOS
-- =============================================================================

CREATE TABLE IF NOT EXISTS registros_averiados (
    id                SERIAL       PRIMARY KEY,
    cliente_id        VARCHAR(10)  NOT NULL DEFAULT 'C001',
    tienda_id         VARCHAR(10)  NOT NULL,
    fecha             VARCHAR(20)  NOT NULL,
    hora              VARCHAR(20)  NOT NULL DEFAULT '',
    usuario           VARCHAR(80)  NOT NULL,
    categoria         VARCHAR(40)  NOT NULL,
    producto          VARCHAR(160) NOT NULL,
    cantidad          DOUBLE PRECISION NOT NULL DEFAULT 0,
    cantidad_unidades DOUBLE PRECISION NOT NULL DEFAULT 0,
    ume               VARCHAR(30)  NOT NULL DEFAULT 'Unidad',
    desc_conversion   VARCHAR(255) NOT NULL DEFAULT '',
    detalle           VARCHAR(255) NOT NULL DEFAULT '',
    sinc_estado       VARCHAR(20)  NOT NULL DEFAULT 'pendiente',
    revisado          BOOLEAN      NOT NULL DEFAULT FALSE,
    creado            TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_averiados_cliente_id ON registros_averiados(cliente_id);

CREATE TABLE IF NOT EXISTS registros_vencimiento (
    id                SERIAL       PRIMARY KEY,
    cliente_id        VARCHAR(10)  NOT NULL DEFAULT 'C001',
    tienda_id         VARCHAR(10)  NOT NULL,
    fecha             VARCHAR(20)  NOT NULL,
    hora              VARCHAR(20)  NOT NULL DEFAULT '',
    usuario           VARCHAR(80)  NOT NULL,
    categoria         VARCHAR(40)  NOT NULL,
    producto          VARCHAR(160) NOT NULL,
    cantidad          DOUBLE PRECISION NOT NULL DEFAULT 0,
    cantidad_unidades DOUBLE PRECISION NOT NULL DEFAULT 0,
    ume               VARCHAR(30)  NOT NULL DEFAULT 'Unidad',
    desc_conversion   VARCHAR(255) NOT NULL DEFAULT '',
    fecha_vencimiento VARCHAR(20)  NOT NULL,
    detalle           VARCHAR(255) NOT NULL DEFAULT '',
    sinc_estado       VARCHAR(20)  NOT NULL DEFAULT 'pendiente',
    revisado          BOOLEAN      NOT NULL DEFAULT FALSE,
    creado            TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_vencimientos_cliente_id ON registros_vencimiento(cliente_id);

CREATE TABLE IF NOT EXISTS sincronizacion_log (
    id         SERIAL      PRIMARY KEY,
    cliente_id VARCHAR(10) NOT NULL DEFAULT 'C001',
    tienda_id  VARCHAR(10) NOT NULL,
    usuario    VARCHAR(80) NOT NULL,
    tipo       VARCHAR(20) NOT NULL,   -- envio | recepcion
    accion     VARCHAR(30) NOT NULL DEFAULT '',
    timestamp  TIMESTAMP   DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_sincronizacion_log_cliente_id ON sincronizacion_log(cliente_id);

-- =============================================================================
-- MÓDULO DE AUDITORÍA (Nuevas tablas)
-- =============================================================================

CREATE TABLE IF NOT EXISTS inventario_periodos (
    id              SERIAL       PRIMARY KEY,
    cliente_id      VARCHAR(10)  NOT NULL DEFAULT 'C001',
    tienda_id       VARCHAR(10)  NOT NULL,
    numero          INTEGER      NOT NULL,
    fecha_desde     VARCHAR(20)  NOT NULL,
    fecha_hasta     VARCHAR(20)  NOT NULL,
    dias_periodo    INTEGER      NOT NULL DEFAULT 7,
    estado          VARCHAR(20)  NOT NULL DEFAULT 'Abierto',
    usuario_creador VARCHAR(80)  NOT NULL,
    fecha_creacion  TIMESTAMP    DEFAULT NOW(),
    fecha_cierre    TIMESTAMP,
    observacion     VARCHAR(500) NOT NULL DEFAULT '',
    CONSTRAINT uq_periodo_tienda_numero UNIQUE (tienda_id, numero)
);
CREATE INDEX IF NOT EXISTS ix_periodos_cliente_id ON inventario_periodos(cliente_id);

CREATE TABLE IF NOT EXISTS conteo_detalle (
    id                SERIAL       PRIMARY KEY,
    periodo_id        INTEGER      NOT NULL REFERENCES inventario_periodos(id) ON DELETE CASCADE,
    cliente_id        VARCHAR(10)  NOT NULL DEFAULT 'C001',
    tienda_id         VARCHAR(10)  NOT NULL,
    usuario           VARCHAR(80)  NOT NULL,
    producto_nombre   VARCHAR(160) NOT NULL,
    categoria         VARCHAR(40)  NOT NULL,
    cantidad_unidad   DOUBLE PRECISION NOT NULL DEFAULT 0,
    cantidad_caja     DOUBLE PRECISION NOT NULL DEFAULT 0,
    cantidad_bulto    DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_unidad_base DOUBLE PRECISION NOT NULL DEFAULT 0,
    fue_cargado       BOOLEAN      NOT NULL DEFAULT TRUE,
    observacion       VARCHAR(255) NOT NULL DEFAULT '',
    primera_carga     TIMESTAMP    DEFAULT NOW(),
    fecha_carga       TIMESTAMP    DEFAULT NOW(),
    veces_sincronizado INTEGER     NOT NULL DEFAULT 1,
    fue_sobreescrito  BOOLEAN      NOT NULL DEFAULT FALSE,
    version_ultima_carga INTEGER   NOT NULL DEFAULT 1,
    CONSTRAINT uq_conteo_periodo_producto UNIQUE (periodo_id, tienda_id, producto_nombre)
);
CREATE INDEX IF NOT EXISTS ix_conteo_detalle_cliente_id ON conteo_detalle(cliente_id);

CREATE TABLE IF NOT EXISTS ajustes_inventario (
    id                SERIAL       PRIMARY KEY,
    periodo_id        INTEGER      NOT NULL REFERENCES inventario_periodos(id) ON DELETE CASCADE,
    cliente_id        VARCHAR(10)  NOT NULL DEFAULT 'C001',
    producto_nombre   VARCHAR(160) NOT NULL,
    usuario_admin     VARCHAR(80)  NOT NULL,
    cantidad_ajustada DOUBLE PRECISION NOT NULL DEFAULT 0,
    motivo            VARCHAR(80)  NOT NULL DEFAULT 'Otro',
    observacion       VARCHAR(500) NOT NULL DEFAULT '',
    fecha_ajuste      TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_ajustes_inventario_cliente_id ON ajustes_inventario(cliente_id);

CREATE TABLE IF NOT EXISTS excel_importados (
    id                  SERIAL       PRIMARY KEY,
    periodo_id          INTEGER      NOT NULL REFERENCES inventario_periodos(id) ON DELETE CASCADE,
    cliente_id          VARCHAR(10)  NOT NULL DEFAULT 'C001',
    nombre_archivo      VARCHAR(255) NOT NULL,
    fecha_importacion   TIMESTAMP    DEFAULT NOW(),
    usuario_importador  VARCHAR(80)  NOT NULL,
    estado_validacion   VARCHAR(40)  NOT NULL DEFAULT 'ok',
    productos_nuevos    INTEGER      NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_excel_importados_cliente_id ON excel_importados(cliente_id);

CREATE TABLE IF NOT EXISTS excel_detalles (
    id                      SERIAL       PRIMARY KEY,
    excel_id                INTEGER      NOT NULL REFERENCES excel_importados(id) ON DELETE CASCADE,
    articulo                VARCHAR(40)  NOT NULL,
    artdescrip              VARCHAR(255) NOT NULL DEFAULT '',
    artcosto                DOUBLE PRECISION,
    stockinicial            DOUBLE PRECISION NOT NULL DEFAULT 0,
    compras                 DOUBLE PRECISION NOT NULL DEFAULT 0,
    otrosingresos           DOUBLE PRECISION NOT NULL DEFAULT 0,
    otrassalidas            DOUBLE PRECISION NOT NULL DEFAULT 0,
    stockfinal              DOUBLE PRECISION NOT NULL DEFAULT 0,
    ventateorica            DOUBLE PRECISION NOT NULL DEFAULT 0,
    ventareal               DOUBLE PRECISION NOT NULL DEFAULT 0,
    diferencia              DOUBLE PRECISION NOT NULL DEFAULT 0,
    importedesvio           DOUBLE PRECISION NOT NULL DEFAULT 0,
    kilos                   DOUBLE PRECISION NOT NULL DEFAULT 0,
    unidades                DOUBLE PRECISION NOT NULL DEFAULT 0,
    grupo                   VARCHAR(120) NOT NULL DEFAULT '',
    grudescrip              VARCHAR(120) NOT NULL DEFAULT '',
    producto_nombre_interno VARCHAR(160)
);
CREATE INDEX IF NOT EXISTS ix_excel_detalles_articulo ON excel_detalles(articulo);

CREATE TABLE IF NOT EXISTS auditoria_resultados (
    id                        SERIAL       PRIMARY KEY,
    periodo_id                INTEGER      NOT NULL REFERENCES inventario_periodos(id) ON DELETE CASCADE,
    cliente_id                VARCHAR(10)  NOT NULL DEFAULT 'C001',
    producto_nombre           VARCHAR(160) NOT NULL,
    categoria                 VARCHAR(40)  NOT NULL DEFAULT '',
    articulo_codigo           VARCHAR(40)  NOT NULL DEFAULT '',
    stock_inicial_anterior    DOUBLE PRECISION NOT NULL DEFAULT 0,
    stock_inicial_excel       DOUBLE PRECISION NOT NULL DEFAULT 0,
    alerta_continuidad        BOOLEAN      NOT NULL DEFAULT FALSE,
    compras                   DOUBLE PRECISION NOT NULL DEFAULT 0,
    promedio_compras_historico DOUBLE PRECISION NOT NULL DEFAULT 0,
    ventas                    DOUBLE PRECISION NOT NULL DEFAULT 0,
    otros_ingresos            DOUBLE PRECISION NOT NULL DEFAULT 0,
    otras_salidas             DOUBLE PRECISION NOT NULL DEFAULT 0,
    stock_final_excel         DOUBLE PRECISION NOT NULL DEFAULT 0,
    stock_esperado            DOUBLE PRECISION NOT NULL DEFAULT 0,
    conteo_empleado           DOUBLE PRECISION NOT NULL DEFAULT 0,
    ajuste_admin              DOUBLE PRECISION NOT NULL DEFAULT 0,
    conteo_final              DOUBLE PRECISION NOT NULL DEFAULT 0,
    diferencia                DOUBLE PRECISION NOT NULL DEFAULT 0,
    tipo_diferencia           VARCHAR(20)  NOT NULL DEFAULT 'correcto',
    costo_unitario            DOUBLE PRECISION,
    impacto                   DOUBLE PRECISION NOT NULL DEFAULT 0,
    causa_sugerida            VARCHAR(80)  NOT NULL DEFAULT 'Pendiente de revisión',
    evidencia                 TEXT         NOT NULL DEFAULT '',
    nivel_confianza           VARCHAR(20)  NOT NULL DEFAULT 'Bajo',
    severidad                 VARCHAR(20)  NOT NULL DEFAULT 'Correcto',
    estado_auditoria          VARCHAR(20)  NOT NULL DEFAULT 'Pendiente',
    usuario_conteo            VARCHAR(80)  NOT NULL DEFAULT '',
    usuario_ajuste            VARCHAR(80)  NOT NULL DEFAULT '',
    fecha_ajuste              VARCHAR(20)  NOT NULL DEFAULT '',
    creado                    TIMESTAMP    DEFAULT NOW(),
    CONSTRAINT uq_auditoria_periodo_producto UNIQUE (periodo_id, producto_nombre)
);
CREATE INDEX IF NOT EXISTS ix_auditoria_resultados_cliente_id ON auditoria_resultados(cliente_id);
CREATE INDEX IF NOT EXISTS ix_auditoria_tipo ON auditoria_resultados(tipo_diferencia);
CREATE INDEX IF NOT EXISTS ix_auditoria_severidad ON auditoria_resultados(severidad);

CREATE TABLE IF NOT EXISTS asistente_ia_consultas (
    id              SERIAL       PRIMARY KEY,
    cliente_id      VARCHAR(10)  NOT NULL DEFAULT 'C001',
    tienda_id       VARCHAR(10)  NOT NULL,
    periodo_id      INTEGER      NOT NULL REFERENCES inventario_periodos(id) ON DELETE CASCADE,
    resultado_id    INTEGER      REFERENCES auditoria_resultados(id) ON DELETE SET NULL,
    usuario         VARCHAR(80)  NOT NULL,
    tipo            VARCHAR(20)  NOT NULL DEFAULT 'periodo',
    pregunta        VARCHAR(1000) NOT NULL,
    respuesta       TEXT         NOT NULL,
    proveedor       VARCHAR(40)  NOT NULL DEFAULT 'local',
    modelo          VARCHAR(120) NOT NULL DEFAULT 'reglas-locales',
    contexto_json   TEXT         NOT NULL DEFAULT '{}',
    estado          VARCHAR(20)  NOT NULL DEFAULT 'ok',
    error           VARCHAR(500) NOT NULL DEFAULT '',
    creado          TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_asistente_ia_cliente_id ON asistente_ia_consultas(cliente_id);
CREATE INDEX IF NOT EXISTS ix_asistente_ia_tienda_id ON asistente_ia_consultas(tienda_id);
CREATE INDEX IF NOT EXISTS ix_asistente_ia_periodo_id ON asistente_ia_consultas(periodo_id);
CREATE INDEX IF NOT EXISTS ix_asistente_ia_resultado_id ON asistente_ia_consultas(resultado_id);
CREATE INDEX IF NOT EXISTS ix_asistente_ia_creado ON asistente_ia_consultas(creado);

CREATE TABLE IF NOT EXISTS justificaciones (
    id                  SERIAL       PRIMARY KEY,
    resultado_id        INTEGER      NOT NULL REFERENCES auditoria_resultados(id) ON DELETE CASCADE,
    cliente_id          VARCHAR(10)  NOT NULL DEFAULT 'C001',
    causa               VARCHAR(80)  NOT NULL,
    cantidad_justificada DOUBLE PRECISION NOT NULL DEFAULT 0,
    importe_justificado DOUBLE PRECISION NOT NULL DEFAULT 0,
    observacion         VARCHAR(500) NOT NULL,
    usuario             VARCHAR(80)  NOT NULL,
    fecha               TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_justificaciones_cliente_id ON justificaciones(cliente_id);

CREATE TABLE IF NOT EXISTS productos_relacionados (
    id                  SERIAL       PRIMARY KEY,
    cliente_id          VARCHAR(10)  NOT NULL DEFAULT 'C001',
    producto_principal  VARCHAR(160) NOT NULL,
    producto_relacionado VARCHAR(160) NOT NULL,
    ratio_esperado      DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    tolerancia          DOUBLE PRECISION NOT NULL DEFAULT 0.1,
    activo              BOOLEAN      NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS ix_productos_relacionados_cliente_id ON productos_relacionados(cliente_id);

-- Las tablas referenciadas se crean después del inventario operativo en este
-- archivo; las FK multi-empleado se agregan al final para mantener el DDL lineal.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        WHERE c.contype = 'f'
          AND c.conrelid = 'inventario_items'::regclass
          AND c.confrelid = 'inventario_periodos'::regclass
          AND a.attname = 'periodo_id'
    ) THEN
        ALTER TABLE inventario_items
            ADD CONSTRAINT fk_inv_item_periodo
            FOREIGN KEY (periodo_id) REFERENCES inventario_periodos(id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        WHERE c.contype = 'f'
          AND c.conrelid = 'historial'::regclass
          AND c.confrelid = 'inventario_snapshots'::regclass
          AND a.attname = 'snapshot_id'
    ) THEN
        ALTER TABLE historial
            ADD CONSTRAINT fk_historial_snapshot
            FOREIGN KEY (snapshot_id) REFERENCES inventario_snapshots(id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        WHERE c.contype = 'f'
          AND c.conrelid = 'historial'::regclass
          AND c.confrelid = 'inventario_periodos'::regclass
          AND a.attname = 'periodo_id'
    ) THEN
        ALTER TABLE historial
            ADD CONSTRAINT fk_historial_periodo
            FOREIGN KEY (periodo_id) REFERENCES inventario_periodos(id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        WHERE c.contype = 'f'
          AND c.conrelid = 'delivery_ventas'::regclass
          AND c.confrelid = 'inventario_periodos'::regclass
          AND a.attname = 'periodo_id'
    ) THEN
        ALTER TABLE delivery_ventas
            ADD CONSTRAINT fk_delivery_venta_periodo
            FOREIGN KEY (periodo_id) REFERENCES inventario_periodos(id) ON DELETE SET NULL;
    END IF;
END $$;

COMMIT;
