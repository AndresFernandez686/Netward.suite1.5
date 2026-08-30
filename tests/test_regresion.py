import unittest

from flask import Flask

from core.auditoria import ejecutar_auditoria
from core.models import (
    ConteoDetalle,
    DeliveryVenta,
    ExcelDetalle,
    ExcelImportado,
    InventarioPeriodo,
    Producto,
    RegistroAveriado,
    RegistroVencimiento,
    db,
)


CLIENTE = "TEST"
TIENDA = "TTEST"
PRODUCTO = "Producto regresión"


class PruebasRegresion(unittest.TestCase):
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
            categoria="Pruebas",
            visible_empleado=True,
        )
        db.session.add(self.producto)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()

    def crear_periodo(self):
        periodo = InventarioPeriodo(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            numero=1,
            fecha_desde="2026-08-01",
            fecha_hasta="2026-08-08",
            dias_periodo=7,
            estado="Cerrado",
            usuario_creador="tester",
        )
        db.session.add(periodo)
        db.session.flush()
        return periodo

    def agregar_conteo(self, periodo, cantidad):
        db.session.add(ConteoDetalle(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario="empleado",
            producto_nombre=PRODUCTO,
            categoria="Pruebas",
            cantidad_unidad=cantidad,
            cantidad_caja=0,
            cantidad_bulto=0,
            total_unidad_base=cantidad,
            fue_cargado=True,
        ))

    def agregar_excel(
        self,
        periodo,
        *,
        stock_inicial,
        compras=0,
        ventas=0,
        stock_final=0,
    ):
        excel = ExcelImportado(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            nombre_archivo="regresion.xlsx",
            usuario_importador="tester",
            estado_validacion="ok",
        )
        db.session.add(excel)
        db.session.flush()
        db.session.add(ExcelDetalle(
            excel_id=excel.id,
            articulo="REG-001",
            artdescrip=PRODUCTO,
            stockinicial=stock_inicial,
            compras=compras,
            ventareal=ventas,
            stockfinal=stock_final,
            producto_nombre_interno=PRODUCTO,
            producto_id=self.producto.id,
            estado_vinculacion="vinculado",
            excluido_auditoria=False,
        ))
        db.session.flush()

    def test_periodo_sin_movimientos_permanece_correcto(self):
        periodo = self.crear_periodo()
        self.agregar_conteo(periodo, 10)
        self.agregar_excel(periodo, stock_inicial=10, stock_final=10)

        resultados = ejecutar_auditoria(periodo)

        self.assertEqual(len(resultados), 1)
        resultado = resultados[0]
        self.assertEqual(resultado.conteo_final, 10)
        self.assertEqual(resultado.stock_inicial_excel, 10)
        self.assertEqual(resultado.stock_esperado, 10)
        self.assertEqual(resultado.diferencia, 0)
        self.assertEqual(resultado.tipo_diferencia, "correcto")
        self.assertEqual(resultado.causa_sugerida, "Sin diferencia")
        self.assertFalse(resultado.alerta_continuidad)
        self.assertEqual(resultado.diferencia_anterior_compensada, 0)

    def test_periodo_con_todos_los_movimientos(self):
        periodo = self.crear_periodo()
        # 100 + 20 compras - 10 delivery - 5 mermas - 3 vencidos = 102.
        self.agregar_conteo(periodo, 102)
        self.agregar_excel(
            periodo,
            stock_inicial=100,
            compras=20,
            ventas=99,
            stock_final=102,
        )
        db.session.add(DeliveryVenta(
            cliente_id=CLIENTE,
            fecha="2026-08-03",
            producto=PRODUCTO,
            cantidad=10,
            precio_unitario=1000,
            total=10000,
            usuario="empleado",
            tienda_id=TIENDA,
        ))
        db.session.add(RegistroAveriado(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            periodo_id=periodo.id,
            fecha="2026-08-04",
            usuario="empleado",
            categoria="Pruebas",
            producto=PRODUCTO,
            cantidad=5,
            cantidad_unidades=5,
            ume="Unidad",
            sinc_estado="sincronizado",
        ))
        db.session.add(RegistroVencimiento(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            fecha="2026-08-05",
            usuario="empleado",
            categoria="Pruebas",
            producto=PRODUCTO,
            cantidad=3,
            cantidad_unidades=3,
            ume="Unidad",
            fecha_vencimiento="2026-08-20",
            sinc_estado="sincronizado",
        ))
        db.session.flush()

        resultados = ejecutar_auditoria(periodo)

        self.assertEqual(len(resultados), 1)
        resultado = resultados[0]
        self.assertEqual(resultado.stock_inicial_excel, 100)
        self.assertEqual(resultado.compras, 20)
        self.assertEqual(resultado.ventas_delivery, 10)
        self.assertEqual(resultado.ventas, 10)
        self.assertNotEqual(resultado.ventas, 99)
        self.assertEqual(resultado.cantidad_merma, 5)
        self.assertEqual(resultado.cantidad_vencida, 3)
        self.assertEqual(resultado.stock_esperado, 102)
        self.assertEqual(resultado.conteo_final, 102)
        self.assertEqual(resultado.diferencia, 0)
        self.assertEqual(resultado.tipo_diferencia, "correcto")


if __name__ == "__main__":
    unittest.main()
