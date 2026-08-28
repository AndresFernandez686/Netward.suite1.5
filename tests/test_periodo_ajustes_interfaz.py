import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PruebasInterfazAjustesPeriodo(unittest.TestCase):
    def test_deja_un_solo_flujo_de_ajuste_administrativo(self):
        plantilla = (ROOT / "templates" / "admin_periodo_detalle.html").read_text(encoding="utf-8")
        self.assertNotIn("Registrar conteo manual", plantilla)
        self.assertNotIn("manualCategoria", plantilla)
        self.assertNotIn("manualCantidad", plantilla)
        self.assertIn("Agregar ajuste administrativo", plantilla)
        self.assertIn("ajusteCategoria", plantilla)
        codigo = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("def admin_conteo_manual", codigo)
        self.assertNotIn('conteo/manual', codigo)

    def test_muestra_pasos_rojos_para_re_ejecutar(self):
        plantilla = (ROOT / "templates" / "admin_periodo_detalle.html").read_text(encoding="utf-8")
        auditoria = (ROOT / "templates" / "admin_auditoria.html").read_text(encoding="utf-8")
        codigo = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("estado_actualizacion_auditoria.pasos", plantilla)
        self.assertIn("estado_actualizacion_auditoria.pasos", auditoria)
        self.assertIn("_marcar_auditoria_por_cambio_admin", codigo)
        self.assertNotIn("_refrescar_auditoria_por_cambio_admin", codigo)


if __name__ == "__main__":
    unittest.main()
