import json
import os
import unittest
from unittest.mock import patch

from flask import Flask

from core.ai_assistant import (
    AIConfig,
    PROVEEDORES,
    _call_provider,
    build_period_context,
    build_product_context,
    explain,
)
from core.models import AsistenteIAConsulta, AuditoriaResultado, InventarioPeriodo, db


class PruebasAsistenteIA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(cls.app)
        cls.ctx = cls.app.app_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        cls.ctx.pop()

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        self.periodo = InventarioPeriodo(
            cliente_id="IA1", tienda_id="TIA1", numero=2,
            fecha_desde="2026-08-10", fecha_hasta="2026-08-17",
            estado="Auditado", usuario_creador="admin",
        )
        db.session.add(self.periodo)
        db.session.flush()
        self.resultado = AuditoriaResultado(
            periodo_id=self.periodo.id, cliente_id="IA1", producto_nombre="Alfajor",
            categoria="Impulsivo", articulo_codigo="A-1", stock_esperado=23,
            conteo_empleado=3, conteo_final=3, diferencia=-20,
            tipo_diferencia="faltante", costo_unitario=1000, impacto=20000,
            causa_sugerida="Error de conteo", nivel_confianza="Medio",
            severidad="Revisar", estado_auditoria="Pendiente", evidencia="Conteo menor al esperado",
            usuario_conteo="empleado",
        )
        db.session.add(self.resultado)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()

    def config(self, provider="openai", **kwargs):
        values = dict(enabled=True, provider=provider, model="modelo-prueba", api_key="secreto",
                      base_url="https://ia.example/v1", timeout=5, max_output_tokens=300,
                      temperature=0.1, custom_headers={})
        values.update(kwargs)
        return AIConfig(**values)

    def test_modo_local_explica_sin_api_y_sin_modificar_resultado(self):
        contexto = build_product_context(self.periodo, self.resultado)
        antes = (self.resultado.diferencia, self.resultado.estado_auditoria)
        respuesta = explain("¿Por qué falta?", contexto, self.config(enabled=False, api_key=""))
        self.assertTrue(respuesta["fallback"])
        self.assertIn("Alfajor", respuesta["answer"])
        self.assertIn("-20", respuesta["answer"])
        self.assertEqual(antes, (self.resultado.diferencia, self.resultado.estado_auditoria))

    def test_contexto_de_producto_solo_busca_anterior_de_misma_empresa_y_tienda(self):
        otro_periodo = InventarioPeriodo(
            cliente_id="OTRA", tienda_id="TIA1", numero=1, fecha_desde="2026-08-01",
            fecha_hasta="2026-08-09", estado="Auditado", usuario_creador="otro",
        )
        db.session.add(otro_periodo)
        db.session.flush()
        db.session.add(AuditoriaResultado(
            periodo_id=otro_periodo.id, cliente_id="OTRA", producto_nombre="Alfajor",
            diferencia=999, tipo_diferencia="sobrante",
        ))
        db.session.commit()
        contexto = build_product_context(self.periodo, self.resultado)
        self.assertIsNone(contexto["periodo_anterior"])

    def test_resumen_periodo_usa_solo_resultados_del_periodo(self):
        contexto = build_period_context(self.periodo)
        self.assertEqual(contexto["resumen"]["productos"], 1)
        self.assertEqual(contexto["resumen"]["faltantes"], 1)
        self.assertEqual(contexto["resumen"]["impacto_faltantes"], 20000)

    @patch("core.ai_assistant._http_json")
    def test_openai_usa_responses_api_sin_almacenar(self, http_json):
        http_json.return_value = {"output": [{"content": [{"type": "output_text", "text": "Explicación segura"}]}]}
        answer = _call_provider(self.config("openai"), "Explica", {"alcance": "periodo"})
        self.assertEqual(answer, "Explicación segura")
        url, payload, headers, _timeout = http_json.call_args.args
        self.assertTrue(url.endswith("/responses"))
        self.assertFalse(payload["store"])
        self.assertEqual(headers["Authorization"], "Bearer secreto")
        self.assertNotIn("secreto", json.dumps(payload))

    @patch("core.ai_assistant._http_json")
    def test_adaptadores_soportados_extraen_texto(self, http_json):
        responses = {
            "openai_compatible": ({"choices": [{"message": {"content": "compatible"}}]}, "compatible"),
            "anthropic": ({"content": [{"type": "text", "text": "anthropic"}]}, "anthropic"),
            "gemini": ({"candidates": [{"content": {"parts": [{"text": "gemini"}]}}]}, "gemini"),
            "ollama": ({"message": {"content": "ollama"}}, "ollama"),
            "custom": ({"answer": "custom"}, "custom"),
        }
        self.assertEqual(PROVEEDORES, {"openai", *responses.keys()})
        for provider, (body, expected) in responses.items():
            with self.subTest(provider=provider):
                http_json.return_value = body
                self.assertEqual(_call_provider(self.config(provider), "Explica", {}), expected)

    def test_configuracion_invalida_cae_a_modo_local(self):
        env = {"AI_ENABLED": "true", "AI_PROVIDER": "openai_compatible", "AI_MODEL": "x",
               "AI_API_KEY": "k", "AI_BASE_URL": "", "AI_TIMEOUT_SECONDS": "inválido"}
        with patch.dict(os.environ, env, clear=True):
            config = AIConfig.from_env()
        self.assertFalse(config.public_status()["configured"])
        self.assertEqual(config.timeout, 30)

    def test_consulta_es_trazable_sin_guardar_claves(self):
        contexto = build_product_context(self.periodo, self.resultado)
        consulta = AsistenteIAConsulta(
            cliente_id="IA1", tienda_id="TIA1", periodo_id=self.periodo.id,
            resultado_id=self.resultado.id, usuario="admin", tipo="producto",
            pregunta="Explica", respuesta="Respuesta", proveedor="local",
            modelo="reglas-locales", contexto_json=json.dumps(contexto), estado="fallback",
        )
        db.session.add(consulta)
        db.session.commit()
        guardada = db.session.get(AsistenteIAConsulta, consulta.id)
        self.assertEqual(guardada.resultado_id, self.resultado.id)
        self.assertEqual(guardada.usuario, "admin")
        self.assertNotIn("api_key", guardada.contexto_json.lower())


if __name__ == "__main__":
    unittest.main()
