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
