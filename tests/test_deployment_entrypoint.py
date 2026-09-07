from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CRITICAL_RUNTIME_FILES = (
    "app.py",
    "wsgi.py",
    "core/empleado.py",
    "core/models.py",
    "core/sync_bridge.py",
    "templates/admin_periodos.html",
    "templates/empleado_inventario.html",
)


class PruebasEntradaDespliegue(unittest.TestCase):
    def test_archivos_criticos_no_estan_vacios(self):
        for relative_path in CRITICAL_RUNTIME_FILES:
            with self.subTest(relative_path=relative_path):
                path = ROOT / relative_path
                self.assertTrue(path.is_file(), f"Falta el archivo crítico {relative_path}")
                self.assertGreater(
                    path.stat().st_size,
                    100,
                    f"El archivo crítico {relative_path} está vacío o truncado",
                )

    def test_wsgi_exporta_la_aplicacion_flask(self):
        source = (ROOT / "wsgi.py").read_text(encoding="utf-8")
        self.assertIn("from app import app, init_db", source)
        self.assertIn("application = app", source)

    def test_modulo_principal_define_app_e_inicializacion(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("app = Flask(__name__)", source)
        self.assertIn("def init_db()", source)


if __name__ == "__main__":
    unittest.main()
