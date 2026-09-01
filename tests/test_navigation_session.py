import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PruebasNavegacionSesion(unittest.TestCase):
    def test_resumen_admin_no_muestra_volver_atras(self):
        dashboard = (ROOT / "templates" / "admin_dashboard.html").read_text(encoding="utf-8")
        base = (ROOT / "templates" / "admin_base.html").read_text(encoding="utf-8")
        self.assertIn("{% block admin_back_button %}{% endblock %}", dashboard)
        self.assertNotIn("window.history.back()", base)

    def test_volver_atras_esta_integrado_al_titulo(self):
        admin = (ROOT / "templates" / "admin_base.html").read_text(encoding="utf-8")
        empleado = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
        estilos = (ROOT / "static" / "css" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('class="topbar__heading-row"', admin)
        self.assertIn('class="topbar__heading-row"', empleado)
        self.assertIn("topbar__back", admin)
        self.assertNotIn("admin-back-nav", admin)
        self.assertIn(".topbar__heading-row", estilos)

    def test_inicio_empleado_no_incluye_boton_atras(self):
        inicio = (ROOT / "templates" / "empleado_inventario.html").read_text(encoding="utf-8")
        self.assertNotIn("btn--back", inicio)
        self.assertNotIn("Volver atrás", inicio)

    def test_reporte_gerencial_vuelve_a_la_auditoria_del_periodo(self):
        reporte = (ROOT / "templates" / "admin_reporte_gerencial.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("Volver atrás", reporte)
        self.assertIn("url_for('admin_auditoria', periodo_id=periodo.id)", reporte)

    def test_nexa_global_usa_preguntas_contextuales_en_admin(self):
        base = (ROOT / "templates" / "admin_base.html").read_text(encoding="utf-8")
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        auditoria = (ROOT / "templates" / "admin_auditoria.html").read_text(encoding="utf-8")

        self.assertIn("nexa-floating-button", base)
        self.assertNotIn("nexa-topbar-button", base)
        self.assertIn("{% for pregunta, etiqueta in nexa_preguntas %}", base)
        self.assertIn("data-section=\"{{ nexa_seccion }}\"", base)
        self.assertIn('"documentacion": {', app_source)
        self.assertIn('"sincronizacion": {', app_source)
        self.assertIn("def admin_nexa_consultar", app_source)
        self.assertNotIn('id="auditAiDrawer"', auditoria)
        self.assertIn("data-ai-url", auditoria)

    def test_nexa_conserva_y_muestra_tres_conversaciones(self):
        base = (ROOT / "templates" / "admin_base.html").read_text(encoding="utf-8")
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        models = (ROOT / "core" / "models.py").read_text(encoding="utf-8")

        self.assertIn('id="auditAiHistory"', base)
        self.assertIn("Últimas 3 conversaciones", base)
        self.assertIn("conversation_id: currentConversationId", base)
        self.assertIn("loadConversations(true)", base)
        self.assertIn("def admin_nexa_conversaciones", app_source)
        self.assertIn(".limit(3)", app_source)
        self.assertIn("class AsistenteIAConversacion", models)

    def test_nexa_es_panel_integrado_y_empuja_el_contenido(self):
        base = (ROOT / "templates" / "admin_base.html").read_text(encoding="utf-8")
        estilos = (ROOT / "static" / "css" / "admin.css").read_text(encoding="utf-8")

        self.assertIn('class="admin-stage"', base)
        self.assertNotIn("audit-ai-overlay", base)
        self.assertIn("document.body.classList.add('nexa-is-open')", base)
        self.assertIn(".admin-stage > .content", estilos)
        self.assertIn("grid-row: 1 / span 2", estilos)
        self.assertIn("height: calc(100vh - 64px)", estilos)
        self.assertIn("flex-basis: clamp(350px, 30vw, 420px)", estilos)
        self.assertIn("grid-template-rows: auto auto minmax(0, 1fr)", estilos)
        self.assertNotIn(".audit-ai-overlay", estilos)

    def test_periodos_no_muestra_tarjeta_para_cargar_excel(self):
        periodo = (ROOT / "templates" / "admin_periodo_detalle.html").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("Documentación Oficial del período", periodo)
        self.assertNotIn('id="periodo-excel-form"', periodo)
        self.assertNotIn('id="periodo-excel-button"', periodo)

    def test_login_restablece_el_boton_al_volver_desde_historial(self):
        javascript = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("resetLoadingButtonStates", javascript)
        self.assertIn("delete button.dataset.originalLabel", javascript)
        self.assertIn("window.addEventListener('pageshow'", javascript)
        self.assertIn('response.headers["Cache-Control"]', app_source)
        self.assertIn("no-store, no-cache", app_source)


if __name__ == "__main__":
    unittest.main()
