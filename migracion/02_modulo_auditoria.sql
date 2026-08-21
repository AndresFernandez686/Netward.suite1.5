-- =============================================================================
-- Netward Suite 1.4 — Módulo de Auditoría: tablas incrementales para Postgres
-- Usar cuando la BD ya tiene las tablas base y solo faltan las de auditoría.
-- Ejecutar con: psql -U <usuario> -d <base_de_datos> -f 02_modulo_auditoria.sql
-- =============================================================================

BEGIN;

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

CREATE TABLE IF NOT EXISTS excel_detalle_ediciones (
    id           SERIAL       PRIMARY KEY,
    cliente_id   VARCHAR(10)  NOT NULL DEFAULT 'C001',
    periodo_id   INTEGER      NOT NULL REFERENCES inventario_periodos(id) ON DELETE CASCADE,
    excel_id     INTEGER      NOT NULL REFERENCES excel_importados(id) ON DELETE CASCADE,
    detalle_id   INTEGER      NOT NULL REFERENCES excel_detalles(id) ON DELETE CASCADE,
    usuario      VARCHAR(80)  NOT NULL,
    cambios_json TEXT         NOT NULL DEFAULT '{}',
    creado       TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_excel_ediciones_cliente_id ON excel_detalle_ediciones(cliente_id);
CREATE INDEX IF NOT EXISTS ix_excel_ediciones_periodo_creado ON excel_detalle_ediciones(periodo_id, creado DESC);
CREATE INDEX IF NOT EXISTS ix_excel_ediciones_detalle_creado ON excel_detalle_ediciones(detalle_id, creado DESC);

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
CREATE INDEX IF NOT EXISTS ix_auditoria_tipo      ON auditoria_resultados(tipo_diferencia);
CREATE INDEX IF NOT EXISTS ix_auditoria_severidad ON auditoria_resultados(severidad);

CREATE TABLE IF NOT EXISTS justificaciones (
    id                   SERIAL       PRIMARY KEY,
    resultado_id         INTEGER      NOT NULL REFERENCES auditoria_resultados(id) ON DELETE CASCADE,
    cliente_id           VARCHAR(10)  NOT NULL DEFAULT 'C001',
    causa                VARCHAR(80)  NOT NULL,
    cantidad_justificada DOUBLE PRECISION NOT NULL DEFAULT 0,
    importe_justificado  DOUBLE PRECISION NOT NULL DEFAULT 0,
    observacion          VARCHAR(500) NOT NULL,
    usuario              VARCHAR(80)  NOT NULL,
    fecha                TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_justificaciones_cliente_id ON justificaciones(cliente_id);

CREATE TABLE IF NOT EXISTS productos_relacionados (
    id                   SERIAL       PRIMARY KEY,
    cliente_id           VARCHAR(10)  NOT NULL DEFAULT 'C001',
    producto_principal   VARCHAR(160) NOT NULL,
    producto_relacionado VARCHAR(160) NOT NULL,
    ratio_esperado       DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    tolerancia           DOUBLE PRECISION NOT NULL DEFAULT 0.1,
    activo               BOOLEAN      NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS ix_productos_relacionados_cliente_id ON productos_relacionados(cliente_id);

CREATE TABLE IF NOT EXISTS configuracion_sistema (
    id          SERIAL       PRIMARY KEY,
    cliente_id  VARCHAR(10)  NOT NULL DEFAULT 'C001',
    clave       VARCHAR(80)  NOT NULL,
    valor       VARCHAR(255) NOT NULL,
    descripcion VARCHAR(255) NOT NULL DEFAULT '',
    actualizado TIMESTAMP    DEFAULT NOW(),
    CONSTRAINT uq_config_cliente_clave UNIQUE (cliente_id, clave)
);
CREATE INDEX IF NOT EXISTS ix_config_sistema_cliente_id ON configuracion_sistema(cliente_id);

COMMIT;
