import unittest

from flask import Flask, session

from core import empleado as empleado_service
from core.auditoria import ejecutar_auditoria
from core.models import (
    ConteoDetalle,
    ExcelDetalle,
    ExcelImportado,
    InventarioPeriodo,
    Producto,
    ProductoPrecio,
    RegistroAveriado,
    RegistroVencimiento,
    db,
)


CLIENTE = "TEST"
TIENDA = "TTEST"
PRODUCTO = "Producto UME"


class PruebasAveriadosVencimientos(unittest.TestCase):
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
        self.producto = Producto(
            nombre=PRODUCTO,
            categoria="Pruebas",
            visible_empleado=True,
        )
        db.session.add(self.producto)
        db.session.flush()
        db.session.add(ProductoPrecio(
            cliente_id=CLIENTE,
            producto_nombre=PRODUCTO,
            producto_id=self.producto.id,
            categoria="Pruebas",
            unidades_por_caja=12,
            unidades_por_bulto=4,
        ))
        self.periodo = InventarioPeriodo(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            numero=1,
            fecha_desde="2026-08-01",
            fecha_hasta="2026-08-08",
            dias_periodo=7,
            estado="Abierto",
            usuario_creador="tester",
        )
        db.session.add(self.periodo)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()

    def registrar_averiado(self, cantidad=2, ume="Unidad", fecha="2026-08-03"):
        with self.app.test_request_context():
            session["cliente_id"] = CLIENTE
            convertido, descripcion = empleado_service.registrar_averiado(
                tienda_id=TIENDA,
                usuario="empleado",
                categoria="Pruebas",
                producto=PRODUCTO,
                cantidad=cantidad,
                ume=ume,
                detalle="Daño de prueba",
                fecha=fecha,
                periodo_id=self.periodo.id,
            )
            db.session.flush()
        return convertido, descripcion, RegistroAveriado.query.one()

    def registrar_vencimiento(
        self,
        cantidad=2,
        ume="Unidad",
        fecha="2026-08-04",
    ):
        with self.app.test_request_context():
            session["cliente_id"] = CLIENTE
            convertido, descripcion = empleado_service.registrar_vencimiento(
                tienda_id=TIENDA,
                usuario="empleado",
                categoria="Pruebas",
                producto=PRODUCTO,
                cantidad=cantidad,
                ume=ume,
                fecha_vencimiento="2026-08-20",
                detalle="Vencimiento de prueba",
                fecha=fecha,
            )
            db.session.flush()
        return convertido, descripcion, RegistroVencimiento.query.one()

    def test_registrar_averiado(self):
        convertido, descripcion, registro = self.registrar_averiado(
            cantidad=3,
            ume="Unidad",
        )

        self.assertIsNotNone(registro.id)
        self.assertEqual(registro.cliente_id, CLIENTE)
        self.assertEqual(registro.tienda_id, TIENDA)
        self.assertEqual(registro.periodo_id, self.periodo.id)
        self.assertEqual(registro.cantidad, 3)
        self.assertEqual(registro.cantidad_unidades, 3)
        self.assertEqual(registro.sinc_estado, "pendiente")
        self.assertEqual(convertido, 3)
        self.assertEqual(descripcion, "")

    def test_registrar_vencimiento(self):
        convertido, descripcion, registro = self.registrar_vencimiento(
            cantidad=5,
            ume="Unidad",
        )

        self.assertIsNotNone(registro.id)
        self.assertEqual(registro.fecha_vencimiento, "2026-08-20")
        self.assertEqual(registro.cantidad, 5)
        self.assertEqual(registro.cantidad_unidades, 5)
        self.assertEqual(registro.sinc_estado, "pendiente")
        self.assertEqual(convertido, 5)
        self.assertEqual(descripcion, "")

    def test_conversion_ume_en_averiado_y_vencimiento(self):
        convertido_averiado, descripcion_averiado, averiado = (
            self.registrar_averiado(cantidad=2, ume="Caja")
        )
        convertido_vencido, descripcion_vencido, vencido = (
            self.registrar_vencimiento(cantidad=1, ume="Bulto")
        )

        self.assertEqual(convertido_averiado, 24)
        self.assertEqual(averiado.cantidad_unidades, 24)
        self.assertIn("24 unid.", descripcion_averiado)
        self.assertEqual(convertido_vencido, 48)
        self.assertEqual(vencido.cantidad_unidades, 48)
        self.assertIn("48 unid.", descripcion_vencido)

    def test_sincronizacion_cambia_ambos_estados(self):
        _, _, averiado = self.registrar_averiado()
        _, _, vencido = self.registrar_vencimiento()

        resumen = empleado_service.procesar_sincronizacion(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario="empleado",
            accion="solo_enviar",
            periodo_id=self.periodo.id,
        )
        db.session.flush()

        self.assertEqual(resumen["n_aver"], 1)
        self.assertEqual(resumen["n_venc"], 1)
        self.assertEqual(resumen["n_total"], 2)
        self.assertEqual(averiado.sinc_estado, "sincronizado")
        self.assertEqual(vencido.sinc_estado, "sincronizado")

    def test_averiados_y_vencidos_reducen_stock_esperado(self):
        _, _, averiado = self.registrar_averiado(cantidad=2, ume="Caja")
        _, _, vencido = self.registrar_vencimiento(cantidad=1, ume="Caja")
        empleado_service.procesar_sincronizacion(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario="empleado",
            accion="solo_enviar",
            periodo_id=self.periodo.id,
        )

        self.periodo.estado = "Cerrado"
        db.session.add(ConteoDetalle(
            periodo_id=self.periodo.id,
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario="empleado",
            producto_nombre=PRODUCTO,
            categoria="Pruebas",
            cantidad_unidad=64,
            cantidad_caja=0,
            cantidad_bulto=0,
            total_unidad_base=64,
            fue_cargado=True,
        ))
        excel = ExcelImportado(
            periodo_id=self.periodo.id,
            cliente_id=CLIENTE,
            nombre_archivo="averiados-vencidos.xlsx",
            usuario_importador="tester",
            estado_validacion="ok",
        )
        db.session.add(excel)
        db.session.flush()
        db.session.add(ExcelDetalle(
            excel_id=excel.id,
            articulo="UME-001",
            artdescrip=PRODUCTO,
            stockinicial=100,
            producto_nombre_interno=PRODUCTO,
            producto_id=self.producto.id,
            estado_vinculacion="vinculado",
            excluido_auditoria=False,
        ))
        db.session.flush()

        resultados = ejecutar_auditoria(self.periodo)

        self.assertEqual(len(resultados), 1)
        resultado = resultados[0]
        self.assertEqual(averiado.cantidad_unidades, 24)
        self.assertEqual(vencido.cantidad_unidades, 12)
        self.assertEqual(resultado.cantidad_merma, 24)
        self.assertEqual(resultado.cantidad_vencida, 12)
        self.assertEqual(resultado.stock_esperado, 64)
        self.assertEqual(resultado.diferencia, 0)

    def test_motor_no_mezcla_averiado_de_otro_periodo_con_misma_fecha(self):
        otro = InventarioPeriodo(
            cliente_id=CLIENTE, tienda_id=TIENDA, numero=2,
            fecha_desde="2026-08-01", fecha_hasta="2026-08-08",
            dias_periodo=7, estado="Abierto", usuario_creador="tester",
        )
        db.session.add(otro)
        db.session.flush()
        with self.app.test_request_context():
            session["cliente_id"] = CLIENTE
            empleado_service.registrar_averiado(
                tienda_id=TIENDA, usuario="empleado", categoria="Pruebas",
                producto=PRODUCTO, cantidad=7, ume="Unidad",
                detalle="Pertenece a otro período", fecha="2026-08-03",
                periodo_id=otro.id,
            )
        RegistroAveriado.query.update(
            {RegistroAveriado.sinc_estado: "sincronizado"},
            synchronize_session=False,
        )
        db.session.flush()

        from core.auditoria import _mermas_vencidos
        merma, _vencidos = _mermas_vencidos(self.periodo, PRODUCTO, TIENDA)
        self.assertEqual(merma, 0)

    def test_fecha_del_averiado_debe_pertenecer_al_periodo(self):
        with self.app.test_request_context():
            session["cliente_id"] = CLIENTE
            with self.assertRaisesRegex(ValueError, "debe estar entre"):
                empleado_service.registrar_averiado(
                    tienda_id=TIENDA, usuario="empleado", categoria="Pruebas",
                    producto=PRODUCTO, cantidad=1, ume="Unidad", detalle="",
                    fecha="2026-08-20", periodo_id=self.periodo.id,
                )


if __name__ == "__main__":
    unittest.main()
