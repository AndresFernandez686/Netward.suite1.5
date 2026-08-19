import unittest

from flask import Flask

from core.auditoria import ejecutar_auditoria
from core.models import (
    AuditoriaResultado,
    ConteoDetalle,
    ExcelDetalle,
    ExcelImportado,
    HistorialMovimiento,
    InventarioPeriodo,
    Producto,
    db,
)
from core.periodos import cerrar_periodo
from core.sync_bridge import retroalimentar_periodo_desde_items


CLIENTE = "TEST"
TIENDA = "TTEST"
PRODUCTO = "Producto de prueba"


class PruebasPeriodos(unittest.TestCase):
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
        db.session.add(Producto(
            nombre=PRODUCTO,
            categoria="Pruebas",
            visible_empleado=True,
        ))
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()

    def crear_periodo(self, numero, desde, hasta, estado="Abierto"):
        periodo = InventarioPeriodo(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            numero=numero,
            fecha_desde=desde,
            fecha_hasta=hasta,
            dias_periodo=7,
            estado=estado,
            usuario_creador="tester",
        )
        db.session.add(periodo)
        db.session.flush()
        return periodo

    def agregar_conteo(self, periodo, cantidad, fue_cargado=True):
        conteo = ConteoDetalle(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario="tester",
            producto_nombre=PRODUCTO,
            categoria="Pruebas",
            cantidad_unidad=cantidad,
            cantidad_caja=0,
            cantidad_bulto=0,
            total_unidad_base=cantidad,
            fue_cargado=fue_cargado,
        )
        db.session.add(conteo)
        db.session.flush()
        return conteo

    def test_crear_periodo_sin_historial_deja_producto_pendiente(self):
        periodo = self.crear_periodo(1, "2026-08-01", "2026-08-08")

        importados = retroalimentar_periodo_desde_items(periodo)
        conteo = ConteoDetalle.query.filter_by(
            periodo_id=periodo.id,
            producto_nombre=PRODUCTO,
        ).one()

        self.assertEqual(importados, 0)
        self.assertFalse(conteo.fue_cargado)
        self.assertEqual(conteo.total_unidad_base, 0)
        self.assertEqual(periodo.estado, "Abierto")

    def test_crear_periodo_con_historial_importa_ultima_carga(self):
        db.session.add_all([
            HistorialMovimiento(
                cliente_id=CLIENTE,
                tienda_id=TIENDA,
                fecha="2026-08-03",
                hora="08:00",
                usuario="empleado",
                categoria="Pruebas",
                producto=PRODUCTO,
                cantidad=7,
            ),
            HistorialMovimiento(
                cliente_id=CLIENTE,
                tienda_id=TIENDA,
                fecha="2026-08-05",
                hora="09:00",
                usuario="empleado",
                categoria="Pruebas",
                producto=PRODUCTO,
                cantidad=11,
            ),
        ])
        periodo = self.crear_periodo(1, "2026-08-01", "2026-08-08")
        db.session.flush()

        importados = retroalimentar_periodo_desde_items(periodo)
        conteo = ConteoDetalle.query.filter_by(
            periodo_id=periodo.id,
            producto_nombre=PRODUCTO,
        ).one()

        self.assertEqual(importados, 1)
        self.assertTrue(conteo.fue_cargado)
        self.assertEqual(conteo.total_unidad_base, 11)
        self.assertEqual(periodo.estado, "Cargado")

    def test_cierre_falla_con_pendientes_y_pasa_con_todo_cargado(self):
        periodo = self.crear_periodo(1, "2026-08-01", "2026-08-08")
        conteo = self.agregar_conteo(periodo, 0, fue_cargado=False)

        cerrado, pendientes = cerrar_periodo(periodo)

        self.assertFalse(cerrado)
        self.assertEqual(pendientes, [PRODUCTO])
        self.assertEqual(periodo.estado, "Abierto")
        self.assertIsNone(periodo.fecha_cierre)

        conteo.fue_cargado = True
        cerrado, pendientes = cerrar_periodo(periodo)

        self.assertTrue(cerrado)
        self.assertEqual(pendientes, [])
        self.assertEqual(periodo.estado, "Cerrado")
        self.assertIsNotNone(periodo.fecha_cierre)

    def preparar_continuidad(self, stock_inicial_actual):
        anterior = self.crear_periodo(
            1, "2026-08-01", "2026-08-08", estado="Cerrado"
        )
        self.agregar_conteo(anterior, 10)

        actual = self.crear_periodo(
            2, "2026-08-09", "2026-08-16", estado="Cerrado"
        )
        self.agregar_conteo(actual, 10)
        excel = ExcelImportado(
            periodo_id=actual.id,
            cliente_id=CLIENTE,
            nombre_archivo="continuidad.xlsx",
            usuario_importador="tester",
            estado_validacion="ok",
        )
        db.session.add(excel)
        db.session.flush()
        db.session.add(ExcelDetalle(
            excel_id=excel.id,
            articulo="TEST-001",
            artdescrip=PRODUCTO,
            producto_nombre_interno=PRODUCTO,
            stockinicial=stock_inicial_actual,
            stockfinal=10,
            estado_vinculacion="vinculado",
            excluido_auditoria=False,
        ))
        db.session.flush()
        return actual

    def test_continuidad_coincidente_no_genera_alerta(self):
        actual = self.preparar_continuidad(stock_inicial_actual=10)

        resultados = ejecutar_auditoria(actual)

        self.assertEqual(len(resultados), 1)
        self.assertFalse(resultados[0].alerta_continuidad)
        self.assertEqual(resultados[0].stock_inicial_anterior, 10)
        self.assertEqual(resultados[0].stock_inicial_excel, 10)

    def test_continuidad_distinta_genera_alerta(self):
        actual = self.preparar_continuidad(stock_inicial_actual=7)

        resultados = ejecutar_auditoria(actual)

        self.assertEqual(len(resultados), 1)
        self.assertTrue(resultados[0].alerta_continuidad)


if __name__ == "__main__":
    unittest.main()
