-- Resultado JSON y precisión del análisis opcional de facturas.
ALTER TABLE facturas_compra ADD COLUMN IF NOT EXISTS analisis_json TEXT;
ALTER TABLE facturas_compra ADD COLUMN IF NOT EXISTS analisis_motor VARCHAR(40);
ALTER TABLE facturas_compra ADD COLUMN IF NOT EXISTS analisis_precision DOUBLE PRECISION;
ALTER TABLE facturas_compra ADD COLUMN IF NOT EXISTS analisis_estado VARCHAR(30);
ALTER TABLE facturas_compra ADD COLUMN IF NOT EXISTS analisis_fecha TIMESTAMP;
