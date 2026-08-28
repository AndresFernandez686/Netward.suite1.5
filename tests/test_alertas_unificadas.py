import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PruebasAlertasUnificadas(unittest.TestCase):
    def test_centro_usa_una_lista_unificada_y_destinos_accionables(self):
        plantilla = (ROOT / "templates" / "admin_alertas.html").read_text(encoding="utf-8")
        codigo = (ROOT / "app.py").read_text(encoding="utf-8")
        base = (ROOT / "templates" / "admin_base.html").read_text(encoding="utf-8")
        dashboard = (ROOT / "templates" / "admin_dashboard.html").read_text(encoding="utf-8")

        self.assertIn("alerts-list", plantilla)
        self.assertIn("alerta.destino", plantilla)
        self.assertNotIn("admin-tabpanel", plantilla)
        self.assertIn("def _construir_alertas_admin", codigo)
        self.assertIn("def admin_alerta_ir", codigo)
        self.assertIn("lectura.leida = True", codigo)
        self.assertIn("notif_total = notif_admin_unread", base)
        self.assertNotIn("catalog-sync-nav-badge", base)
        self.assertIn("dashboard-alert-center", dashboard)
        self.assertNotIn("alert-tile alert-tile--danger", dashboard)

    def test_todos_los_tipos_redirigen_a_su_apartado(self):
        codigo = (ROOT / "app.py").read_text(encoding="utf-8")
        for tipo in ("stock", "vencimiento", "averiado", "catalogo", "auditoria"):
            self.assertIn(f'tipo == "{tipo}"', codigo)
        self.assertIn('"admin_inventario"', codigo)
        self.assertIn('"admin_vencimientos"', codigo)
        self.assertIn('"admin_averiados"', codigo)
        self.assertIn('"desc.desc_sincronizar"', codigo)
        self.assertIn('"admin_auditoria"', codigo)

    def test_modelos_usados_por_alertas_estan_importados(self):
        codigo = (ROOT / "app.py").read_text(encoding="utf-8")
        cabecera = codigo[:codigo.index("BASE_DIR =")]
        self.assertIn("ExcelDetalleEdicion", cabecera)


if __name__ == "__main__":
    unittest.main()
