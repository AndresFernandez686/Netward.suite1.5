import json
import unittest
from datetime import date

from flask import Flask

from core.auditoria import ejecutar_auditoria
from core.inventario import desc_bp, _datos_extraidos_del_periodo
from core.excel_importer import contar_detalles_pendientes, contar_detalles_revinculables
from core.models import (
    ConteoDetalle,
    ExcelDetalle,
    ExcelDetalleEdicion,
    ExcelImportado,
    FacturaCompra,
    FacturaCompraDetalle,
    InventarioPeriodo,
    Producto,
    db,
)


class PruebasEditorExcel(unittest.TestCase):
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
        cls.app.register_blueprint(desc_bp)
        cls.ctx = cls.app.app_context()
        cls.ctx.push()
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        cls.ctx.pop()

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        self.producto = Producto(nombre="Alfajor", categoria="Impulsivo", codigo_articulo="A1")
        self.periodo = InventarioPeriodo(
            cliente_id="C-EDIT", tienda_id="T-EDIT", numero=1,
            fecha_desde="2026-08-20", fecha_hasta="2026-08-21",
            estado="Excel Importado", usuario_creador="admin",
        )
        db.session.add_all([self.producto, self.periodo])
        db.session.flush()
        self.excel = ExcelImportado(
            periodo_id=self.periodo.id, cliente_id="C-EDIT",
            nombre_archivo="oficial.xlsx", usuario_importador="admin",
            estado_validacion="ok",
        )
        db.session.add(self.excel)
        db.session.flush()
        self.detalle = ExcelDetalle(
            excel_id=self.excel.id, articulo="A1", artdescrip="Alfajor",
            producto_id=self.producto.id, producto_nombre_interno="Alfajor",
            estado_vinculacion="vinculado", stockinicial=10, compras=0,
            ventareal=2, stockfinal=8,
        )
        db.session.add_all([
            self.detalle,
            ConteoDetalle(
                periodo_id=self.periodo.id, cliente_id="C-EDIT", tienda_id="T-EDIT",
                usuario="empleado", producto_nombre="Alfajor", categoria="Impulsivo",
                total_unidad_base=13, fue_cargado=True,
            ),
        ])
        db.session.commit()
        with self.client.session_transaction() as sesion:
            sesion["rol"] = "administrador"
            sesion["usuario"] = "admin-editor"
            sesion["cliente_id"] = "C-EDIT"

    def tearDown(self):
        db.session.rollback()
        db.session.remove()

    def test_edicion_se_guarda_se_audita_y_deja_trazabilidad(self):
        respuesta = self.client.post(
            f"/admin/desc/excel/{self.excel.id}/datos",
            json={"filas": [{"id": self.detalle.id, "valores": {
                "compras": "5",
            }}]},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(respuesta.get_json()["requiere_sincronizacion"])
        self.assertEqual(respuesta.get_json()["sincronizacion"]["total"], 0)
        db.session.expire_all()
        detalle = db.session.get(ExcelDetalle, self.detalle.id)
        self.assertEqual(detalle.compras, 5)
        self.assertEqual(detalle.ventateorica, 7)
        self.assertEqual(detalle.diferencia, 5)
        edicion = ExcelDetalleEdicion.query.one()
        cambios = json.loads(edicion.cambios_json)
        self.assertEqual(edicion.usuario, "admin-editor")
        self.assertEqual(cambios["compras"], {"anterior": 0.0, "nuevo": 5.0})
        self.assertEqual(cambios["ventateorica"], {"anterior": 0.0, "nuevo": 7.0})
        self.assertEqual(cambios["diferencia"], {"anterior": 0.0, "nuevo": 5.0})

        resultados = ejecutar_auditoria(self.periodo)
        resultado = next(r for r in resultados if r.producto_nombre == "Alfajor")
        self.assertEqual(resultado.compras, 5)
        self.assertEqual(resultado.stock_esperado, 13)
        self.assertEqual(resultado.diferencia, 0)

    def test_artcosto_no_puede_guardarse_en_los_datos_extraidos(self):
        respuesta = self.client.post(
            f"/admin/desc/excel/{self.excel.id}/datos",
            json={"filas": [{"id": self.detalle.id, "valores": {
                "artcosto": "1000",
            }}]},
        )
        self.assertEqual(respuesta.status_code, 400)

    def test_renombre_extraido_activa_aviso_y_exige_revinculacion(self):
        respuesta = self.client.post(
            f"/admin/desc/excel/{self.excel.id}/datos",
            json={"filas": [{"id": self.detalle.id, "valores": {
                "artdescrip": "Alfajor renombrado",
            }}]},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.get_json()["requiere_sincronizacion"])
        self.assertEqual(respuesta.get_json()["sincronizacion"]["total"], 1)
        db.session.expire_all()
        detalle = db.session.get(ExcelDetalle, self.detalle.id)
        excel = db.session.get(ExcelImportado, self.excel.id)
        self.assertEqual(detalle.estado_vinculacion, "pendiente")
        self.assertIsNone(detalle.producto_id)
        self.assertEqual(excel.estado_validacion, "pendiente_vinculacion")
        self.assertEqual(contar_detalles_pendientes("C-EDIT"), 1)
        self.assertEqual(contar_detalles_revinculables("C-EDIT"), 1)

    def test_no_permite_editar_excel_de_otro_cliente(self):
        with self.client.session_transaction() as sesion:
            sesion["cliente_id"] = "OTRO"
        respuesta = self.client.post(
            f"/admin/desc/excel/{self.excel.id}/datos",
            json={"filas": [{"id": self.detalle.id, "valores": {"compras": 99}}]},
        )
        self.assertEqual(respuesta.status_code, 404)
        self.assertEqual(db.session.get(ExcelDetalle, self.detalle.id).compras, 0)

    def test_datos_extraidos_quedan_aislados_por_periodo(self):
        periodo_otro = InventarioPeriodo(
            cliente_id="C-EDIT", tienda_id="T-EDIT", numero=2,
            fecha_desde="2026-08-22", fecha_hasta="2026-08-23",
            estado="Excel Importado", usuario_creador="admin",
        )
        db.session.add(periodo_otro)
        db.session.flush()
        excel_otro = ExcelImportado(
            periodo_id=periodo_otro.id, cliente_id="C-EDIT",
            nombre_archivo="otro-periodo.xlsx", usuario_importador="admin",
            estado_validacion="ok",
        )
        db.session.add(excel_otro)
        db.session.flush()
        db.session.add(ExcelDetalle(
            cliente_id="C-EDIT", excel_id=excel_otro.id,
            articulo="B2", artdescrip="Producto de otro período",
            estado_vinculacion="pendiente",
        ))
        db.session.commit()

        excel, filas = _datos_extraidos_del_periodo("C-EDIT", self.periodo.id)
        self.assertEqual(excel.id, self.excel.id)
        self.assertEqual({fila.excel_id for fila in filas}, {self.excel.id})
        self.assertNotIn("Producto de otro período", {fila.artdescrip for fila in filas})

        excel, filas = _datos_extraidos_del_periodo("C-EDIT", periodo_otro.id)
        self.assertEqual(excel.id, excel_otro.id)
        self.assertEqual([fila.artdescrip for fila in filas], ["Producto de otro período"])

        excel, filas = _datos_extraidos_del_periodo("OTRO-CLIENTE", periodo_otro.id)
        self.assertIsNone(excel)
        self.assertEqual(filas, [])

    def test_detecta_conflicto_si_la_celda_cambio_en_otra_sesion(self):
        self.detalle.compras = 8
        db.session.commit()
        respuesta = self.client.post(
            f"/admin/desc/excel/{self.excel.id}/datos",
            json={"filas": [{"id": self.detalle.id, "valores": {"compras": 5},
                              "originales": {"compras": "0"}}]},
        )
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(db.session.get(ExcelDetalle, self.detalle.id).compras, 8)
        self.assertEqual(ExcelDetalleEdicion.query.count(), 0)

    def test_guardar_todas_las_lineas_pdf_persiste_fanee_y_campos_pendientes(self):
        fanee = Producto(nombre="Servilleta Fanee", categoria="Fanee")
        factura = FacturaCompra(
            periodo_id=self.periodo.id, cliente_id="C-EDIT", proveedor="Fane",
            numero_factura="001", fecha_emision=date(2026, 8, 20),
            nombre_archivo="fane.pdf", sha256="bulk-pdf-test",
            archivo_pdf=b"%PDF", metodo_extraccion="texto_pdf",
            estado="procesada", usuario_importador="admin",
        )
        db.session.add_all((fanee, factura))
        db.session.flush()
        vinculada = FacturaCompraDetalle(
            factura_id=factura.id, descripcion="Servilleta", cantidad_facturada=1,
            factor_conversion=1, estado_vinculacion="pendiente",
        )
        pendiente = FacturaCompraDetalle(
            factura_id=factura.id, descripcion="Producto desconocido", cantidad_facturada=1,
            factor_conversion=1, estado_vinculacion="pendiente",
        )
        db.session.add_all((vinculada, pendiente))
        db.session.commit()

        respuesta = self.client.post(
            "/admin/documentacion/facturas/detalles/guardar",
            data={
                "periodo_id": str(self.periodo.id),
                "detalle_ids": [str(vinculada.id), str(pendiente.id)],
                f"producto_id_{vinculada.id}": str(fanee.id),
                f"cantidad_facturada_{vinculada.id}": "3",
                f"factor_conversion_{vinculada.id}": "10",
                f"producto_id_{pendiente.id}": "",
                f"cantidad_facturada_{pendiente.id}": "4",
                f"factor_conversion_{pendiente.id}": "2",
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        db.session.expire_all()
        self.assertEqual(vinculada.producto_id, fanee.id)
        self.assertEqual(vinculada.estado_vinculacion, "vinculado")
        self.assertEqual(vinculada.compras_calculadas, 30)
        self.assertIsNone(pendiente.producto_id)
        self.assertEqual(pendiente.estado_vinculacion, "pendiente")
        self.assertEqual(pendiente.cantidad_facturada, 4)
        self.assertEqual(pendiente.factor_conversion, 2)
        self.assertEqual(pendiente.compras_calculadas, 8)


if __name__ == "__main__":
    unittest.main()
