import io
import unittest

import openpyxl
from flask import Flask

from core.excel_importer import importar_excel
from core.inventario import _procesar_filas
from core.models import (
    ExcelDetalle,
    ExcelImportado,
    InventarioPeriodo,
    Producto,
    db,
)


CLIENTE = "TEST"
TIENDA = "TTEST"
PRODUCTO = "Helado Chocolate"
HEADERS = [
    "articulo",
    "artdescrip",
    "artcosto",
    "stockinicial",
    "compras",
    "otrosingresos",
    "otrassalidas",
    "stockfinal",
    "ventateorica",
    "ventareal",
    "diferencia",
    "importedesvio",
    "kilos",
    "unidades",
    "grupo",
    "grudescrip",
]


def crear_xlsx(headers, rows):
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.append(headers)
    for row in rows:
        hoja.append(row)
    contenido = io.BytesIO()
    libro.save(contenido)
    libro.close()
    return contenido.getvalue()


def fila_oficial(codigo="A-001", descripcion=PRODUCTO):
    return [
        codigo,
        descripcion,
        5000,
        10,
        5,
        2,
        1,
        8,
        8,
        6,
        2,
        10000,
        0,
        0,
        "Helados",
        "Helados",
    ]


class PruebasExcelOficial(unittest.TestCase):
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
        self.producto = Producto(
            nombre=PRODUCTO,
            categoria="Helados",
            visible_empleado=True,
        )
        self.periodo = InventarioPeriodo(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            numero=1,
            fecha_desde="2026-08-01",
            fecha_hasta="2026-08-08",
            dias_periodo=7,
            estado="Cerrado",
            usuario_creador="tester",
        )
        db.session.add_all([self.producto, self.periodo])
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()

    def importar(self, rows, headers=HEADERS):
        excel, advertencias = importar_excel(
            periodo_id=self.periodo.id,
            cliente_id=CLIENTE,
            usuario="tester",
            filename="oficial.xlsx",
            contenido=crear_xlsx(headers, rows),
        )
        db.session.flush()
        return excel, advertencias

    def test_importar_excel_valido_crea_cabecera_y_detalle(self):
        excel, advertencias = self.importar([fila_oficial()])

        self.assertIsNotNone(excel.id)
        self.assertEqual(excel.estado_validacion, "ok")
        self.assertEqual(excel.productos_nuevos, 0)
        self.assertEqual(advertencias, [])
        detalles = ExcelDetalle.query.filter_by(excel_id=excel.id).all()
        self.assertEqual(len(detalles), 1)
        self.assertEqual(detalles[0].articulo, "A-001")

    def test_importar_excel_con_columnas_faltantes_es_rechazado(self):
        contenido = crear_xlsx(
            ["stockinicial", "compras"],
            [[10, 5]],
        )

        with self.assertRaisesRegex(ValueError, "columnas"):
            importar_excel(
                periodo_id=self.periodo.id,
                cliente_id=CLIENTE,
                usuario="tester",
                filename="incompleto.xlsx",
                contenido=contenido,
            )

        self.assertEqual(ExcelImportado.query.count(), 0)
        self.assertEqual(ExcelDetalle.query.count(), 0)

    def test_producto_no_vinculado_deja_importacion_pendiente(self):
        excel, advertencias = self.importar([
            fila_oficial("X-999", "Producto totalmente desconocido")
        ])
        detalle = ExcelDetalle.query.filter_by(excel_id=excel.id).one()

        self.assertEqual(excel.estado_validacion, "pendiente_vinculacion")
        self.assertEqual(excel.productos_nuevos, 1)
        self.assertEqual(detalle.estado_vinculacion, "sin_producto")
        self.assertIsNone(detalle.producto_id)
        self.assertEqual(len(advertencias), 1)

    def test_vinculacion_por_nombre_exacto(self):
        excel, _ = self.importar([fila_oficial("", "  HELADO   CHOCOLATE ")])
        detalle = ExcelDetalle.query.filter_by(excel_id=excel.id).one()

        self.assertEqual(detalle.estado_vinculacion, "vinculado")
        self.assertEqual(detalle.producto_id, self.producto.id)
        self.assertEqual(detalle.producto_nombre_interno, PRODUCTO)

    def test_vinculacion_por_nombre_parcial(self):
        excel, _ = self.importar([
            fila_oficial("", "Helado Chocolate presentación 1 litro")
        ])
        detalle = ExcelDetalle.query.filter_by(excel_id=excel.id).one()

        self.assertEqual(detalle.estado_vinculacion, "vinculado")
        self.assertEqual(detalle.producto_id, self.producto.id)
        self.assertEqual(detalle.producto_nombre_interno, PRODUCTO)

    def test_vinculacion_sin_coincidencia_queda_pendiente(self):
        excel, _ = self.importar([fila_oficial("", "Salsa de frutilla especial")])
        detalle = ExcelDetalle.query.filter_by(excel_id=excel.id).one()

        self.assertEqual(excel.estado_validacion, "pendiente_vinculacion")
        self.assertEqual(detalle.estado_vinculacion, "sin_producto")
        self.assertIsNone(detalle.producto_nombre_interno)

    def procesar(self, *, venta_real_excel=6, ventas_delivery=None):
        headers = [
            "Producto",
            "Stock Inicial",
            "Compras",
            "Otros Ingresos",
            "Otras Salidas",
            "Stock Final",
            "Venta Teorica",
            "Venta Real",
            "Diferencia",
        ]
        row = [PRODUCTO, 10, 5, 2, 1, 8, 0, venta_real_excel, 0]
        ventas_map = {} if ventas_delivery is None else {
            PRODUCTO.lower(): ventas_delivery
        }
        filas, _, resumen = _procesar_filas(
            [headers, row],
            stock_map={},
            ventas_map=ventas_map,
            prev_snapshot=None,
            precios_map={},
        )
        self.assertEqual(resumen["total"], 1)
        return filas[0], resumen

    def test_calculo_venta_teorica(self):
        fila, _ = self.procesar()

        self.assertEqual(fila[6], 8)  # 10 + 5 + 2 - 8 - 1

    def test_venta_real_usa_delivery_cuando_existe(self):
        fila, resumen = self.procesar(venta_real_excel=6, ventas_delivery=4)

        self.assertEqual(fila[7], 4)
        self.assertEqual(resumen["vr_sys"], 1)

    def test_venta_real_conserva_excel_sin_delivery(self):
        fila, resumen = self.procesar(venta_real_excel=6)

        self.assertEqual(fila[7], 6)
        self.assertEqual(resumen["vr_sys"], 0)

    def test_diferencia_es_venta_teorica_menos_venta_real(self):
        fila, _ = self.procesar(venta_real_excel=6)

        self.assertEqual(fila[6], 8)
        self.assertEqual(fila[7], 6)
        self.assertEqual(fila[8], 2)


if __name__ == "__main__":
    unittest.main()
