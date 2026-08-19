import json
import unittest

from flask import Flask, session

from core import empleado as empleado_service
from core.auditoria import build_reporte_gerencial, ejecutar_auditoria
from core.models import (
    ConteoDetalle,
    ExcelDetalle,
    ExcelImportado,
    HistorialMovimiento,
    InventarioItem,
    InventarioBorrador,
    InventarioPeriodo,
    Producto,
    db,
)
from core.sync_bridge import propagar_conteo_a_periodo


CLIENTE = "TEST"
TIENDA = "TTEST"
PRODUCTO = "Alfajor Almendrado"
OTRO_PRODUCTO = "Chocolate Blanco"


class PruebasInventarioMultiempleado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            TESTING=True,
            SECRET_KEY="test",
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
        db.session.add_all([
            Producto(nombre=PRODUCTO, categoria="Impulsivo", visible_empleado=True),
            Producto(nombre=OTRO_PRODUCTO, categoria="Impulsivo", visible_empleado=True),
        ])
        self.periodo = InventarioPeriodo(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            numero=1,
            fecha_desde="2026-08-19",
            fecha_hasta="2026-08-20",
            dias_periodo=2,
            estado="Abierto",
            usuario_creador="admin",
        )
        db.session.add(self.periodo)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()

    def carrito(self, producto, cantidad, *, version=0, confirmar=False):
        carrito, _ = empleado_service.add_carrito_item(
            carrito=[],
            categoria="Impulsivo",
            producto=producto,
            cantidad=cantidad,
            ume="Unidad",
            tipo_inventario="Diario",
            fecha="2026-08-19",
            detalle="Prueba multi-empleado",
            version_esperada=version,
            confirmar_sobreescritura=confirmar,
        )
        return carrito

    def guardar(self, usuario, carrito, *, commit=True):
        with self.app.test_request_context():
            session.update(
                cliente_id=CLIENTE,
                tienda_id=TIENDA,
                usuario=usuario,
                empleado_periodo_id=self.periodo.id,
            )
            resultado = empleado_service.build_carrito_guardado(
                carrito,
                TIENDA,
                usuario,
                cliente_id=CLIENTE,
                periodo_id=self.periodo.id,
            )
            if commit:
                db.session.commit()
            else:
                db.session.flush()
            return resultado

    def sincronizar(self, usuario):
        propagados = propagar_conteo_a_periodo(
            tienda_id=TIENDA,
            cliente_id=CLIENTE,
            usuario=usuario,
            periodo_id=self.periodo.id,
        )
        resumen = empleado_service.procesar_sincronizacion(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario=usuario,
            accion="solo_enviar",
        )
        db.session.commit()
        return propagados, resumen

    def test_01_continuidad_entre_empleados(self):
        self.guardar("Empleado A", self.carrito(PRODUCTO, 7))

        cargas = empleado_service.listar_cargas_periodo(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            periodo_id=self.periodo.id,
        )
        self.assertEqual(len(cargas), 1)
        self.assertEqual(cargas[0]["cantidad"], 7)
        self.assertEqual(cargas[0]["usuario"], "Empleado A")

    def test_02_producto_ya_cargado_exige_confirmacion(self):
        self.guardar("Empleado A", self.carrito(PRODUCTO, 7))

        with self.assertRaises(empleado_service.ConflictoCarga) as captura:
            self.guardar("Empleado B", self.carrito(PRODUCTO, 9, version=1))
        self.assertEqual(captura.exception.usuario, "Empleado A")
        self.assertEqual(captura.exception.cantidad, 7)

    def test_03_sobreescritura_actualiza_usuario_y_conserva_historial(self):
        self.guardar("Empleado A", self.carrito(PRODUCTO, 7))
        self.guardar(
            "Empleado B",
            self.carrito(PRODUCTO, 9, version=1, confirmar=True),
        )

        item = InventarioItem.query.filter_by(producto=PRODUCTO).one()
        self.assertEqual(item.cantidad, 9)
        self.assertEqual(item.usuario_ultima_carga, "Empleado B")
        self.assertTrue(item.fue_sobreescrito)
        movimientos = HistorialMovimiento.query.filter_by(producto=PRODUCTO).order_by(
            HistorialMovimiento.id
        ).all()
        self.assertEqual([m.tipo_movimiento for m in movimientos], ["original", "sobreescritura"])
        self.assertEqual(movimientos[1].usuario_anterior, "Empleado A")
        self.assertEqual(movimientos[1].cantidad_anterior, 7)

    def test_04_cancelar_sobreescritura_no_modifica_ni_crea_historial(self):
        self.guardar("Empleado A", self.carrito(PRODUCTO, 7))

        with self.assertRaises(empleado_service.ConflictoCarga):
            self.guardar("Empleado B", self.carrito(PRODUCTO, 9, version=1))
        db.session.rollback()

        item = InventarioItem.query.filter_by(producto=PRODUCTO).one()
        self.assertEqual(item.cantidad, 7)
        self.assertEqual(item.usuario_ultima_carga, "Empleado A")
        self.assertEqual(HistorialMovimiento.query.filter_by(producto=PRODUCTO).count(), 1)

    def test_05_sincronizacion_parcial_por_empleado_es_consistente(self):
        self.guardar("Empleado A", self.carrito(PRODUCTO, 7))
        self.guardar("Empleado B", self.carrito(OTRO_PRODUCTO, 4))

        propagados_a, resumen_a = self.sincronizar("Empleado A")
        self.assertEqual(propagados_a, 1)
        self.assertEqual(resumen_a["n_inv"], 1)
        self.assertEqual(
            InventarioItem.query.filter_by(producto=OTRO_PRODUCTO).one().sinc_estado,
            "pendiente",
        )

        propagados_b, resumen_b = self.sincronizar("Empleado B")
        self.assertEqual(propagados_b, 1)
        self.assertEqual(resumen_b["n_inv"], 1)
        self.assertEqual(InventarioItem.query.filter_by(sinc_estado="sincronizado").count(), 2)
        self.assertEqual(ConteoDetalle.query.filter_by(periodo_id=self.periodo.id, fue_cargado=True).count(), 2)

    def test_06_conflicto_simultaneo_rechaza_la_version_obsoleta(self):
        carrito_a = self.carrito(PRODUCTO, 7, version=0)
        carrito_b = self.carrito(PRODUCTO, 11, version=0)

        self.guardar("Empleado A", carrito_a)
        with self.assertRaises(empleado_service.ConflictoCarga) as captura:
            self.guardar("Empleado B", carrito_b)
        db.session.rollback()

        item = InventarioItem.query.filter_by(producto=PRODUCTO).one()
        self.assertEqual(item.cantidad, 7)
        self.assertEqual(item.usuario_ultima_carga, "Empleado A")
        self.assertEqual(captura.exception.version, 1)

    def test_07_auditoria_usa_solo_la_ultima_carga_valida(self):
        self.guardar("Empleado A", self.carrito(PRODUCTO, 7))
        self.sincronizar("Empleado A")
        self.guardar("Empleado B", self.carrito(PRODUCTO, 9, version=1, confirmar=True))
        self.sincronizar("Empleado B")

        producto = Producto.query.filter_by(nombre=PRODUCTO).one()
        excel = ExcelImportado(
            periodo_id=self.periodo.id,
            cliente_id=CLIENTE,
            nombre_archivo="multiempleado.xlsx",
            usuario_importador="admin",
            estado_validacion="ok",
        )
        db.session.add(excel)
        db.session.flush()
        db.session.add(ExcelDetalle(
            excel_id=excel.id,
            articulo="ALF-001",
            artdescrip=PRODUCTO,
            artcosto=500,
            stockinicial=9,
            stockfinal=9,
            producto_id=producto.id,
            producto_nombre_interno=PRODUCTO,
            estado_vinculacion="vinculado",
            excluido_auditoria=False,
        ))
        db.session.commit()

        self.assertEqual(ConteoDetalle.query.filter_by(periodo_id=self.periodo.id, producto_nombre=PRODUCTO).count(), 1)
        resultado = ejecutar_auditoria(self.periodo)[0]
        self.assertEqual(resultado.conteo_final, 9)
        self.assertEqual(resultado.diferencia, 0)
        self.assertEqual(resultado.usuario_conteo, "Empleado B")

    def test_08_reporte_muestra_usuario_y_sobreescritura_sin_duplicar(self):
        self.guardar("Empleado A", self.carrito(PRODUCTO, 7))
        self.sincronizar("Empleado A")
        self.guardar("Empleado B", self.carrito(PRODUCTO, 9, version=1, confirmar=True))
        self.sincronizar("Empleado B")

        reporte = build_reporte_gerencial(self.periodo)
        cargas = [c for c in reporte["cargas"] if c.producto_nombre == PRODUCTO]
        self.assertEqual(len(cargas), 1)
        self.assertEqual(cargas[0].usuario, "Empleado B")
        self.assertTrue(cargas[0].fue_sobreescrito)
        self.assertEqual(cargas[0].total_unidad_base, 9)

    def test_09_borrador_de_un_empleado_es_visible_y_genera_conflicto(self):
        carrito_a = self.carrito(PRODUCTO, 7)
        db.session.add(InventarioBorrador(
            cliente_id=CLIENTE,
            periodo_id=self.periodo.id,
            tienda_id=TIENDA,
            usuario="Empleado A",
            contenido_json=json.dumps(carrito_a),
        ))
        db.session.commit()

        cargas = empleado_service.listar_cargas_periodo(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            periodo_id=self.periodo.id,
        )
        self.assertEqual(len(cargas), 1)
        self.assertEqual(cargas[0]["cantidad"], 7)
        self.assertEqual(cargas[0]["usuario"], "Empleado A")
        self.assertTrue(cargas[0]["es_borrador"])

        actual = empleado_service.obtener_carga_actual(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            periodo_id=self.periodo.id,
            categoria="Impulsivo",
            producto=PRODUCTO,
            excluir_usuario="Empleado B",
        )
        with self.assertRaises(empleado_service.ConflictoCarga):
            self.guardar(
                "Empleado B",
                self.carrito(PRODUCTO, 9, version=actual["version"]),
            )

        self.guardar(
            "Empleado B",
            self.carrito(
                PRODUCTO,
                9,
                version=actual["version"],
                confirmar=True,
            ),
        )
        item = InventarioItem.query.filter_by(producto=PRODUCTO).one()
        self.assertEqual(item.cantidad, 9)
        self.assertEqual(item.usuario_ultima_carga, "Empleado B")
        self.assertEqual(InventarioBorrador.query.filter_by(usuario="Empleado A").count(), 0)

    def test_10_cargas_compartidas_aisladas_por_empresa_y_tienda(self):
        contenido = json.dumps(self.carrito(PRODUCTO, 7))
        db.session.add_all([
            InventarioBorrador(
                cliente_id=CLIENTE,
                periodo_id=self.periodo.id,
                tienda_id=TIENDA,
                usuario="Empleado tienda correcta",
                contenido_json=contenido,
            ),
            InventarioBorrador(
                cliente_id=CLIENTE,
                periodo_id=self.periodo.id,
                tienda_id="OTRA_TIENDA",
                usuario="Empleado otra tienda",
                contenido_json=json.dumps(self.carrito(OTRO_PRODUCTO, 50)),
            ),
            InventarioBorrador(
                cliente_id="OTRA_EMPRESA",
                periodo_id=self.periodo.id,
                tienda_id=TIENDA,
                usuario="Empleado otra empresa",
                contenido_json=json.dumps(self.carrito(OTRO_PRODUCTO, 80)),
            ),
        ])
        db.session.commit()

        cargas = empleado_service.listar_cargas_periodo(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            periodo_id=self.periodo.id,
        )
        self.assertEqual(len(cargas), 1)
        self.assertEqual(cargas[0]["usuario"], "Empleado tienda correcta")
        self.assertEqual(cargas[0]["cantidad"], 7)
        self.assertNotIn("Empleado otra tienda", {c["usuario"] for c in cargas})
        self.assertNotIn("Empleado otra empresa", {c["usuario"] for c in cargas})


if __name__ == "__main__":
    unittest.main()
