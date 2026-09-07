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

    def test_cantidad_usa_cero_como_placeholder_y_exige_valor_explicito(self):
        plantilla = (ROOT / "templates" / "empleado_inventario.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('name="cantidad" min="0" step="1" placeholder="0" required', plantilla)
        self.assertIn('name="cantidad_baldes" min="1" step="1" inputmode="numeric" placeholder="Ej. 2" required', plantilla)
        self.assertIn('name="peso_kg" min="0.001" step="0.001" inputmode="decimal"', plantilla)
        self.assertIn('data-kilo-preview role="status" aria-live="polite"', plantilla)
        self.assertNotIn('name="cantidad" min="0" step="1" value="0"', plantilla)
        self.assertIn('class="inv-form" novalidate', plantilla)
        pendientes = (ROOT / "templates" / "empleado_productos_no_cargados.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('class="pending-direct-form" novalidate', pendientes)

        app = (ROOT / "app.py").read_text(encoding="utf-8")
        inicio = app.index("def carrito_agregar():")
        fin = app.index("def carrito_eliminar", inicio)
        ruta = app[inicio:fin]
        self.assertIn('if cantidad_texto == "":', ruta)
        self.assertIn("if cantidad < 0:", ruta)


if __name__ == "__main__":
    unittest.main()
