import unittest
from pathlib import Path

from core.empleado import obtener_productos_no_cargados


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

    def test_productos_no_cargados_excluye_cargas_de_cualquier_empleado(self):
        pendientes = obtener_productos_no_cargados(
            productos={
                "Impulsivo": ["Familiar 1", "Familiar 2"],
                "Extras": ["Pizza"],
            },
            productos_cargados=[
                {
                    "categoria": "Impulsivo",
                    "producto": "Familiar 1",
                    "cantidad": 0,
                    "usuario": "otro-empleado",
                }
            ],
        )

        self.assertEqual(
            pendientes,
            [
                {"categoria": "Impulsivo", "producto": "Familiar 2"},
                {"categoria": "Extras", "producto": "Pizza"},
            ],
        )

    def test_producto_renombrado_no_reaparece_como_pendiente(self):
        pendientes = obtener_productos_no_cargados(
            productos={
                "Impulsivo": [
                    "Familiar nº 1 (chocolate/d.leche/americana)",
                    "Familiar nº 2 (chocolate/frutilla/dulce de leche)",
                    "Pizza",
                ]
            },
            productos_cargados=[
                {"categoria": "Impulsivo", "producto": "Familiar 1", "cantidad": 5},
                {"categoria": "Otra categoría", "producto": "Pizza", "cantidad": 5},
            ],
        )

        self.assertEqual(pendientes, [{
            "categoria": "Impulsivo",
            "producto": "Familiar nº 2 (chocolate/frutilla/dulce de leche)",
        }])

    def test_apartado_pendientes_permite_carga_directa_y_es_responsive(self):
        principal = (ROOT / "templates" / "empleado_inventario.html").read_text(
            encoding="utf-8"
        )
        pendientes = (ROOT / "templates" / "empleado_productos_no_cargados.html").read_text(
            encoding="utf-8"
        )
        estilos = (ROOT / "static" / "css" / "styles.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("empleado_productos_no_cargados", principal)
        self.assertIn("Ver y cargar pendientes", principal)
        self.assertNotIn("{% for pendiente in productos_no_cargados %}", principal)
        self.assertIn("{% for pendiente in productos_no_cargados %}", pendientes)
        self.assertIn('action="{{ url_for(\'carrito_agregar\') }}"', pendientes)
        self.assertIn('class="pending-product-static"', pendientes)
        self.assertNotIn("Buscar por producto", pendientes)
        self.assertIn("pendientes_por_categoria.get(cat, 0)", pendientes)
        self.assertIn("Producto de {{ active_tab }}", pendientes)
        self.assertIn(".pending-direct-form { grid-template-columns: 1fr; }", estilos)

        app = (ROOT / "app.py").read_text(encoding="utf-8")
        inicio = app.index("def empleado_productos_no_cargados():")
        fin = app.index("def empleado_periodo_seleccionar", inicio)
        ruta = app[inicio:fin]
        self.assertIn('item["categoria"] == contexto["active_tab"]', ruta)


if __name__ == "__main__":
    unittest.main()
