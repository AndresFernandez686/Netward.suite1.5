-- Conserva el orden elegido por el usuario al cargar varias facturas.
ALTER TABLE facturas_compra
    ADD COLUMN IF NOT EXISTS orden_carga INTEGER NOT NULL DEFAULT 0;
