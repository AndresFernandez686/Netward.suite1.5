import unittest
from unittest.mock import patch

from flask import Flask

from core.excel_importer import importar_excel_transaccional
from core.models import (
    ConteoDetalle,
    ExcelDetalle,
    ExcelImportado,
    InventarioItem,
    InventarioPeriodo,
    Producto,
    SincronizacionLog,
    db,
)
from core.sync_bridge import sincronizar_transaccional


CLIENTE = "TX"
TIENDA = "T-TX"
USUARIO = "empleado-tx"


class PruebasIntegridadTransaccional(unittest.TestCase):
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

    def tearDown(self):
        db.session.rollback()
        db.session.remove()

    def crear_periodo(self):
        periodo = InventarioPeriodo(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            numero=1,
            fecha_desde="2026-08-19",
            fecha_hasta="2026-08-20",
            dias_periodo=2,
            estado="Abierto",
            usuario_creador="tester",
        )
        db.session.add(periodo)
        db.session.flush()
        return periodo

    def test_fallo_intermedio_de_sincronizacion_revierte_todo(self):
        periodo = self.crear_periodo()
        for indice in range(2):
            db.session.add(InventarioItem(
                cliente_id=CLIENTE,
                tienda_id=TIENDA,
                periodo_id=periodo.id,
                categoria="Transacción",
                producto=f"Producto TX {indice}",
                cantidad=indice + 1,
                ume="Unidad",
                sinc_estado="pendiente",
                usuario_ultima_carga=USUARIO,
            ))
        db.session.commit()
        periodo_id = periodo.id

        def simular_fallo_db(_resumen):
            raise RuntimeError("fallo simulado antes del commit")

        with self.assertRaisesRegex(RuntimeError, "fallo simulado"):
            sincronizar_transaccional(
                cliente_id=CLIENTE,
                tienda_id=TIENDA,
                usuario=USUARIO,
                accion="solo_enviar",
                periodo=periodo,
                antes_commit=simular_fallo_db,
            )

        self.assertEqual(ConteoDetalle.query.filter_by(periodo_id=periodo_id).count(), 0)
        self.assertEqual(InventarioItem.query.filter_by(sinc_estado="pendiente").count(), 2)
        self.assertEqual(InventarioItem.query.filter_by(sinc_estado="sincronizado").count(), 0)
        self.assertEqual(SincronizacionLog.query.count(), 0)
        self.assertEqual(db.session.get(InventarioPeriodo, periodo_id).estado, "Abierto")

    def test_error_intermedio_excel_deja_solo_cabecera_fallida(self):
        periodo = self.crear_periodo()
        productos = [
            Producto(nombre=f"Producto Excel {i}", categoria="Transacción", visible_empleado=True)
            for i in range(3)
        ]
        db.session.add_all(productos)
        db.session.commit()
        periodo_id = periodo.id
        filas = [
            ["articulo", "artdescrip", "stockinicial", "stockfinal"],
            ["TX-1", "Producto Excel 0", 10, 10],
            ["TX-2", "Producto Excel 1", 20, 20],
            ["TX-3", "Producto Excel 2", 30, 30],
        ]
        agregar_real = db.session.add
        detalles_agregados = 0

        def agregar_con_fallo(obj):
            nonlocal detalles_agregados
            agregar_real(obj)
            if isinstance(obj, ExcelDetalle):
                detalles_agregados += 1
                if detalles_agregados == 2:
                    raise RuntimeError("fallo simulado en fila 2")

        with patch("core.excel_importer._leer_excel", return_value=filas), patch.object(
            db.session,
            "add",
            side_effect=agregar_con_fallo,
        ):
            with self.assertRaisesRegex(RuntimeError, "fila 2"):
                importar_excel_transaccional(
                    periodo_id=periodo_id,
                    cliente_id=CLIENTE,
                    usuario="admin",
                    filename="fallo-intermedio.xlsx",
                    contenido=b"contenido simulado",
                )

        importaciones = ExcelImportado.query.all()
        self.assertEqual(len(importaciones), 1)
        self.assertEqual(importaciones[0].estado_validacion, "fallido")
        self.assertEqual(importaciones[0].nombre_archivo, "fallo-intermedio.xlsx")
        self.assertEqual(ExcelDetalle.query.count(), 0)
        self.assertEqual(db.session.get(InventarioPeriodo, periodo_id).estado, "Abierto")
        self.assertTrue(all(producto.codigo_articulo is None for producto in Producto.query.all()))


if __name__ == "__main__":
    unittest.main()
