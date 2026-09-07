import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PruebasValidacionPeriodosUI(unittest.TestCase):
    def test_crear_periodo_usa_validacion_visual_del_sistema(self):
        plantilla = (ROOT / "templates" / "admin_periodos.html").read_text(
            encoding="utf-8"
        )

        inicio = plantilla.index("class=\"periodos-form\"")
        fin = plantilla.index("</form>", inicio)
        formulario = plantilla[inicio:fin]

        self.assertIn("data-inline-validation novalidate", formulario)
        self.assertIn(
            'data-required-message="Selecciona la fecha de inicio."',
            formulario,
        )
        self.assertIn(
            'data-required-message="Selecciona la fecha de finalización."',
            formulario,
        )
        self.assertGreaterEqual(formulario.count("data-validation-field"), 3)

        javascript = (ROOT / "static" / "js" / "main.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("function showSystemNotification(message, category)", javascript)
        self.assertIn("window.NetwardNotify = showSystemNotification", javascript)
        self.assertIn("showSystemNotification(\n          validationMessage(firstInvalid)", javascript)


if __name__ == "__main__":
    unittest.main()
