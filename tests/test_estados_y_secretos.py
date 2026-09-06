import os
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from core.ai_assistant import AIConfig, explain, public_provider_error


ROOT = Path(__file__).resolve().parents[1]


class PruebasEstadosYSecretos(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_404_html_es_recuperable_y_no_expone_detalles(self):
        response = self.client.get("/ruta-que-no-existe")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 404)
        self.assertIn("No encontramos esta página", body)
        self.assertIn("Volver", body)
        self.assertNotIn("Traceback", body)

    def test_404_json_es_sanitizado(self):
        response = self.client.get(
            "/ruta-que-no-existe",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json["status"], 404)
        self.assertNotIn("traceback", str(response.json).lower())

    def test_headers_de_seguridad_estan_presentes(self):
        response = self.client.get("/ruta-que-no-existe")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Referrer-Policy"], "strict-origin-when-cross-origin")
        self.assertIn("camera=()", response.headers["Permissions-Policy"])

    def test_estado_publico_de_ia_no_contiene_credenciales(self):
        config = AIConfig(
            enabled=True,
            provider="openai",
            model="modelo-seguro",
            api_key="sk-secreto-que-no-debe-salir",
            base_url="https://usuario:clave@proveedor.example/v1",
            timeout=30,
            max_output_tokens=1000,
            temperature=0.2,
            custom_headers={"Authorization": "Bearer secreto"},
        )
        serialized = str(config.public_status())
        self.assertNotIn(config.api_key, serialized)
        self.assertNotIn(config.base_url, serialized)
        self.assertNotIn("Authorization", serialized)

    def test_error_no_controlado_del_proveedor_es_generico(self):
        message = public_provider_error(
            ValueError("https://usuario:clave@proveedor.example?api_key=secreto")
        )
        self.assertNotIn("secreto", message)
        self.assertNotIn("proveedor.example", message)

    def test_frontend_no_referencia_variables_de_claves(self):
        frontend = "\n".join(
            path.read_text(encoding="utf-8")
            for folder in (ROOT / "templates", ROOT / "static")
            for path in folder.rglob("*")
            if path.suffix in {".html", ".js", ".css"}
        )
        for variable in (
            "AI_API_KEY",
            "AZURE_DOCUMENT_INTELLIGENCE_KEY",
            "SECRET_KEY",
            "DATABASE_URL",
            "AI_CUSTOM_HEADERS_JSON",
        ):
            self.assertNotIn(variable, frontend)

    def test_configuracion_incompleta_muestra_mensaje_server_side_generico(self):
        with patch.dict(os.environ, {}, clear=True):
            result = explain("Analiza este período", {})
        self.assertFalse(result["ok"])
        self.assertNotIn("API_KEY", result["error"])
        self.assertIn("servidor", result["error"])

    def test_javascript_incluye_estados_y_reintento(self):
        javascript = (ROOT / "static/js/main.js").read_text(encoding="utf-8")
        self.assertIn("window.NetwardUI", javascript)
        self.assertIn("Reintentar", javascript)
        self.assertIn("enhanceEmptyStates", javascript)
        self.assertIn("aria-busy", javascript)


if __name__ == "__main__":
    unittest.main()
