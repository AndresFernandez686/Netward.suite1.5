import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PruebasAislamientoEmpresa(unittest.TestCase):
    def test_login_y_sesion_quedan_bloqueados_a_la_instancia(self):
        codigo = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn('TENANT_ISOLATION_MODE = _env_flag("TENANT_ISOLATION_MODE")', codigo)
        self.assertIn('ISOLATED_TENANT_ID = os.getenv("ISOLATED_TENANT_ID"', codigo)
        self.assertIn('session.get("cliente_id") != app.config["ISOLATED_TENANT_ID"]', codigo)
        self.assertIn('usuario_query = usuario_query.filter_by(', codigo)
        self.assertIn('usuarios_query = usuarios_query.filter_by(', codigo)
        self.assertIn("def assert_isolated_databases():", codigo)
        self.assertIn("assert_isolated_databases()", codigo)

    def test_plantilla_no_contiene_credenciales_reales(self):
        ejemplo = (ROOT / ".env.example").read_text(encoding="utf-8")
        linea_clave = next(
            linea for linea in ejemplo.splitlines()
            if linea.startswith("AZURE_DOCUMENT_INTELLIGENCE_KEY=")
        )

        self.assertEqual(linea_clave, "AZURE_DOCUMENT_INTELLIGENCE_KEY=")
        self.assertIn("TENANT_ISOLATION_MODE=false", ejemplo)
        self.assertIn("ISOLATED_TENANT_ID=C001", ejemplo)


if __name__ == "__main__":
    unittest.main()
