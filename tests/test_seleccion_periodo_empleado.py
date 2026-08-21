import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PruebasSeleccionPeriodoEmpleado(unittest.TestCase):
    def test_selector_y_formularios_conservan_periodo_visible(self):
        plantilla = (ROOT / "templates" / "empleado_inventario.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("p.id == periodo_activo.id", plantilla)
        self.assertIn("Período seleccionado:", plantilla)
        self.assertGreaterEqual(
            plantilla.count('name="periodo_id" value="{{ periodo_activo.id }}"'),
            6,
        )

        sincronizacion = (ROOT / "templates" / "empleado_sincronizar.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("Sincronizando únicamente el período seleccionado", sincronizacion)
        self.assertIn('name="periodo_id" value="{{ periodo_activo.id }}"', sincronizacion)


if __name__ == "__main__":
    unittest.main()
