import json
import os
import unittest
from io import BytesIO
from urllib import error as urlerror
from unittest.mock import patch

from flask import Flask

from core.ai_assistant import (
    AIConfig,
    PROVEEDORES,
    _call_provider,
    _http_json,
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
            categoria="Impulsivo", articulo_codigo="A-1", stock_inicial_excel=10,
            compras=20, otros_ingresos=5, ventas=8, otras_salidas=2,
            cantidad_merma=1, cantidad_vencida=1, stock_esperado=23,
            venta_teorica=28, conteo_empleado=3, conteo_final=3, diferencia=20,
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

    def test_sin_api_no_activa_el_bot_local_ni_modifica_resultado(self):
        contexto = build_product_context(self.periodo, self.resultado)
        antes = (self.resultado.diferencia, self.resultado.estado_auditoria)
        respuesta = explain("¿Por qué falta?", contexto, self.config(enabled=False, api_key=""))
        self.assertFalse(respuesta["ok"])
        self.assertFalse(respuesta["fallback"])
        self.assertEqual(respuesta["answer"], "")
        self.assertIn("Nexa no está configurada", respuesta["error"])
        self.assertEqual(antes, (self.resultado.diferencia, self.resultado.estado_auditoria))

    @patch("core.ai_assistant._http_json")
    def test_error_de_openai_no_activa_el_bot_local(self, http_json):
        from core.ai_assistant import AIProviderError
        http_json.side_effect = AIProviderError("OpenAI no disponible")
        respuesta = explain("Explica", {"alcance": "periodo"}, self.config())
        self.assertFalse(respuesta["ok"])
        self.assertFalse(respuesta["fallback"])
        self.assertEqual(respuesta["provider"], "openai")
        self.assertEqual(respuesta["answer"], "")
        self.assertEqual(respuesta["error"], "OpenAI no disponible")

    @patch("core.ai_assistant.request.urlopen")
    def test_error_http_informa_codigo_remoto_sin_exponer_respuesta(self, urlopen):
        urlopen.side_effect = urlerror.HTTPError(
            "https://api.openai.com/v1/responses",
            429,
            "Too Many Requests",
            {},
            BytesIO(json.dumps({
                "error": {
                    "message": "mensaje remoto que no debe mostrarse",
                    "type": "insufficient_quota",
                    "code": "insufficient_quota",
                }
            }).encode("utf-8")),
        )
        with self.assertRaisesRegex(Exception, r"HTTP 429 \(insufficient_quota\)"):
            _http_json("https://api.openai.com/v1/responses", {}, {}, 5)

    def test_bot_local_se_conserva_pero_requiere_activacion_explicita(self):
        contexto = build_product_context(self.periodo, self.resultado)
        config = self.config(enabled=False, api_key="", local_fallback_enabled=True)
        estado = config.public_status()
        self.assertTrue(estado["local_active"])
        self.assertEqual(estado["provider"], "local")
        self.assertEqual(estado["model"], "reglas-locales")
        self.assertEqual(estado["label"], "Nexa · bot local activo")
        respuesta = explain(
            "¿Por qué falta?",
            contexto,
            config,
        )
        self.assertTrue(respuesta["ok"])
        self.assertTrue(respuesta["fallback"])
        self.assertIn("Alfajor", respuesta["answer"])
        self.assertIn("Fórmula: stock inicial + compras", respuesta["answer"])
        self.assertIn("10 + 20 + 5 - 3 - 2 - 1 - 1 = 28", respuesta["answer"])
        self.assertIn("28 - 8 = +20", respuesta["answer"])
        self.assertIn("|+20| × 1.000 = 20.000 Gs.", respuesta["answer"])

    def test_contexto_incluye_formulas_y_fuentes_del_resultado(self):
        contexto = build_product_context(self.periodo, self.resultado)

        self.assertEqual(contexto["calculo"]["stock_inicial_aplicado"], 10)
        self.assertEqual(
            contexto["calculo"]["fuente_stock_inicial"],
            "stock inicial del Excel oficial",
        )
        self.assertEqual(
            contexto["calculo"]["fuente_ventas"],
            "venta real del Excel oficial",
        )
        self.assertEqual(
            contexto["formulas"]["diferencia"],
            "venta teórica - venta real",
        )

    def test_explicacion_usa_venta_teorica_menos_venta_real(self):
        self.resultado.stock_inicial_excel = 136
        self.resultado.compras = 48
        self.resultado.otros_ingresos = 0
        self.resultado.ventas = 256
        self.resultado.otras_salidas = 0
        self.resultado.cantidad_merma = 0
        self.resultado.cantidad_vencida = 0
        self.resultado.stock_esperado = -72
        self.resultado.conteo_empleado = 5
        self.resultado.conteo_final = 5
        self.resultado.venta_teorica = 179
        self.resultado.diferencia = -77
        self.resultado.tipo_diferencia = "sobrante"
        self.resultado.impacto = 77000
        db.session.commit()

        contexto = build_product_context(self.periodo, self.resultado)
        respuesta = explain(
            "¿Cómo se calculó la diferencia?",
            contexto,
            self.config(enabled=False, api_key="", local_fallback_enabled=True),
        )["answer"]

        self.assertIn("136 + 48 + 0 - 5 - 0 - 0 - 0 = 179", respuesta)
        self.assertIn("179 - 256 = -77", respuesta)
        self.assertIn("El signo negativo indica sobrante", respuesta)

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

    def test_configuracion_invalida_no_activa_modo_local(self):
        env = {"AI_ENABLED": "true", "AI_PROVIDER": "openai_compatible", "AI_MODEL": "x",
               "AI_API_KEY": "k", "AI_BASE_URL": "", "AI_TIMEOUT_SECONDS": "inválido"}
        with patch.dict(os.environ, env, clear=True):
            config = AIConfig.from_env()
        self.assertFalse(config.public_status()["configured"])
        self.assertFalse(config.local_fallback_enabled)
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
