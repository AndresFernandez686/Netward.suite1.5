import unittest
from datetime import datetime

from flask import Flask

from core.auditoria_estado import estado_actualizacion_auditoria, marcar_cambio_auditoria
from core.models import (
    AjusteInventario, AuditoriaResultado, ExcelDetalleEdicion, InventarioPeriodo, db,
)


class PruebasEstadoAuditoria(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(cls.app)
        cls.ctx = cls.app.app_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        cls.ctx.pop()

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()
        self.periodo = InventarioPeriodo(
            cliente_id="TEST", tienda_id="T001", numero=1,
            fecha_desde="2026-08-20", fecha_hasta="2026-08-21",
            usuario_creador="admin", estado="Cerrado",
        )
        db.session.add(self.periodo)
        db.session.commit()

    def test_sin_resultados_no_exige_re_ejecucion(self):
        estado = estado_actualizacion_auditoria(self.periodo)
        self.assertFalse(estado["ejecutada"])
        self.assertFalse(estado["desactualizada"])

    def test_edicion_excel_posterior_marca_auditoria_desactualizada(self):
        resultado = AuditoriaResultado(
            periodo_id=self.periodo.id, cliente_id="TEST", producto_nombre="Producto",
            creado=datetime(2026, 8, 21, 10, 0),
        )
        db.session.add(resultado)
        db.session.add(ExcelDetalleEdicion(
            cliente_id="TEST", periodo_id=self.periodo.id,
            excel_id=1, detalle_id=1, usuario="admin", cambios_json="{}",
            creado=datetime(2026, 8, 21, 11, 0),
        ))
        db.session.commit()

        estado = estado_actualizacion_auditoria(self.periodo)
        self.assertTrue(estado["desactualizada"])
        self.assertIn("Datos del Excel oficial modificados", estado["motivos"])

        resultado.creado = datetime(2026, 8, 21, 12, 0)
        db.session.commit()
        self.assertFalse(estado_actualizacion_auditoria(self.periodo)["desactualizada"])

    def test_cambio_pdf_y_catalogo_pendiente_exigen_re_ejecucion(self):
        db.session.add(AuditoriaResultado(
            periodo_id=self.periodo.id, cliente_id="TEST", producto_nombre="Producto",
            creado=datetime(2026, 8, 21, 10, 0),
        ))
        db.session.commit()
        marcar_cambio_auditoria(self.periodo.id, "TEST", "Líneas de facturas PDF corregidas")
        db.session.commit()

        estado = estado_actualizacion_auditoria(self.periodo, catalogo_pendiente=True)
        self.assertTrue(estado["desactualizada"])
        self.assertIn("Líneas de facturas PDF corregidas", estado["motivos"])
        self.assertTrue(any("catálogo" in motivo for motivo in estado["motivos"]))

    def test_ajuste_posterior_exige_re_ejecucion_y_luego_se_resuelve(self):
        resultado = AuditoriaResultado(
            periodo_id=self.periodo.id, cliente_id="TEST", producto_nombre="Producto",
            creado=datetime(2026, 8, 21, 10, 0),
        )
        db.session.add(resultado)
        db.session.add(AjusteInventario(
            periodo_id=self.periodo.id, cliente_id="TEST", producto_nombre="Producto",
            usuario_admin="admin", cantidad_ajustada=2, motivo="Corrección de carga",
            fecha_ajuste=datetime(2026, 8, 21, 11, 0),
        ))
        db.session.commit()

        estado = estado_actualizacion_auditoria(self.periodo)
        self.assertTrue(estado["desactualizada"])
        self.assertIn("Ajuste administrativo agregado", estado["motivos"])
        self.assertEqual(len(estado["pasos"]), 3)

        resultado.creado = datetime(2026, 8, 21, 12, 0)
        db.session.commit()
        self.assertFalse(estado_actualizacion_auditoria(self.periodo)["desactualizada"])


if __name__ == "__main__":
    unittest.main()
