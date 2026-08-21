-- Documentación Oficial: facturas PDF de compras y sus líneas extraídas.
-- PostgreSQL, idempotente para instalaciones existentes.

CREATE TABLE IF NOT EXISTS facturas_compra (
    id                  SERIAL       PRIMARY KEY,
    periodo_id          INTEGER      NOT NULL REFERENCES inventario_periodos(id) ON DELETE CASCADE,
    cliente_id          VARCHAR(10)  NOT NULL DEFAULT 'C001',
    proveedor           VARCHAR(40)  NOT NULL,
    numero_factura      VARCHAR(60)  NOT NULL DEFAULT 'sin-numero',
    fecha_emision       DATE,
    nombre_archivo      VARCHAR(255) NOT NULL,
    sha256              VARCHAR(64)  NOT NULL,
    archivo_pdf         BYTEA        NOT NULL,
    metodo_extraccion   VARCHAR(30)  NOT NULL DEFAULT 'texto_pdf',
    estado              VARCHAR(30)  NOT NULL DEFAULT 'procesada',
    total_factura       DOUBLE PRECISION NOT NULL DEFAULT 0,
    usuario_importador  VARCHAR(80)  NOT NULL,
    texto_extraido      TEXT         NOT NULL DEFAULT '',
    fecha_importacion   TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_factura_cliente_sha256 UNIQUE (cliente_id, sha256)
);

CREATE INDEX IF NOT EXISTS ix_facturas_compra_periodo_id ON facturas_compra(periodo_id);
CREATE INDEX IF NOT EXISTS ix_facturas_compra_cliente_id ON facturas_compra(cliente_id);
CREATE INDEX IF NOT EXISTS ix_facturas_compra_fecha_emision ON facturas_compra(fecha_emision);
CREATE INDEX IF NOT EXISTS ix_facturas_compra_estado ON facturas_compra(estado);

CREATE TABLE IF NOT EXISTS facturas_compra_detalles (
    id                   SERIAL       PRIMARY KEY,
    factura_id           INTEGER      NOT NULL REFERENCES facturas_compra(id) ON DELETE CASCADE,
    codigo_proveedor     VARCHAR(40)  NOT NULL DEFAULT '',
    descripcion          VARCHAR(255) NOT NULL,
    cantidad_facturada   DOUBLE PRECISION NOT NULL DEFAULT 0,
    factor_conversion    DOUBLE PRECISION NOT NULL DEFAULT 1,
    compras_calculadas   DOUBLE PRECISION NOT NULL DEFAULT 0,
    precio_unitario      DOUBLE PRECISION NOT NULL DEFAULT 0,
    importe              DOUBLE PRECISION NOT NULL DEFAULT 0,
    producto_id          INTEGER REFERENCES productos(id),
    producto_nombre      VARCHAR(160),
    estado_vinculacion   VARCHAR(30)  NOT NULL DEFAULT 'pendiente',
    confianza            VARCHAR(20)  NOT NULL DEFAULT 'Baja',
    observacion          VARCHAR(255) NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_facturas_detalles_factura_id ON facturas_compra_detalles(factura_id);
CREATE INDEX IF NOT EXISTS ix_facturas_detalles_producto_id ON facturas_compra_detalles(producto_id);
CREATE INDEX IF NOT EXISTS ix_facturas_detalles_estado ON facturas_compra_detalles(estado_vinculacion);
