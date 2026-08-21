-- Trazabilidad de cambios manuales sobre los datos extraídos del Excel oficial.
-- Migración incremental e idempotente para PostgreSQL.
BEGIN;

CREATE TABLE IF NOT EXISTS excel_detalle_ediciones (
    id           SERIAL       PRIMARY KEY,
    cliente_id   VARCHAR(10)  NOT NULL DEFAULT 'C001',
    periodo_id   INTEGER      NOT NULL,
    excel_id     INTEGER      NOT NULL,
    detalle_id   INTEGER      NOT NULL,
    usuario      VARCHAR(80)  NOT NULL,
    cambios_json TEXT         NOT NULL DEFAULT '{}',
    creado       TIMESTAMP    NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_excel_edicion_periodo') THEN
        ALTER TABLE excel_detalle_ediciones ADD CONSTRAINT fk_excel_edicion_periodo
            FOREIGN KEY (periodo_id) REFERENCES inventario_periodos(id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_excel_edicion_excel') THEN
        ALTER TABLE excel_detalle_ediciones ADD CONSTRAINT fk_excel_edicion_excel
            FOREIGN KEY (excel_id) REFERENCES excel_importados(id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_excel_edicion_detalle') THEN
        ALTER TABLE excel_detalle_ediciones ADD CONSTRAINT fk_excel_edicion_detalle
            FOREIGN KEY (detalle_id) REFERENCES excel_detalles(id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_excel_ediciones_cliente_id ON excel_detalle_ediciones(cliente_id);
CREATE INDEX IF NOT EXISTS ix_excel_ediciones_periodo_creado ON excel_detalle_ediciones(periodo_id, creado DESC);
CREATE INDEX IF NOT EXISTS ix_excel_ediciones_detalle_creado ON excel_detalle_ediciones(detalle_id, creado DESC);

COMMIT;
