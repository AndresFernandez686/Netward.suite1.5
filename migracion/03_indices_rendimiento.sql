-- =============================================================================
-- Netward Suite 1.4 — Índices de rendimiento para producción en PostgreSQL
-- Ejecutar DESPUÉS de 01_schema_completo.sql o 02_modulo_auditoria.sql.
-- Estos índices son opcionales pero recomendados para consultas frecuentes.
-- =============================================================================

BEGIN;

-- ── Inventario operativo ─────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_inv_items_tienda_sinc
    ON inventario_items(tienda_id, sinc_estado);

CREATE INDEX IF NOT EXISTS ix_inv_items_fecha
    ON inventario_items(fecha);

CREATE INDEX IF NOT EXISTS ix_inv_items_periodo_usuario
    ON inventario_items(periodo_id, usuario_ultima_carga, sinc_estado);

CREATE INDEX IF NOT EXISTS ix_historial_fecha_tienda
    ON historial(tienda_id, fecha DESC);

CREATE INDEX IF NOT EXISTS ix_historial_usuario
    ON historial(usuario);

CREATE INDEX IF NOT EXISTS ix_historial_periodo_producto
    ON historial(periodo_id, producto, version DESC);

-- ── Averiados y vencimientos ─────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_averiados_tienda_sinc
    ON registros_averiados(tienda_id, sinc_estado);

CREATE INDEX IF NOT EXISTS ix_averiados_revisado
    ON registros_averiados(revisado) WHERE revisado = FALSE;

CREATE INDEX IF NOT EXISTS ix_vencimientos_tienda_sinc
    ON registros_vencimiento(tienda_id, sinc_estado);

CREATE INDEX IF NOT EXISTS ix_vencimientos_fecha_venc
    ON registros_vencimiento(fecha_vencimiento);

CREATE INDEX IF NOT EXISTS ix_vencimientos_revisado
    ON registros_vencimiento(revisado) WHERE revisado = FALSE;

-- ── Auditoría ────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_periodos_tienda_estado
    ON inventario_periodos(tienda_id, estado);

CREATE INDEX IF NOT EXISTS ix_periodos_fecha_desde
    ON inventario_periodos(fecha_desde DESC);

CREATE INDEX IF NOT EXISTS ix_conteo_detalle_periodo
    ON conteo_detalle(periodo_id);

CREATE INDEX IF NOT EXISTS ix_conteo_detalle_fue_cargado
    ON conteo_detalle(periodo_id, fue_cargado);

CREATE INDEX IF NOT EXISTS ix_ajustes_periodo
    ON ajustes_inventario(periodo_id);

CREATE INDEX IF NOT EXISTS ix_excel_detalles_excel_id
    ON excel_detalles(excel_id);

CREATE INDEX IF NOT EXISTS ix_excel_detalles_interno
    ON excel_detalles(producto_nombre_interno)
    WHERE producto_nombre_interno IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_auditoria_periodo_faltante
    ON auditoria_resultados(periodo_id, tipo_diferencia)
    WHERE tipo_diferencia = 'faltante';

CREATE INDEX IF NOT EXISTS ix_auditoria_impacto
    ON auditoria_resultados(periodo_id, impacto DESC);

CREATE INDEX IF NOT EXISTS ix_justificaciones_resultado
    ON justificaciones(resultado_id);

CREATE INDEX IF NOT EXISTS ix_asistente_ia_periodo_creado
    ON asistente_ia_consultas(periodo_id, creado DESC);

CREATE INDEX IF NOT EXISTS ix_asistente_ia_resultado_creado
    ON asistente_ia_consultas(resultado_id, creado DESC)
    WHERE resultado_id IS NOT NULL;

-- ── Delivery ─────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_delivery_ventas_fecha_tienda
    ON delivery_ventas(tienda_id, fecha DESC);
CREATE INDEX IF NOT EXISTS ix_delivery_ventas_periodo_estado
    ON delivery_ventas(periodo_id, estado_periodo);

-- ── Sincronización ───────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS ix_sinc_log_tienda_tipo
    ON sincronizacion_log(tienda_id, tipo, timestamp DESC);

COMMIT;
