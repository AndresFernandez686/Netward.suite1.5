import unittest

from flask import Flask

from core.auditoria import build_reporte_gerencial
from core.models import AuditoriaResultado, InventarioPeriodo, db


CLIENTE = "TEST"
TIENDA = "TTEST"


class PruebasReporteGerencial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(cls.app)
        cls.contexto = cls.app.app_context()
        cls.contexto.push()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        cls.contexto.pop()

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        self.anterior = self.crear_periodo(
            numero=1,
            desde="2026-08-01",
            hasta="2026-08-08",
        )
        self.actual = self.crear_periodo(
            numero=2,
            desde="2026-08-09",
            hasta="2026-08-16",
        )

        self.agregar_resultado(
            self.anterior,
            "Anterior crítico",
            impacto=150,
            causa="Error de conteo",
            severidad="Crítico",
        )
        self.agregar_resultado(
            self.anterior,
            "Anterior observado",
            impacto=100,
            causa="Merma o averiado",
            severidad="Observación",
        )

        self.agregar_resultado(
            self.actual,
            "Producto menor",
            impacto=100,
            causa="Error de conteo",
            severidad="Observación",
        )
        self.agregar_resultado(
            self.actual,
            "Producto mayor",
            impacto=300,
            causa="Error de conteo",
            severidad="Crítico",
        )
        self.agregar_resultado(
            self.actual,
            "Producto medio",
            impacto=200,
            causa="Merma o averiado",
            severidad="Crítico",
        )
        # No debe formar parte de pérdidas, top ni críticos del reporte.
        self.agregar_resultado(
            self.actual,
            "Sobrante excluido",
            impacto=999,
            causa="Pendiente de revisión",
            severidad="Crítico",
            tipo="sobrante",
        )
        db.session.commit()
        self.reporte = build_reporte_gerencial(self.actual)

    def tearDown(self):
        db.session.rollback()
        db.session.remove()

    def crear_periodo(self, numero, desde, hasta):
        periodo = InventarioPeriodo(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            numero=numero,
            fecha_desde=desde,
            fecha_hasta=hasta,
            dias_periodo=7,
            estado="Auditado",
            usuario_creador="tester",
        )
        db.session.add(periodo)
        db.session.flush()
        return periodo

    def agregar_resultado(
        self,
        periodo,
        producto,
        *,
        impacto,
        causa,
        severidad,
        tipo="faltante",
    ):
        resultado = AuditoriaResultado(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            producto_nombre=producto,
            tipo_diferencia=tipo,
            diferencia=-1 if tipo == "faltante" else 1,
            impacto=impacto,
            causa_sugerida=causa,
            severidad=severidad,
        )
        db.session.add(resultado)
        db.session.flush()
        return resultado

    def test_total_perdida_suma_solo_impactos_faltantes(self):
        self.assertEqual(self.reporte["total_perdida"], 600)

    def test_top_productos_ordenado_por_impacto(self):
        self.assertEqual(
            [fila.producto_nombre for fila in self.reporte["faltantes"]],
            ["Producto mayor", "Producto medio", "Producto menor"],
        )
        self.assertEqual(
            [fila.impacto for fila in self.reporte["faltantes"]],
            [300, 200, 100],
        )

    def test_agrupacion_por_causa(self):
        self.assertEqual(
            self.reporte["por_causa"]["Error de conteo"],
            {"cantidad": 2, "importe": 400},
        )
        self.assertEqual(
            self.reporte["por_causa"]["Merma o averiado"],
            {"cantidad": 1, "importe": 200},
        )
        self.assertEqual(
            self.reporte["causa_dominante"],
            {"nombre": "Error de conteo", "importe": 400, "cantidad": 2},
        )

    def test_productos_criticos(self):
        self.assertEqual(
            [fila.producto_nombre for fila in self.reporte["alertas_criticas"]],
            ["Producto mayor", "Producto medio"],
        )

    def test_delta_perdidas(self):
        comparacion = self.reporte["comparacion"]
        self.assertEqual(comparacion["perdida_anterior"], 250)
        self.assertEqual(comparacion["delta_perdida"], 350)
        self.assertEqual(comparacion["delta"], 350)

    def test_delta_criticos(self):
        comparacion = self.reporte["comparacion"]
        self.assertEqual(comparacion["criticos_anterior"], 1)
        self.assertEqual(comparacion["criticos_actual"], 2)
        self.assertEqual(comparacion["delta_criticos"], 1)

    def test_delta_faltantes(self):
        comparacion = self.reporte["comparacion"]
        self.assertEqual(comparacion["faltantes_anterior"], 2)
        self.assertEqual(comparacion["faltantes_actual"], 3)
        self.assertEqual(comparacion["delta_faltantes"], 1)


if __name__ == "__main__":
    unittest.main()
