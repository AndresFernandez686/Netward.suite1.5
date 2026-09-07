import unittest

from flask import Flask, session

from core import empleado as empleado_service
from core.models import (
    ConteoDetalle,
    HistorialMovimiento,
    InventarioItem,
    InventarioPeriodo,
    RegistroAveriado,
    RegistroVencimiento,
    db,
)


CLIENTE = "TEST"
TIENDA = "TTEST"
PRODUCTO = "Chocolate"


class PruebasInventarioPorKilos(unittest.TestCase):
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
        self.periodo = InventarioPeriodo(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            numero=1,
            fecha_desde="2026-09-01",
            fecha_hasta="2026-09-08",
            dias_periodo=7,
            estado="Abierto",
            usuario_creador="admin",
        )
        db.session.add(self.periodo)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()

    def test_balde_lleno_convierte_a_kg(self):
        resultado = empleado_service.normalizar_conteo_kilos(
            estado_balde="Lleno", cantidad_baldes="2", peso_kg=""
        )
        self.assertEqual(resultado["cantidad_unidades"], 15.6)
        self.assertEqual(resultado["ume"], "kg")
        self.assertIn("2 baldes llenos", resultado["desc_conversion"])
        self.assertIn("7,800 kg", resultado["desc_conversion"])

    def test_medio_lleno_usa_peso_real(self):
        resultado = empleado_service.normalizar_conteo_kilos(
            estado_balde="Medio lleno", cantidad_baldes="", peso_kg="3,500"
        )
        self.assertEqual(resultado["cantidad_unidades"], 3.5)
        self.assertIn("peso real", resultado["desc_conversion"])

    def test_vacio_conserva_baldes_sin_sumar_stock(self):
        resultado = empleado_service.normalizar_conteo_kilos(
            estado_balde="Vacio", cantidad_baldes="3", peso_kg=""
        )
        self.assertEqual(resultado["cantidad_unidades"], 0)
        self.assertEqual(resultado["cantidad_baldes"], 3)
        self.assertIn("3 baldes vacíos", resultado["desc_conversion"])

    def test_rechaza_combinaciones_y_precision_invalidas(self):
        casos = (
            {"estado_balde": "Lleno", "cantidad_baldes": "1.5", "peso_kg": ""},
            {"estado_balde": "Medio lleno", "cantidad_baldes": "1", "peso_kg": "3.5"},
            {"estado_balde": "Medio lleno", "cantidad_baldes": "", "peso_kg": "0.0001"},
            {"estado_balde": "Vacio", "cantidad_baldes": "0", "peso_kg": ""},
        )
        for datos in casos:
            with self.subTest(datos=datos), self.assertRaises(ValueError):
                empleado_service.normalizar_conteo_kilos(**datos)

    def test_carrito_y_guardado_no_aplican_doble_conversion(self):
        carrito, _ = empleado_service.add_carrito_item(
            carrito=[],
            categoria="Por Kilos",
            producto=PRODUCTO,
            cantidad=0,
            ume="kg",
            tipo_inventario="Diario",
            fecha="2026-09-02",
            detalle="",
            estado_balde="Lleno",
            cantidad_baldes="2",
            peso_kg="",
        )
        self.assertEqual(carrito[0]["cantidad_unidades"], 15.6)
        with self.app.test_request_context():
            session["cliente_id"] = CLIENTE
            empleado_service.build_carrito_guardado(
                carrito,
                TIENDA,
                "empleado",
                cliente_id=CLIENTE,
                periodo_id=self.periodo.id,
            )
            db.session.flush()

        item = InventarioItem.query.one()
        conteo = ConteoDetalle.query.one()
        historial = HistorialMovimiento.query.one()
        self.assertEqual(item.cantidad, 15.6)
        self.assertEqual(item.ume, "kg")
        self.assertEqual(conteo.total_unidad_base, 15.6)
        self.assertEqual(historial.cantidad, 15.6)
        self.assertEqual(historial.modo, "kg")

    def test_averiado_y_vencimiento_aceptan_tres_decimales_en_kg(self):
        with self.app.test_request_context():
            session["cliente_id"] = CLIENTE
            empleado_service.registrar_averiado(
                tienda_id=TIENDA,
                usuario="empleado",
                categoria="Por Kilos",
                producto=PRODUCTO,
                cantidad=0.750,
                ume="Unidad",
                detalle="",
                fecha="2026-09-02",
                periodo_id=self.periodo.id,
            )
            empleado_service.registrar_vencimiento(
                tienda_id=TIENDA,
                usuario="empleado",
                categoria="Por Kilos",
                producto=PRODUCTO,
                cantidad=1.125,
                ume="Unidad",
                fecha_vencimiento="2026-09-10",
                detalle="",
                fecha="2026-09-02",
            )
            db.session.flush()

        averiado = RegistroAveriado.query.one()
        vencimiento = RegistroVencimiento.query.one()
        self.assertEqual((averiado.cantidad, averiado.cantidad_unidades, averiado.ume), (0.75, 0.75, "kg"))
        self.assertEqual((vencimiento.cantidad, vencimiento.cantidad_unidades, vencimiento.ume), (1.125, 1.125, "kg"))

    def test_categorias_por_unidades_siguen_exigiendo_enteros(self):
        with self.assertRaisesRegex(ValueError, "entero"):
            empleado_service.normalizar_cantidad_categoria("Impulsivo", "1.5")
        cantidad, ume = empleado_service.normalizar_cantidad_categoria("Impulsivo", "2")
        self.assertEqual((cantidad, ume), (2.0, "Unidad"))

    def test_ajustes_en_kilos_aceptan_decimales_con_signo(self):
        self.assertEqual(
            empleado_service.normalizar_ajuste_categoria("Por Kilos", "-0,750"),
            (-0.75, "kg"),
        )
        with self.assertRaisesRegex(ValueError, "entero"):
            empleado_service.normalizar_ajuste_categoria("Impulsivo", "-0.750")


if __name__ == "__main__":
    unittest.main()
