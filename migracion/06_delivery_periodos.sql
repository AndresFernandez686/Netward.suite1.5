-- Netward Suite 1.4 — Asociación de delivery con períodos (PostgreSQL)
-- Idempotente para instalaciones existentes.

BEGIN;

ALTER TABLE delivery_ventas
    ADD COLUMN IF NOT EXISTS periodo_id INTEGER,
    ADD COLUMN IF NOT EXISTS estado_periodo VARCHAR(20) NOT NULL DEFAULT 'sin_periodo';

DO $$
BEGIN
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

CREATE INDEX IF NOT EXISTS ix_delivery_ventas_periodo_id
    ON delivery_ventas(periodo_id);
CREATE INDEX IF NOT EXISTS ix_delivery_ventas_periodo_estado
    ON delivery_ventas(periodo_id, estado_periodo);

COMMIT;
