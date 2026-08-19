import unittest

from flask import Flask

from core.auditoria import ejecutar_auditoria
from core.models import (
    ConteoDetalle,
    ExcelDetalle,
    ExcelImportado,
    InventarioPeriodo,
    Producto,
    db,
)


CLIENTE = "TEST"
TIENDA = "TTEST"
PRODUCTO = "Alfajor Almendrado"


class PruebaAuditoriaCorrelativa(unittest.TestCase):
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
        self.producto = Producto(
            nombre=PRODUCTO,
            categoria="Impulsivo",
            visible_empleado=True,
        )
        db.session.add(self.producto)
        db.session.commit()

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
            estado="Cerrado",
            usuario_creador="tester",
        )
        db.session.add(periodo)
        db.session.flush()
        return periodo

    def agregar_datos(
        self,
        periodo,
        *,
        stock_inicial,
        compras,
        conteo,
        otras_salidas=0,
    ):
        db.session.add(ConteoDetalle(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario="empleado",
            producto_nombre=PRODUCTO,
            categoria="Impulsivo",
            cantidad_unidad=conteo,
            cantidad_caja=0,
            cantidad_bulto=0,
            total_unidad_base=conteo,
            fue_cargado=True,
        ))
        excel = ExcelImportado(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            nombre_archivo=f"periodo-{periodo.numero}.xlsx",
            usuario_importador="tester",
            estado_validacion="ok",
        )
        db.session.add(excel)
        db.session.flush()
        db.session.add(ExcelDetalle(
            excel_id=excel.id,
            articulo="ALF-001",
            artdescrip=PRODUCTO,
            artcosto=500,
            stockinicial=stock_inicial,
            compras=compras,
            otrassalidas=otras_salidas,
            ventareal=0,
            stockfinal=conteo,
            producto_nombre_interno=PRODUCTO,
            producto_id=self.producto.id,
            estado_vinculacion="vinculado",
            excluido_auditoria=False,
        ))
        db.session.flush()

    def test_faltante_anterior_y_sobrante_actual_quedan_compensados(self):
        anterior = self.crear_periodo(
            2,
            "2026-08-01",
            "2026-08-08",
        )
        self.agregar_datos(
            anterior,
            stock_inicial=23,
            compras=0,
            conteo=3,
        )
        resultado_anterior = ejecutar_auditoria(anterior)[0]
        self.assertEqual(resultado_anterior.stock_esperado, 23)
        self.assertEqual(resultado_anterior.conteo_final, 3)
        self.assertEqual(resultado_anterior.diferencia, -20)
        self.assertEqual(resultado_anterior.tipo_diferencia, "faltante")

        actual = self.crear_periodo(
            3,
            "2026-08-09",
            "2026-08-16",
        )
        # El cierre real anterior fue 3; una compra de 20 lleva el esperado a 23.
        self.agregar_datos(
            actual,
            stock_inicial=3,
            compras=20,
            conteo=43,
        )
        resultado_actual = ejecutar_auditoria(actual)[0]

        self.assertEqual(resultado_actual.stock_esperado, 23)
        self.assertEqual(resultado_actual.conteo_final, 43)
        self.assertEqual(resultado_actual.diferencia, 20)
        self.assertEqual(resultado_actual.diferencia_anterior_compensada, -20)
        self.assertEqual(resultado_actual.tipo_diferencia, "compensado")
        self.assertEqual(
            resultado_actual.causa_sugerida,
            "Compensación entre períodos",
        )
        self.assertEqual(resultado_actual.nivel_confianza, "Alto")
        self.assertEqual(resultado_actual.severidad, "Correcto")
        self.assertEqual(resultado_actual.impacto, 0)
        self.assertEqual(
            resultado_actual.estado_auditoria,
            "Sin diferencia real",
        )

    def test_sobrante_anterior_y_faltante_actual_quedan_compensados(self):
        anterior = self.crear_periodo(
            2,
            "2026-08-01",
            "2026-08-08",
        )
        self.agregar_datos(
            anterior,
            stock_inicial=23,
            compras=0,
            conteo=43,
        )
        resultado_anterior = ejecutar_auditoria(anterior)[0]
        self.assertEqual(resultado_anterior.stock_esperado, 23)
        self.assertEqual(resultado_anterior.conteo_final, 43)
        self.assertEqual(resultado_anterior.diferencia, 20)
        self.assertEqual(resultado_anterior.tipo_diferencia, "sobrante")

        actual = self.crear_periodo(
            3,
            "2026-08-09",
            "2026-08-16",
        )
        # El conteo anterior fue 43; una salida de 20 deja el esperado en 23.
        self.agregar_datos(
            actual,
            stock_inicial=43,
            compras=0,
            conteo=3,
            otras_salidas=20,
        )
        resultado_actual = ejecutar_auditoria(actual)[0]

        self.assertEqual(resultado_actual.stock_esperado, 23)
        self.assertEqual(resultado_actual.conteo_final, 3)
        self.assertEqual(resultado_actual.diferencia, -20)
        self.assertEqual(resultado_actual.diferencia_anterior_compensada, 20)
        self.assertEqual(resultado_actual.tipo_diferencia, "compensado")
        self.assertEqual(
            resultado_actual.causa_sugerida,
            "Compensación entre períodos",
        )
        self.assertEqual(resultado_actual.nivel_confianza, "Alto")
        self.assertEqual(resultado_actual.severidad, "Correcto")
        self.assertEqual(resultado_actual.impacto, 0)
        self.assertEqual(
            resultado_actual.estado_auditoria,
            "Sin diferencia real",
        )


if __name__ == "__main__":
    unittest.main()
