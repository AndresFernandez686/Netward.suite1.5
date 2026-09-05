import unittest
from types import SimpleNamespace

from core.auditoria_causal import explicar_causa_diferencia


def resultado(**overrides):
    values = {
        "stock_esperado": 24,
        "conteo_final": 5,
        "diferencia": -19,
        "venta_teorica": 30,
        "ventas": 11,
        "estado_auditoria": "Pendiente",
        "causa_sugerida": "Pendiente de revisión",
        "nivel_confianza": "Bajo",
        "evidencia": "Requiere revisión manual.",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class PruebasExplicacionCausal(unittest.TestCase):
    def test_faltante_explica_por_que_no_coincide_en_lenguaje_natural(self):
        analisis = explicar_causa_diferencia(resultado())

        self.assertIn("debían quedar 24 unidades", analisis["por_que_no_coincide"])
        self.assertIn("conteo encontró 5", analisis["por_que_no_coincide"])
        self.assertIn("Faltan 19 unidades", analisis["por_que_no_coincide"])
        self.assertEqual(analisis["nivel"], "no_determinada")
        self.assertEqual(len(analisis["hipotesis"]), 3)
        self.assertIn("antes de concluir", analisis["resumen"])

    def test_sobrante_prioriza_entradas_omitidas_y_ventas_duplicadas(self):
        analisis = explicar_causa_diferencia(resultado(
            stock_esperado=4, conteo_final=9, diferencia=5,
            venta_teorica=3, ventas=8,
        ))

        self.assertIn("Hay 5 unidades más", analisis["por_que_no_coincide"])
        self.assertEqual(
            analisis["hipotesis"][0]["causa"],
            "Entrada, compra o stock inicial no registrado",
        )
        self.assertIn("Venta real duplicada", analisis["hipotesis"][1]["causa"])

    def test_causa_respaldada_se_distingue_de_una_causa_confirmada(self):
        analisis = explicar_causa_diferencia(resultado(
            causa_sugerida="Inconsistencia de continuidad",
            nivel_confianza="Alto",
            evidencia="El stock inicial no coincide con el cierre anterior.",
        ))

        self.assertEqual(analisis["nivel"], "probable")
        self.assertEqual(analisis["etiqueta"], "Causa probable respaldada")
        self.assertIn("stock inicial", analisis["resumen"])

    def test_sin_datos_no_inventa_una_causa(self):
        analisis = explicar_causa_diferencia(resultado(
            estado_auditoria="Sin datos",
            evidencia="Sin datos de Inventario oficial.",
        ))

        self.assertEqual(analisis["nivel"], "sin_datos")
        self.assertEqual(analisis["hipotesis"], [])
        self.assertIn("valores técnicos", analisis["por_que_no_coincide"])


if __name__ == "__main__":
    unittest.main()
