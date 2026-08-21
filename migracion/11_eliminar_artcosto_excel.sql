-- El impacto económico usa exclusivamente producto_precios.precio.
-- La columna externa artcosto deja de almacenarse en Netward.
BEGIN;

ALTER TABLE IF EXISTS excel_detalles
    DROP COLUMN IF EXISTS artcosto;

COMMIT;
