import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PruebasConfirmacionesUI(unittest.TestCase):
    def test_confirmacion_global_no_impone_cuenta_regresiva(self):
        codigo = ROOT.joinpath("static", "js", "main.js").read_text(encoding="utf-8")
        plantillas = "\n".join(
            archivo.read_text(encoding="utf-8")
            for archivo in ROOT.joinpath("templates").glob("*.html")
        )

        self.assertIn("openConfirmOverlay", codigo)
        self.assertIn("acceptBtn.disabled = false", codigo)
        self.assertNotIn("confirmCountdownTimer", codigo)
        self.assertNotIn("form.dataset.confirmDelay", codigo)
        self.assertNotIn("data-confirm-delay", plantillas)
        self.assertNotIn("data-submit-delay", plantillas)
        self.assertNotIn("data-countdown-label", plantillas)
        self.assertNotIn("initTimedSubmit", codigo)
        self.assertIn("initSubmitLoading", codigo)

    def test_administrador_y_empleado_cargan_el_mismo_componente_actualizado(self):
        for nombre in ("base.html", "admin_base.html"):
            plantilla = ROOT.joinpath("templates", nombre).read_text(encoding="utf-8")
            self.assertIn("confirm-no-delay-1", plantilla)


if __name__ == "__main__":
    unittest.main()
