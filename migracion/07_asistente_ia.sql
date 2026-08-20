-- =============================================================================
-- Netward Suite 1.4 — trazabilidad del asistente explicativo de auditoría
-- Migración incremental e idempotente para PostgreSQL.
-- =============================================================================
BEGIN;

CREATE TABLE IF NOT EXISTS asistente_ia_consultas (
    id              SERIAL        PRIMARY KEY,
    cliente_id      VARCHAR(10)   NOT NULL DEFAULT 'C001',
    tienda_id       VARCHAR(10)   NOT NULL,
    periodo_id      INTEGER       NOT NULL,
    resultado_id    INTEGER,
    usuario         VARCHAR(80)   NOT NULL,
    tipo            VARCHAR(20)   NOT NULL DEFAULT 'periodo',
    pregunta        VARCHAR(1000) NOT NULL,
    respuesta       TEXT          NOT NULL,
    proveedor       VARCHAR(40)   NOT NULL DEFAULT 'local',
    modelo          VARCHAR(120)  NOT NULL DEFAULT 'reglas-locales',
    contexto_json   TEXT          NOT NULL DEFAULT '{}',
    estado          VARCHAR(20)   NOT NULL DEFAULT 'ok',
    error           VARCHAR(500)  NOT NULL DEFAULT '',
    creado          TIMESTAMP     NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_asistente_ia_periodo') THEN
        ALTER TABLE asistente_ia_consultas
            ADD CONSTRAINT fk_asistente_ia_periodo FOREIGN KEY (periodo_id)
            REFERENCES inventario_periodos(id) ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_asistente_ia_resultado') THEN
        ALTER TABLE asistente_ia_consultas
            ADD CONSTRAINT fk_asistente_ia_resultado FOREIGN KEY (resultado_id)
            REFERENCES auditoria_resultados(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_asistente_ia_cliente_id ON asistente_ia_consultas(cliente_id);
CREATE INDEX IF NOT EXISTS ix_asistente_ia_tienda_id ON asistente_ia_consultas(tienda_id);
CREATE INDEX IF NOT EXISTS ix_asistente_ia_periodo_creado ON asistente_ia_consultas(periodo_id, creado DESC);
CREATE INDEX IF NOT EXISTS ix_asistente_ia_resultado_creado
    ON asistente_ia_consultas(resultado_id, creado DESC) WHERE resultado_id IS NOT NULL;

COMMIT;
