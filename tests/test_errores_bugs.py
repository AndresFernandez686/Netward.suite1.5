import io
import unittest

import openpyxl
from flask import Flask

from core.auditoria import ejecutar_auditoria
from core.excel_importer import importar_excel
from core.models import (
    ConteoDetalle,
    ExcelDetalle,
    InventarioPeriodo,
    Producto,
    db,
)


CLIENTE = "TEST"
TIENDA = "TTEST"


def xlsx_producto_desconocido():
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.append([
        "articulo", "artdescrip", "stockinicial", "compras",
        "otrosingresos", "otrassalidas", "stockfinal", "ventareal",
    ])
    hoja.append(["X-404", "Producto inexistente", 10, 7, 2, 1, 17, 1])
    stream = io.BytesIO()
    libro.save(stream)
    libro.close()
    return stream.getvalue()


class PruebasErroresBugs(unittest.TestCase):
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
            fecha_desde="2026-08-01",
            fecha_hasta="2026-08-08",
            dias_periodo=7,
            estado="Cerrado",
            usuario_creador="tester",
        )
        db.session.add(periodo)
        db.session.flush()
        return periodo

    def agregar_producto_y_conteo(self, periodo, nombre, cantidad):
        producto = Producto(
            nombre=nombre,
            categoria="Pruebas",
            visible_empleado=True,
        )
        db.session.add(producto)
        db.session.flush()
        db.session.add(ConteoDetalle(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario="empleado",
            producto_nombre=nombre,
            categoria="Pruebas",
            cantidad_unidad=cantidad,
            cantidad_caja=0,
            cantidad_bulto=0,
            total_unidad_base=cantidad,
            fue_cargado=True,
        ))
        db.session.flush()
        return producto

    def test_dif_anterior_sin_periodo_previo_no_explota(self):
        periodo = self.crear_periodo()
        self.agregar_producto_y_conteo(periodo, "Sin período previo", 5)

        resultados = ejecutar_auditoria(periodo)

        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0].diferencia_anterior_compensada, 0)

    def test_producto_sin_precio_tiene_impacto_cero(self):
        periodo = self.crear_periodo()
        self.agregar_producto_y_conteo(periodo, "Sin precio", 5)

        resultados = ejecutar_auditoria(periodo)

        self.assertEqual(len(resultados), 1)
        resultado = resultados[0]
        self.assertEqual(resultado.diferencia, 5)
        self.assertIsNone(resultado.costo_unitario)
        self.assertEqual(resultado.impacto, 0)
        self.assertEqual(resultado.fuente_costo, "Sin costo")

    def test_producto_no_vinculado_deja_excel_pendiente(self):
        periodo = self.crear_periodo()

        excel, advertencias = importar_excel(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            usuario="tester",
            filename="producto-desconocido.xlsx",
            contenido=xlsx_producto_desconocido(),
        )
        db.session.flush()
        detalle = ExcelDetalle.query.filter_by(excel_id=excel.id).one()

        self.assertEqual(excel.estado_validacion, "pendiente_vinculacion")
        self.assertEqual(excel.productos_nuevos, 1)
        self.assertEqual(detalle.estado_vinculacion, "sin_producto")
        self.assertIsNone(detalle.producto_id)
        self.assertEqual(len(advertencias), 1)

        resultados = ejecutar_auditoria(periodo)
        resultado = next(r for r in resultados if r.producto_nombre == "Producto inexistente")
        self.assertEqual(resultado.stock_inicial_excel, 10)
        self.assertEqual(resultado.compras, 7)
        self.assertEqual(resultado.otros_ingresos, 2)
        self.assertEqual(resultado.otras_salidas, 1)
        self.assertEqual(resultado.ventas, 1)
        self.assertEqual(resultado.stock_final_excel, 17)
        self.assertEqual(resultado.estado_auditoria, "Pendiente")


if __name__ == "__main__":
    unittest.main()
