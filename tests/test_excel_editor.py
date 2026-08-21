import json
import unittest

from flask import Flask

from core.auditoria import ejecutar_auditoria
from core.inventario import desc_bp
from core.models import (
    ConteoDetalle,
    ExcelDetalle,
    ExcelDetalleEdicion,
    ExcelImportado,
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
                "compras": "5", "artcosto": "1000", "artdescrip": "Alfajor editado",
            }}]},
        )
        self.assertEqual(respuesta.status_code, 200)
        db.session.expire_all()
        detalle = db.session.get(ExcelDetalle, self.detalle.id)
        self.assertEqual(detalle.compras, 5)
        self.assertEqual(detalle.artcosto, 1000)
        edicion = ExcelDetalleEdicion.query.one()
        cambios = json.loads(edicion.cambios_json)
        self.assertEqual(edicion.usuario, "admin-editor")
        self.assertEqual(cambios["compras"], {"anterior": 0.0, "nuevo": 5.0})

        resultados = ejecutar_auditoria(self.periodo)
        resultado = next(r for r in resultados if r.producto_nombre == "Alfajor")
        self.assertEqual(resultado.compras, 5)
        self.assertEqual(resultado.stock_esperado, 13)
        self.assertEqual(resultado.diferencia, 0)

    def test_no_permite_editar_excel_de_otro_cliente(self):
        with self.client.session_transaction() as sesion:
            sesion["cliente_id"] = "OTRO"
        respuesta = self.client.post(
            f"/admin/desc/excel/{self.excel.id}/datos",
            json={"filas": [{"id": self.detalle.id, "valores": {"compras": 99}}]},
        )
        self.assertEqual(respuesta.status_code, 404)
        self.assertEqual(db.session.get(ExcelDetalle, self.detalle.id).compras, 0)

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


if __name__ == "__main__":
    unittest.main()
