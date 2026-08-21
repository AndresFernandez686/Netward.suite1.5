import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PruebasNotificacionInventario(unittest.TestCase):
    def test_notificacion_aparece_inmediatamente_antes_de_productos_cargados(self):
        plantilla = (ROOT / "templates" / "empleado_inventario.html").read_text(
            encoding="utf-8"
        )

        posicion_flash = plantilla.index("inventory-cart-flashes")
        posicion_carrito = plantilla.index('id="sec-carrito"')
        posicion_formularios = plantilla.index("{% for cat in categorias %}")

        self.assertGreater(posicion_flash, posicion_formularios)
        self.assertLess(posicion_flash, posicion_carrito)
        self.assertEqual(plantilla.count("get_flashed_messages"), 1)

    def test_empleado_no_ve_panel_de_cargas_compartidas(self):
        plantilla = (ROOT / "templates" / "empleado_inventario.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("Carga compartida del período", plantilla)
        self.assertNotIn("cargas_existentes", plantilla)
        self.assertIn("{% for item in productos_cargados %}", plantilla)
        self.assertIn("{% if item.es_propio %}", plantilla)


if __name__ == "__main__":
    unittest.main()
