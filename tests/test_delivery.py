import unittest

from flask import Flask, session

from core import empleado as empleado_service
from core.auditoria import ejecutar_auditoria
from core.models import (
    ConteoDetalle,
    DeliveryProducto,
    DeliveryVenta,
    ExcelDetalle,
    ExcelImportado,
    InventarioPeriodo,
    Producto,
    db,
)


CLIENTE = "TEST"
TIENDA = "TTEST"
PRODUCTO = "Combo Delivery"


class PruebasDelivery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            TESTING=True,
            SECRET_KEY="testing",
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
        self.producto_interno = Producto(
            nombre=PRODUCTO,
            categoria="Delivery",
            visible_empleado=True,
        )
        self.producto_delivery = DeliveryProducto(
            cliente_id=CLIENTE,
            nombre=PRODUCTO,
            precio=12500,
            activo=True,
        )
        db.session.add_all([self.producto_interno, self.producto_delivery])
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()

    def registrar_venta(self, cantidad=3, fecha="2026-08-03"):
        with self.app.test_request_context():
            session["cliente_id"] = CLIENTE
            resultado = empleado_service.registrar_venta_delivery(
                tienda_id=TIENDA,
                usuario="empleado",
                producto_id=self.producto_delivery.id,
                cantidad=cantidad,
                fecha=fecha,
            )
            db.session.flush()
        return resultado, DeliveryVenta.query.one()

    def test_registrar_venta_delivery(self):
        resultado, venta = self.registrar_venta(cantidad=3)

        self.assertEqual(resultado[0], PRODUCTO)
        self.assertIsNotNone(venta.id)
        self.assertEqual(venta.cliente_id, CLIENTE)
        self.assertEqual(venta.tienda_id, TIENDA)
        self.assertEqual(venta.producto, PRODUCTO)
        self.assertEqual(venta.cantidad, 3)
        self.assertEqual(venta.precio_unitario, 12500)

    def test_total_delivery_es_precio_por_cantidad(self):
        resultado, venta = self.registrar_venta(cantidad=3)

        self.assertEqual(resultado[1], 37500)
        self.assertEqual(venta.total, 37500)

    def test_auditoria_reemplaza_venta_real_con_delivery(self):
        self.registrar_venta(cantidad=4)
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
        db.session.add(ConteoDetalle(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario="empleado",
            producto_nombre=PRODUCTO,
            categoria="Delivery",
            cantidad_unidad=6,
            cantidad_caja=0,
            cantidad_bulto=0,
            total_unidad_base=6,
            fue_cargado=True,
        ))
        excel = ExcelImportado(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            nombre_archivo="delivery.xlsx",
            usuario_importador="tester",
            estado_validacion="ok",
        )
        db.session.add(excel)
        db.session.flush()
        db.session.add(ExcelDetalle(
            excel_id=excel.id,
            articulo="DEL-001",
            artdescrip=PRODUCTO,
            stockinicial=10,
            ventareal=9,
            producto_nombre_interno=PRODUCTO,
            producto_id=self.producto_interno.id,
            estado_vinculacion="vinculado",
            excluido_auditoria=False,
        ))
        db.session.flush()

        resultados = ejecutar_auditoria(periodo)

        self.assertEqual(len(resultados), 1)
        resultado = resultados[0]
        self.assertEqual(resultado.ventas_delivery, 4)
        self.assertEqual(resultado.ventas, 4)
        self.assertEqual(resultado.stock_esperado, 6)
        self.assertEqual(resultado.conteo_final, 6)
        self.assertEqual(resultado.diferencia, 0)


if __name__ == "__main__":
    unittest.main()
