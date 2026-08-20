-- =============================================================================
-- Netward Suite 1.4 — Rollback completo de PostgreSQL
-- ADVERTENCIA: borra todas las tablas y datos. Usar solo en entornos de prueba
-- o cuando se quiera empezar de cero.
-- Ejecutar con: psql -U <usuario> -d <base_de_datos> -f 04_rollback.sql
-- =============================================================================

BEGIN;

-- Orden inverso respeta las FK (hijos antes que padres)
DROP TABLE IF EXISTS asistente_ia_consultas       CASCADE;
DROP TABLE IF EXISTS justificaciones              CASCADE;
DROP TABLE IF EXISTS auditoria_resultados         CASCADE;
DROP TABLE IF EXISTS excel_detalles               CASCADE;
DROP TABLE IF EXISTS excel_importados             CASCADE;
DROP TABLE IF EXISTS ajustes_inventario           CASCADE;
DROP TABLE IF EXISTS conteo_detalle               CASCADE;
DROP TABLE IF EXISTS inventario_periodos          CASCADE;
DROP TABLE IF EXISTS productos_relacionados       CASCADE;

DROP TABLE IF EXISTS sincronizacion_log           CASCADE;
DROP TABLE IF EXISTS registros_vencimiento        CASCADE;
DROP TABLE IF EXISTS registros_averiados          CASCADE;
DROP TABLE IF EXISTS inventario_desc_snapshots    CASCADE;
DROP TABLE IF EXISTS inventario_snapshots         CASCADE;
DROP TABLE IF EXISTS historial                    CASCADE;
DROP TABLE IF EXISTS inventario_items             CASCADE;
DROP TABLE IF EXISTS delivery_ventas              CASCADE;
DROP TABLE IF EXISTS delivery_productos           CASCADE;
DROP TABLE IF EXISTS producto_precios             CASCADE;
DROP TABLE IF EXISTS stock_thresholds             CASCADE;
DROP TABLE IF EXISTS productos                    CASCADE;
DROP TABLE IF EXISTS usuarios                     CASCADE;
DROP TABLE IF EXISTS tiendas                      CASCADE;
DROP TABLE IF EXISTS clientes                     CASCADE;

COMMIT;
