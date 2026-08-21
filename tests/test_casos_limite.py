import unittest

from flask import Flask

from core.auditoria import ejecutar_auditoria
from core.models import (
    ConteoDetalle,
    DeliveryVenta,
    ExcelDetalle,
    ExcelImportado,
    InventarioItem,
    InventarioPeriodo,
    Producto,
    ProductoPrecio,
    db,
)


CLIENTE = "LIMITE"
TIENDA = "T-LIMITE"


class PruebasCasosLimite(unittest.TestCase):
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

    def crear_producto(self, nombre):
        producto = Producto(nombre=nombre, categoria="Límite", visible_empleado=True)
        db.session.add(producto)
        db.session.flush()
        return producto

    def agregar_conteo(self, periodo, producto, cantidad):
        db.session.add(ConteoDetalle(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario="empleado",
            producto_nombre=producto.nombre,
            categoria=producto.categoria,
            cantidad_unidad=cantidad,
            total_unidad_base=cantidad,
            fue_cargado=True,
        ))
        db.session.flush()

    def agregar_excel(self, periodo, producto, stock, *, costo=100, vinculado=True):
        excel = ExcelImportado(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            nombre_archivo="limites.xlsx",
            usuario_importador="tester",
            estado_validacion="ok" if vinculado else "pendiente_vinculacion",
        )
        db.session.add(excel)
        db.session.flush()
        detalle = ExcelDetalle(
            excel_id=excel.id,
            articulo="LIMIT-1",
            artdescrip=producto.nombre,
            stockinicial=stock,
            stockfinal=stock,
            producto_nombre_interno=producto.nombre if vinculado else None,
            producto_id=producto.id if vinculado else None,
            estado_vinculacion="vinculado" if vinculado else "sin_producto",
            excluido_auditoria=False,
        )
        db.session.add(detalle)
        if costo is not None:
            db.session.add(ProductoPrecio(
                cliente_id=CLIENTE,
                producto_id=producto.id,
                producto_nombre=producto.nombre,
                categoria=producto.categoria,
                precio=costo,
            ))
        db.session.flush()
        return excel

    def auditar_unico(self, periodo):
        resultados = ejecutar_auditoria(periodo)
        self.assertEqual(len(resultados), 1)
        return resultados[0]

    def test_stock_inicial_enorme_no_desborda_y_requiere_revision(self):
        producto = self.crear_producto("Stock enorme")
        periodo = self.crear_periodo()
        self.agregar_conteo(periodo, producto, 1_000_000_000_001)
        self.agregar_excel(periodo, producto, 1_000_000_000_001)

        resultado = self.auditar_unico(periodo)

        self.assertEqual(resultado.estado_auditoria, "Pendiente")
        self.assertEqual(resultado.causa_sugerida, "Pendiente de revisión")
        self.assertIn("fuera de rango", resultado.evidencia)

    def test_stock_inicial_cero_es_valido(self):
        producto = self.crear_producto("Stock cero")
        periodo = self.crear_periodo()
        self.agregar_conteo(periodo, producto, 0)
        self.agregar_excel(periodo, producto, 0)

        resultado = self.auditar_unico(periodo)

        self.assertEqual(resultado.diferencia, 0)
        self.assertEqual(resultado.estado_auditoria, "Sin diferencia")

    def test_stock_inicial_negativo_no_rompe_y_requiere_revision(self):
        producto = self.crear_producto("Stock negativo")
        periodo = self.crear_periodo()
        self.agregar_conteo(periodo, producto, 0)
        self.agregar_excel(periodo, producto, -25)

        resultado = self.auditar_unico(periodo)

        self.assertEqual(resultado.estado_auditoria, "Pendiente")
        self.assertEqual(resultado.impacto, 2500)
        self.assertIn("Posible archivo corrupto", resultado.evidencia)

    def test_producto_sin_costo_queda_pendiente_con_impacto_cero(self):
        producto = self.crear_producto("Sin costo")
        periodo = self.crear_periodo()
        self.agregar_conteo(periodo, producto, 5)
        self.agregar_excel(periodo, producto, 10, costo=None)

        resultado = self.auditar_unico(periodo)

        self.assertEqual(resultado.fuente_costo, "Sin costo")
        self.assertEqual(resultado.impacto, 0)
        self.assertEqual(resultado.estado_auditoria, "Pendiente")

    def test_producto_sin_ume_no_rompe_y_requiere_revision(self):
        producto = self.crear_producto("Sin UME")
        periodo = self.crear_periodo()
        self.agregar_conteo(periodo, producto, 10)
        self.agregar_excel(periodo, producto, 10)
        item = InventarioItem(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            periodo_id=periodo.id,
            categoria=producto.categoria,
            producto=producto.nombre,
            cantidad=10,
            ume=None,
            sinc_estado="sincronizado",
        )
        db.session.add(item)
        db.session.flush()
        # El default ORM completa "Unidad" al insertar; simulamos aquí un
        # registro legado/corrupto que quedó realmente sin UME.
        item.ume = None
        db.session.flush()

        resultado = self.auditar_unico(periodo)

        self.assertEqual(resultado.estado_auditoria, "Pendiente")
        self.assertIn("sin UME", resultado.evidencia)

    def test_producto_no_vinculado_permanece_pendiente(self):
        producto = self.crear_producto("No vinculado")
        periodo = self.crear_periodo()
        excel = self.agregar_excel(periodo, producto, 10, vinculado=False)

        resultado = self.auditar_unico(periodo)

        self.assertEqual(excel.estado_validacion, "pendiente_vinculacion")
        self.assertEqual(resultado.estado_auditoria, "Pendiente")
        self.assertIn("pendiente de vinculación", resultado.evidencia)

    def test_periodo_sin_excel_se_marca_sin_datos(self):
        producto = self.crear_producto("Sin Excel")
        periodo = self.crear_periodo()
        self.agregar_conteo(periodo, producto, 7)

        resultado = self.auditar_unico(periodo)

        self.assertEqual(resultado.estado_auditoria, "Sin datos")
        self.assertEqual(resultado.impacto, 0)
        self.assertEqual(periodo.estado, "Cerrado")

    def test_periodo_sin_inventario_se_marca_sin_datos(self):
        producto = self.crear_producto("Sin inventario")
        periodo = self.crear_periodo()
        self.agregar_excel(periodo, producto, 9)

        resultado = self.auditar_unico(periodo)

        self.assertEqual(resultado.estado_auditoria, "Sin datos")
        self.assertEqual(resultado.impacto, 0)
        self.assertEqual(periodo.estado, "Cerrado")

    def test_periodo_solo_delivery_conserva_evidencia_y_se_marca_sin_datos(self):
        periodo = self.crear_periodo()
        db.session.add(DeliveryVenta(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            fecha="2026-08-03",
            hora="12:00:00",
            producto="Solo delivery",
            cantidad=4,
            precio_unitario=1000,
            total=4000,
            usuario="empleado",
        ))
        db.session.flush()

        resultado = self.auditar_unico(periodo)

        self.assertEqual(resultado.ventas_delivery, 4)
        self.assertEqual(resultado.estado_auditoria, "Sin datos")
        self.assertEqual(resultado.impacto, 0)
        self.assertIn("Inventario oficial", resultado.evidencia)


if __name__ == "__main__":
    unittest.main()
