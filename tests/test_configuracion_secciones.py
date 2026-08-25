import unittest
from pathlib import Path

from jinja2 import DictLoader, Environment, select_autoescape


ROOT = Path(__file__).resolve().parents[1]


class PruebasConfiguracionSeparada(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template = (ROOT / "templates" / "admin_configuracion.html").read_text(encoding="utf-8")
        base = """<title>{% block title %}{% endblock %}</title>
        <h1>{% block heading %}{% endblock %}</h1>
        <p>{% block subheading %}{% endblock %}</p>
        {% block content %}{% endblock %}{% block scripts %}{% endblock %}"""
        env = Environment(
            loader=DictLoader({"admin_configuracion.html": template, "admin_base.html": base}),
            autoescape=select_autoescape(["html"]),
        )
        env.globals["url_for"] = lambda endpoint, **values: f"/{endpoint}"
        cls.template = env.get_template("admin_configuracion.html")

    def render(self, section):
        return self.template.render(
            active_section=section,
            active_tab="tab-impulsivo",
            app_nombre="Netward",
            local_notice=None,
            productos_impulsivo=[],
            productos_extras=[],
            productos_kilos=[],
            tiendas=[],
        )

    def test_productos_no_renderiza_tiendas_ni_formulario_de_sucursal(self):
        html = self.render("productos")
        self.assertIn("Catalogo de productos", html)
        self.assertIn("Agregar producto", html)
        self.assertNotIn("Tiendas registradas", html)
        self.assertNotIn("Agregar nueva tienda", html)

    def test_tiendas_no_renderiza_catalogo_ni_formulario_de_producto(self):
        html = self.render("tiendas")
        self.assertIn("Tiendas registradas", html)
        self.assertIn("Agregar nueva tienda", html)
        self.assertNotIn("Catalogo de productos", html)
        self.assertNotIn("Agregar producto", html)

    def test_catalogo_unifica_alta_busqueda_precios_y_eliminacion(self):
        catalogo = (ROOT / "templates" / "admin_precios.html").read_text(
            encoding="utf-8"
        )
        menu = (ROOT / "templates" / "admin_base.html").read_text(encoding="utf-8")
        app = ROOT.joinpath("app.py").read_text(encoding="utf-8")

        self.assertIn("catalog-toolbar", catalogo)
        self.assertIn("catalog-add-toggle", catalogo)
        self.assertIn("producto_crear", catalogo)
        self.assertIn("producto_eliminar", catalogo)
        self.assertIn("precio_{{ p.id }}", catalogo)
        self.assertIn("> Catálogo", menu)
        self.assertNotIn("> Productos", menu)
        self.assertNotIn("> Precios", menu)
        self.assertIn('return redirect(url_for("admin_precios", tab=active_tab)', app)


if __name__ == "__main__":
    unittest.main()
