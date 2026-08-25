import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PruebasFlujoDesc(unittest.TestCase):
    def test_procesar_almacena_y_redirige_sin_descarga_automatica(self):
        codigo = (ROOT / "core" / "inventario.py").read_text(encoding="utf-8")
        inicio = codigo.index("def admin_desc():")
        fin = codigo.index("def desc_snapshot_eliminar", inicio)
        ruta = codigo[inicio:fin]
        plantilla = (ROOT / "templates" / "admin_desc.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("send_file(", ruta)
        self.assertNotIn("_generar_xlsx(", ruta)
        self.assertIn("#datos-extraidos-card", ruta)
        self.assertNotIn("data-submit-delay", plantilla)
        self.assertIn("Importar y validar", plantilla)
        self.assertIn("if (!fileInput.files.length)", plantilla)
        self.assertIn("fileInput.click()", plantilla)
        self.assertIn("btn-proc-label", plantilla)
        self.assertIn("Ver datos extraídos", plantilla)
        self.assertIn("Guardar modificaciones", plantilla)
        self.assertIn("function activateDocTab", plantilla)
        self.assertIn("docPanels.forEach", plantilla)
        self.assertIn("activateDocTab('datos', true)", plantilla)

    def test_facturas_tienen_tabla_compacta_y_encabezado_congelado(self):
        plantilla = (ROOT / "templates" / "admin_desc.html").read_text(
            encoding="utf-8"
        )
        estilos = (ROOT / "static" / "css" / "admin.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("desc-invoice-col-document", plantilla)
        self.assertIn("desc-invoice-row", plantilla)
        self.assertIn("Misma factura", plantilla)
        self.assertIn("Producto facturado", plantilla)
        self.assertIn(".desc-invoice-table thead th", estilos)
        self.assertIn("position: sticky", estilos)
        self.assertIn("table-layout: fixed", estilos)
        self.assertIn("desc-invoice-validation-alert", plantilla)
        self.assertIn("has-empty-fields", plantilla)
        self.assertIn("not excel_seleccionado or facturas_pendientes", plantilla)

    def test_selectores_de_producto_siguen_al_campo_y_limitan_resultados(self):
        codigo = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
        empleado = (ROOT / "templates" / "empleado_inventario.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("document.addEventListener('scroll', scheduleReposition, true)", codigo)
        self.assertIn("window.addEventListener('resize', scheduleReposition)", codigo)
        self.assertIn('data-min-chars="2" data-max-results="8"', empleado)
        self.assertIn('data-search="{{ p|lower|e }}"', empleado)

    def test_tabla_extraida_no_muestra_columnas_auxiliares_descartadas(self):
        plantilla = (ROOT / "templates" / "admin_desc.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("<th>Importe desvío</th>", plantilla)
        self.assertNotIn('data-field="importedesvio"', plantilla)
        self.assertNotIn('data-field="kilos"', plantilla)
        self.assertNotIn('data-field="unidades"', plantilla)
        self.assertNotIn('data-field="grupo"', plantilla)
        self.assertNotIn('data-field="grudescrip"', plantilla)

    def test_busqueda_interna_por_palabras_en_relaciones_y_facturas(self):
        relaciones = (ROOT / "templates" / "admin_productos_relacionados.html").read_text(
            encoding="utf-8"
        )
        facturas = (ROOT / "templates" / "admin_desc.html").read_text(encoding="utf-8")
        buscador = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
        aplicacion = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertNotIn("<datalist", relaciones)
        self.assertIn("rel-product-combo", relaciones)
        self.assertIn('data-min-chars="2" data-max-results="8"', relaciones)
        self.assertIn("p.codigo_articulo", relaciones)
        self.assertIn("function searchScore", buscador)
        self.assertIn("queryWords.every", buscador)
        self.assertIn("matches.sort", buscador)
        self.assertIn("Seleccioná ambos productos desde el catálogo interno.", aplicacion)
        self.assertIn('data-search="{{ (producto.nombre ~', facturas)

    def test_periodo_contable_usa_validacion_visual_del_sistema(self):
        plantilla = (ROOT / "templates" / "admin_desc.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="proc-form" class="desc-form"', plantilla)
        self.assertIn("data-inline-validation novalidate", plantilla)
        self.assertIn("Selecciona un período contable antes de importar.", plantilla)
        self.assertIn("Seleccionar período...", plantilla)

    def test_documentacion_oficial_no_muestra_tarjetas_de_resumen(self):
        plantilla = (ROOT / "templates" / "admin_desc.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("Inventarios procesados", plantilla)
        self.assertNotIn("Estado del servicio", plantilla)
        self.assertNotIn("desc-kpis", plantilla)

    def test_panel_de_documento_y_analisis_azure(self):
        plantilla = (ROOT / "templates" / "admin_desc.html").read_text(
            encoding="utf-8"
        )
        estilos = (ROOT / "static" / "css" / "admin.css").read_text(
            encoding="utf-8"
        )
        rutas = (ROOT / "core" / "inventario.py").read_text(encoding="utf-8")

        self.assertIn("Ver documento", plantilla)
        self.assertIn("Análisis de Nexa", plantilla)
        self.assertIn("invoice-document-inline", plantilla)
        self.assertNotIn("invoice-document-dialog", plantilla)
        self.assertIn("Ocultar documento", plantilla)
        self.assertIn("Abrir en pestaña", plantilla)
        self.assertIn("invoice-analysis-table-slot", plantilla)
        self.assertIn("invoice-review-table", plantilla)
        self.assertNotIn("Impresión con sangría", plantilla)
        self.assertIn("desc.desc_facturas_periodo_descargar", plantilla)
        self.assertIn("desc.desc_factura_analisis", plantilla)
        self.assertIn("loadStoredAnalysis", plantilla)
        self.assertIn(".desc-document-analysis", estilos)
        self.assertIn("def desc_factura_descargar", rutas)
        self.assertIn("def desc_factura_analisis", rutas)
        self.assertNotIn("Facturas cargadas por perÃ­odo", plantilla)
        self.assertIn("Ver factura", plantilla)
        self.assertIn("FacturaCompra.orden_carga.asc()", rutas)
        self.assertIn("orden_carga=siguiente_orden + posicion", rutas)
        self.assertNotIn("Leer facturas y detectar compras", plantilla)
        self.assertNotIn("Descargar PDF", plantilla)
        self.assertIn("invoiceUploadForm.requestSubmit()", plantilla)
        self.assertNotIn("facturas_historial_archivos", plantilla)
        inicio_historial = plantilla.index(
            '<section class="card card--skip-collapse" id="procesamientos-recientes"'
        )
        datos = plantilla[plantilla.index('id="datos-extraidos-card"'):inicio_historial]
        historial = plantilla[inicio_historial:]
        self.assertIn('id="datos-ver-facturas"', datos)
        self.assertIn("Ver factura", datos)
        self.assertNotIn("Ver factura", historial)
        self.assertNotIn("desc-rules-grid", plantilla)

    def test_auditoria_remite_al_unico_importador_y_datetime_es_compatible(self):
        detalle = (ROOT / "templates" / "admin_periodo_detalle.html").read_text(
            encoding="utf-8"
        )
        app = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertNotIn('name="archivo_excel"', detalle)
        self.assertIn("desc.admin_desc", detalle)
        self.assertIn('id="periodo-excel-input"', detalle)
        self.assertIn('name="return_to" value="periodo"', detalle)
        self.assertIn("excelForm.requestSubmit()", detalle)
        self.assertNotIn("Reemplazar Excel oficial</a>", detalle)
        self.assertIn("datetime.now(timezone.utc)", app)
        self.assertNotIn("datetime.utcnow().strftime", app)

    def test_alta_producto_deja_la_revinculacion_para_el_boton_manual(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        inicio = app.index("def producto_crear():")
        fin = app.index("def producto_eliminar", inicio)
        ruta = app[inicio:fin]
        plantilla = (ROOT / "templates" / "admin_sincronizar.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("revincular_detalles_pendientes", ruta)
        self.assertIn("Aplicar cambios", plantilla)
        self.assertIn("disabled", plantilla)
        self.assertIn("Volver atrás", plantilla)

    def test_notifica_cambios_pendientes_de_catalogo(self):
        desc = (ROOT / "templates" / "admin_desc.html").read_text(encoding="utf-8")
        base = (ROOT / "templates" / "admin_base.html").read_text(encoding="utf-8")
        sincronizar = (ROOT / "templates" / "admin_sincronizar.html").read_text(
            encoding="utf-8"
        )
        estilos = (ROOT / "static" / "css" / "admin.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("estado_sync.total", desc)
        self.assertIn("desc-sync-badge", desc)
        self.assertIn("refreshSyncNotice", desc)
        self.assertIn("notif_sincronizacion", base)
        self.assertIn("pendientes_sin_producto", sincronizar)
        self.assertIn("Aplicar cambios", sincronizar)
        self.assertIn(".desc-sync-alert[hidden]", estilos)
        self.assertIn("display: none !important", estilos)

        empleado_sync = (ROOT / "templates" / "empleado_sincronizar.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("catalogo_pendiente", empleado_sync)
        self.assertIn("Sincronización pendiente", empleado_sync)
        self.assertIn("enviar_recibir", empleado_sync)

    def test_enviar_y_recibir_funciona_sin_inventario_pendiente(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        inicio = app.index("def empleado_sincronizar():")
        fin = app.index("def empleado_historial", inicio)
        ruta = app[inicio:fin]

        self.assertIn("catalogo_pendiente_usuario(cliente_id, usuario)", ruta)
        self.assertIn('accion == "enviar_recibir" and catalogo_pendiente', ruta)
        self.assertIn("if pendientes == 0 and not recibe_catalogo:", ruta)


if __name__ == "__main__":
    unittest.main()
