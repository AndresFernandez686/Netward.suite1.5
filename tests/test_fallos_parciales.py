import unittest
from pathlib import Path

from flask import Flask, session

from core import empleado as empleado_service
from core.auditoria import _ventas_delivery_periodo, ejecutar_auditoria
from core.models import (
    ConteoDetalle,
    DeliveryProducto,
    DeliveryVenta,
    HistorialMovimiento,
    InventarioItem,
    InventarioPeriodo,
    InventarioSnapshot,
    Producto,
    db,
)
from core.sync_bridge import sincronizar_transaccional


CLIENTE = "FALLOS"
TIENDA = "T-FALLOS"
USUARIO = "empleado-red"


class PruebasFallosParciales(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            TESTING=True,
            SECRET_KEY="fallos-test",
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
            dias_periodo=8,
            estado="Abierto",
            usuario_creador="admin",
        )
        db.session.add(periodo)
        db.session.flush()
        return periodo

    def test_red_inestable_revierte_guardado_y_sync_y_permite_reintentar(self):
        producto = Producto(nombre="Producto con red inestable", categoria="Red", visible_empleado=True)
        periodo = self.crear_periodo(1, "2026-08-01", "2026-08-08")
        db.session.add(producto)
        db.session.commit()
        carrito = [{
            "categoria": producto.categoria,
            "producto": producto.nombre,
            "cantidad": 7,
            "cantidad_unidades": 7,
            "ume": "Unidad",
            "factor": 1,
            "desc_conversion": "",
            "tipo_inventario": "Diario",
            "fecha": "2026-08-03",
            "detalle": "Prueba de red",
            "hora": "12:00:00",
            "version_esperada": 0,
            "confirmar_sobreescritura": False,
        }]

        def cortar_red(_resultado):
            raise ConnectionError("conexión interrumpida")

        with self.assertRaises(ConnectionError):
            empleado_service.guardar_carrito_transaccional(
                carrito,
                TIENDA,
                USUARIO,
                cliente_id=CLIENTE,
                periodo_id=periodo.id,
                antes_commit=cortar_red,
            )
        self.assertEqual(InventarioItem.query.count(), 0)
        self.assertEqual(HistorialMovimiento.query.count(), 0)
        self.assertEqual(InventarioSnapshot.query.count(), 0)

        guardados = empleado_service.guardar_carrito_transaccional(
            carrito,
            TIENDA,
            USUARIO,
            cliente_id=CLIENTE,
            periodo_id=periodo.id,
        )
        self.assertEqual(guardados, 1)
        self.assertEqual(InventarioItem.query.filter_by(sinc_estado="pendiente").count(), 1)

        with self.assertRaises(ConnectionError):
            sincronizar_transaccional(
                cliente_id=CLIENTE,
                tienda_id=TIENDA,
                usuario=USUARIO,
                accion="solo_enviar",
                periodo=periodo,
                antes_commit=cortar_red,
            )
        self.assertEqual(ConteoDetalle.query.count(), 0)
        self.assertEqual(InventarioItem.query.filter_by(sinc_estado="pendiente").count(), 1)

        resumen = sincronizar_transaccional(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario=USUARIO,
            accion="solo_enviar",
            periodo=periodo,
        )
        self.assertEqual(resumen["n_inv"], 1)
        self.assertEqual(ConteoDetalle.query.count(), 1)
        self.assertEqual(InventarioItem.query.filter_by(sinc_estado="sincronizado").count(), 1)

        codigo_app = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
        self.assertIn("El carrito se conserva sin cambios; puedes reintentar", codigo_app)
        self.assertIn("Ningún dato fue marcado como enviado; puedes reintentar", codigo_app)

    def test_delivery_se_asigna_por_fecha_y_fuera_rango_no_se_mezcla(self):
        periodo_1 = self.crear_periodo(1, "2026-08-01", "2026-08-08")
        periodo_2 = self.crear_periodo(2, "2026-08-09", "2026-08-16")
        delivery = DeliveryProducto(
            cliente_id=CLIENTE,
            nombre="Delivery temporal",
            precio=1000,
            activo=True,
        )
        db.session.add(delivery)
        db.session.commit()

        with self.app.test_request_context():
            session["cliente_id"] = CLIENTE
            empleado_service.registrar_venta_delivery(
                tienda_id=TIENDA,
                usuario=USUARIO,
                producto_id=delivery.id,
                cantidad=4,
                fecha="2026-08-12",
            )
            empleado_service.registrar_venta_delivery(
                tienda_id=TIENDA,
                usuario=USUARIO,
                producto_id=delivery.id,
                cantidad=9,
                fecha="2026-08-20",
            )
            db.session.commit()

        en_rango = DeliveryVenta.query.filter_by(fecha="2026-08-12").one()
        fuera_rango = DeliveryVenta.query.filter_by(fecha="2026-08-20").one()
        self.assertEqual(en_rango.periodo_id, periodo_2.id)
        self.assertEqual(en_rango.estado_periodo, "en_rango")
        self.assertIsNone(fuera_rango.periodo_id)
        self.assertEqual(fuera_rango.estado_periodo, "fuera_rango")

        self.assertEqual(_ventas_delivery_periodo(periodo_1, delivery.nombre), 0)
        self.assertEqual(_ventas_delivery_periodo(periodo_2, delivery.nombre), 4)
        self.assertEqual(ejecutar_auditoria(periodo_1), [])
        resultados_2 = ejecutar_auditoria(periodo_2)
        self.assertEqual(len(resultados_2), 1)
        self.assertEqual(resultados_2[0].ventas_delivery, 4)
        self.assertEqual(resultados_2[0].estado_auditoria, "Sin datos")


if __name__ == "__main__":
    unittest.main()
