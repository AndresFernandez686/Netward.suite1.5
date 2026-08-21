-- Sincronización versionada del catálogo por empleado.
-- Los productos publicados por el administrador solo aparecen después de
-- que cada empleado ejecuta "Enviar y Recibir".

BEGIN;

ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS catalogo_version_recibida INTEGER NOT NULL DEFAULT 0;

ALTER TABLE productos
    ADD COLUMN IF NOT EXISTS catalogo_version INTEGER NOT NULL DEFAULT 0;

UPDATE usuarios
SET catalogo_version_recibida = 0
WHERE catalogo_version_recibida IS NULL;

UPDATE productos
SET catalogo_version = 0
WHERE catalogo_version IS NULL;

CREATE INDEX IF NOT EXISTS ix_productos_catalogo_version
    ON productos(catalogo_version);

COMMIT;
