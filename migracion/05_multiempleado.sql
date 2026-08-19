-- =============================================================================
-- Netward Suite 1.4 — Inventario multi-empleado para PostgreSQL
-- Ejecutar sobre instalaciones existentes después de 02_modulo_auditoria.sql.
-- Es idempotente: puede ejecutarse nuevamente sin duplicar columnas o índices.
-- =============================================================================

BEGIN;

ALTER TABLE inventario_items
    ADD COLUMN IF NOT EXISTS periodo_id INTEGER,
    ADD COLUMN IF NOT EXISTS usuario_ultima_carga VARCHAR(80) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS fue_sobreescrito BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE historial
    ADD COLUMN IF NOT EXISTS snapshot_id INTEGER,
    ADD COLUMN IF NOT EXISTS periodo_id INTEGER,
    ADD COLUMN IF NOT EXISTS tipo_movimiento VARCHAR(30) NOT NULL DEFAULT 'original',
    ADD COLUMN IF NOT EXISTS usuario_anterior VARCHAR(80) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS cantidad_anterior DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

ALTER TABLE conteo_detalle
    ADD COLUMN IF NOT EXISTS primera_carga TIMESTAMP DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS veces_sincronizado INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS fue_sobreescrito BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS version_ultima_carga INTEGER NOT NULL DEFAULT 1;

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
END $$;

CREATE INDEX IF NOT EXISTS ix_inventario_items_periodo_id
    ON inventario_items(periodo_id);
CREATE INDEX IF NOT EXISTS ix_inv_items_periodo_usuario
    ON inventario_items(periodo_id, usuario_ultima_carga, sinc_estado);
CREATE INDEX IF NOT EXISTS ix_historial_snapshot_id
    ON historial(snapshot_id);
CREATE INDEX IF NOT EXISTS ix_historial_periodo_id
    ON historial(periodo_id);
CREATE INDEX IF NOT EXISTS ix_historial_periodo_producto
    ON historial(periodo_id, producto, version DESC);

COMMIT;
