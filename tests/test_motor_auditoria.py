import unittest

from flask import Flask

from core.auditoria import ejecutar_auditoria
from core.models import (
    AjusteInventario,
    AuditoriaResultado,
    ConteoDetalle,
    ExcelDetalle,
    ExcelImportado,
    InventarioPeriodo,
    Producto,
    RegistroAveriado,
    RegistroVencimiento,
    db,
)


CLIENTE = "TEST"
TIENDA = "TTEST"


class PruebasMotorAuditoria(unittest.TestCase):
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

    def crear_producto(self, nombre):
        producto = Producto(
            nombre=nombre,
            categoria="Pruebas",
            visible_empleado=True,
        )
        db.session.add(producto)
        db.session.flush()
        return producto

    def crear_periodo(
        self,
        numero,
        desde="2026-08-01",
        hasta="2026-08-08",
        estado="Cerrado",
    ):
        periodo = InventarioPeriodo(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            numero=numero,
            fecha_desde=desde,
            fecha_hasta=hasta,
            dias_periodo=7,
            estado=estado,
            usuario_creador="tester",
        )
        db.session.add(periodo)
        db.session.flush()
        return periodo

    def agregar_conteo(self, periodo, producto, cantidad):
        conteo = ConteoDetalle(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario="empleado",
            producto_nombre=producto.nombre,
            categoria=producto.categoria,
            cantidad_unidad=cantidad,
            cantidad_caja=0,
            cantidad_bulto=0,
            total_unidad_base=cantidad,
            fue_cargado=True,
        )
        db.session.add(conteo)
        db.session.flush()
        return conteo

    def agregar_excel(
        self,
        periodo,
        producto,
        *,
        stock_inicial=0,
        compras=0,
        otros_ingresos=0,
        ventas=0,
        otras_salidas=0,
        stock_final=0,
        costo=None,
    ):
        excel = ExcelImportado.query.filter_by(periodo_id=periodo.id).first()
        if excel is None:
            excel = ExcelImportado(
                periodo_id=periodo.id,
                cliente_id=CLIENTE,
                nombre_archivo=f"periodo-{periodo.numero}.xlsx",
                usuario_importador="tester",
                estado_validacion="ok",
            )
            db.session.add(excel)
            db.session.flush()
        detalle = ExcelDetalle(
            excel_id=excel.id,
            articulo=f"P-{producto.id}",
            artdescrip=producto.nombre,
            artcosto=costo,
            stockinicial=stock_inicial,
            compras=compras,
            otrosingresos=otros_ingresos,
            ventareal=ventas,
            otrassalidas=otras_salidas,
            stockfinal=stock_final,
            producto_nombre_interno=producto.nombre,
            producto_id=producto.id,
            estado_vinculacion="vinculado",
            excluido_auditoria=False,
        )
        db.session.add(detalle)
        db.session.flush()
        return detalle

    def agregar_resultado_anterior(
        self,
        periodo,
        producto,
        *,
        conteo_final=10,
        diferencia=0,
        compras=0,
    ):
        resultado = AuditoriaResultado(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            producto_nombre=producto.nombre,
            categoria=producto.categoria,
            conteo_final=conteo_final,
            diferencia=diferencia,
            compras=compras,
        )
        db.session.add(resultado)
        db.session.flush()
        return resultado

    def resultado_unico(self, periodo):
        resultados = ejecutar_auditoria(periodo)
        self.assertEqual(len(resultados), 1)
        return resultados[0]

    def test_formula_stock_esperado(self):
        producto = self.crear_producto("Stock esperado")
        periodo = self.crear_periodo(1)
        self.agregar_conteo(periodo, producto, 86)
        self.agregar_excel(
            periodo,
            producto,
            stock_inicial=100,
            compras=20,
            otros_ingresos=5,
            ventas=30,
            otras_salidas=4,
            stock_final=86,
        )
        db.session.add(RegistroAveriado(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            fecha="2026-08-03",
            usuario="empleado",
            categoria="Pruebas",
            producto=producto.nombre,
            cantidad=3,
            cantidad_unidades=3,
            sinc_estado="sincronizado",
        ))
        db.session.add(RegistroVencimiento(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            fecha="2026-08-04",
            usuario="empleado",
            categoria="Pruebas",
            producto=producto.nombre,
            cantidad=2,
            cantidad_unidades=2,
            fecha_vencimiento="2026-08-10",
            sinc_estado="sincronizado",
        ))
        db.session.flush()

        resultado = self.resultado_unico(periodo)

        self.assertEqual(resultado.stock_esperado, 86)

    def test_formula_conteo_final(self):
        producto = self.crear_producto("Conteo final")
        periodo = self.crear_periodo(1)
        self.agregar_conteo(periodo, producto, 80)
        self.agregar_excel(periodo, producto, stock_inicial=85)
        db.session.add(AjusteInventario(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            producto_nombre=producto.nombre,
            usuario_admin="admin",
            cantidad_ajustada=5,
            motivo="Corrección de carga",
            impacta_stock=True,
        ))
        db.session.flush()

        resultado = self.resultado_unico(periodo)

        self.assertEqual(resultado.conteo_empleado, 80)
        self.assertEqual(resultado.ajuste_admin, 5)
        self.assertEqual(resultado.conteo_final, 85)

    def test_formula_diferencia(self):
        producto = self.crear_producto("Diferencia")
        periodo = self.crear_periodo(1)
        self.agregar_conteo(periodo, producto, 7)
        self.agregar_excel(periodo, producto, stock_inicial=10)

        resultado = self.resultado_unico(periodo)

        self.assertEqual(resultado.stock_esperado, 10)
        self.assertEqual(resultado.conteo_final, 7)
        self.assertEqual(resultado.diferencia, -3)

    def test_tipos_de_diferencia_y_regla_stock_cero(self):
        periodo = self.crear_periodo(1)
        casos = [
            ("Positiva", 10, 12, "sobrante"),
            ("Negativa", 10, 8, "faltante"),
            ("Cero", 10, 10, "correcto"),
            ("Stock esperado cero", 0, 3, "sobrante"),
        ]
        for nombre, esperado, conteo, _ in casos:
            producto = self.crear_producto(nombre)
            self.agregar_conteo(periodo, producto, conteo)
            self.agregar_excel(periodo, producto, stock_inicial=esperado)

        resultados = {
            resultado.producto_nombre: resultado
            for resultado in ejecutar_auditoria(periodo)
        }

        for nombre, _, _, tipo in casos:
            with self.subTest(nombre=nombre):
                self.assertEqual(resultados[nombre].tipo_diferencia, tipo)

    def test_limites_de_severidad(self):
        periodo = self.crear_periodo(1)
        casos = [
            ("Severidad 0", 30, "Correcto"),
            ("Severidad 5", 35, "Observación"),
            ("Severidad 20", 50, "Revisar"),
            ("Severidad 21", 51, "Crítico"),
        ]
        for nombre, conteo, _ in casos:
            producto = self.crear_producto(nombre)
            self.agregar_conteo(periodo, producto, conteo)
            self.agregar_excel(periodo, producto, stock_inicial=30)

        resultados = {
            resultado.producto_nombre: resultado
            for resultado in ejecutar_auditoria(periodo)
        }

        for nombre, _, severidad in casos:
            with self.subTest(nombre=nombre):
                self.assertEqual(resultados[nombre].severidad, severidad)

    def test_impacto_economico(self):
        producto = self.crear_producto("Impacto")
        periodo = self.crear_periodo(1)
        self.agregar_conteo(periodo, producto, 7)
        self.agregar_excel(
            periodo,
            producto,
            stock_inicial=10,
            costo=500,
        )

        resultado = self.resultado_unico(periodo)

        self.assertEqual(resultado.diferencia, -3)
        self.assertEqual(resultado.costo_unitario, 500)
        self.assertEqual(resultado.impacto, 1500)
        self.assertEqual(resultado.fuente_costo, "Excel oficial")

    def test_causa_compra_mal_cargada(self):
        producto = self.crear_producto("Compra sospechosa")
        anterior = self.crear_periodo(1)
        self.agregar_resultado_anterior(
            anterior, producto, conteo_final=10, compras=10
        )
        actual = self.crear_periodo(
            2, desde="2026-08-09", hasta="2026-08-16"
        )
        self.agregar_conteo(actual, producto, 49)
        self.agregar_excel(actual, producto, stock_inicial=10, compras=40)

        resultado = self.resultado_unico(actual)

        self.assertEqual(resultado.causa_sugerida, "Compra mal cargada")
        self.assertEqual(resultado.nivel_confianza, "Alto")

    def test_causa_error_de_conteo(self):
        producto = self.crear_producto("Error conteo")
        anterior = self.crear_periodo(1)
        self.agregar_resultado_anterior(
            anterior, producto, conteo_final=10, diferencia=10
        )
        actual = self.crear_periodo(
            2, desde="2026-08-09", hasta="2026-08-16"
        )
        self.agregar_conteo(actual, producto, 3)
        self.agregar_excel(actual, producto, stock_inicial=10)

        resultado = self.resultado_unico(actual)

        self.assertEqual(resultado.causa_sugerida, "Error de conteo")
        self.assertEqual(resultado.nivel_confianza, "Medio")
        self.assertEqual(resultado.diferencia_anterior_compensada, 10)

    def test_causa_merma(self):
        producto = self.crear_producto("Producto con merma")
        periodo = self.crear_periodo(1)
        self.agregar_conteo(periodo, producto, 4)
        self.agregar_excel(periodo, producto, stock_inicial=10)
        db.session.add(RegistroAveriado(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            fecha="2026-08-03",
            usuario="empleado",
            categoria="Pruebas",
            producto=producto.nombre,
            cantidad=3,
            cantidad_unidades=3,
            sinc_estado="sincronizado",
        ))
        db.session.flush()

        resultado = self.resultado_unico(periodo)

        self.assertEqual(resultado.causa_sugerida, "Merma o averiado")
        self.assertEqual(resultado.cantidad_merma, 3)
        self.assertEqual(resultado.nivel_confianza, "Alto")

    def test_causa_producto_vencido(self):
        producto = self.crear_producto("Producto vencido")
        periodo = self.crear_periodo(1)
        self.agregar_conteo(periodo, producto, 4)
        self.agregar_excel(periodo, producto, stock_inicial=10)
        db.session.add(RegistroVencimiento(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            fecha="2026-08-03",
            usuario="empleado",
            categoria="Pruebas",
            producto=producto.nombre,
            cantidad=3,
            cantidad_unidades=3,
            fecha_vencimiento="2026-08-10",
            sinc_estado="sincronizado",
        ))
        db.session.flush()

        resultado = self.resultado_unico(periodo)

        self.assertEqual(resultado.causa_sugerida, "Producto vencido")
        self.assertEqual(resultado.cantidad_vencida, 3)
        self.assertEqual(resultado.nivel_confianza, "Alto")

    def test_causa_inconsistencia_de_continuidad(self):
        producto = self.crear_producto("Continuidad")
        anterior = self.crear_periodo(1)
        self.agregar_resultado_anterior(anterior, producto, conteo_final=10)
        actual = self.crear_periodo(
            2, desde="2026-08-09", hasta="2026-08-16"
        )
        self.agregar_conteo(actual, producto, 9)
        self.agregar_excel(actual, producto, stock_inicial=7)

        resultado = self.resultado_unico(actual)

        self.assertTrue(resultado.alerta_continuidad)
        self.assertEqual(
            resultado.causa_sugerida,
            "Inconsistencia de continuidad",
        )
        self.assertEqual(resultado.nivel_confianza, "Alto")

    def test_sin_evidencia_queda_pendiente(self):
        producto = self.crear_producto("Sin evidencia")
        periodo = self.crear_periodo(1)
        self.agregar_conteo(periodo, producto, 9)
        self.agregar_excel(periodo, producto, stock_inicial=10)

        resultado = self.resultado_unico(periodo)

        self.assertEqual(resultado.causa_sugerida, "Pendiente de revisión")
        self.assertEqual(resultado.nivel_confianza, "Bajo")
        self.assertEqual(resultado.estado_auditoria, "Pendiente")

    def test_niveles_de_confianza_alto_medio_bajo(self):
        anterior = self.crear_periodo(1)
        actual = self.crear_periodo(
            2, desde="2026-08-09", hasta="2026-08-16"
        )
        casos = [
            ("Confianza alta", 10, 0, "Alto"),
            ("Confianza media", 10, 3, "Medio"),
            ("Confianza baja", 0, 9, "Bajo"),
        ]
        for nombre, diferencia_anterior, conteo_actual, _ in casos:
            producto = self.crear_producto(nombre)
            self.agregar_resultado_anterior(
                anterior,
                producto,
                conteo_final=10,
                diferencia=diferencia_anterior,
            )
            self.agregar_conteo(actual, producto, conteo_actual)
            self.agregar_excel(actual, producto, stock_inicial=10)

        resultados = {
            resultado.producto_nombre: resultado
            for resultado in ejecutar_auditoria(actual)
        }

        for nombre, _, _, confianza in casos:
            with self.subTest(nombre=nombre):
                self.assertEqual(resultados[nombre].nivel_confianza, confianza)

    def test_dif_anterior_sin_periodo_anterior(self):
        producto = self.crear_producto("Sin anterior")
        periodo = self.crear_periodo(1)
        self.agregar_conteo(periodo, producto, 9)
        self.agregar_excel(periodo, producto, stock_inicial=10)

        resultado = self.resultado_unico(periodo)

        self.assertEqual(resultado.diferencia_anterior_compensada, 0)

    def test_dif_anterior_con_anterior_sin_diferencia(self):
        producto = self.crear_producto("Anterior sin diferencia")
        anterior = self.crear_periodo(1)
        self.agregar_resultado_anterior(
            anterior, producto, conteo_final=10, diferencia=0
        )
        actual = self.crear_periodo(
            2, desde="2026-08-09", hasta="2026-08-16"
        )
        self.agregar_conteo(actual, producto, 9)
        self.agregar_excel(actual, producto, stock_inicial=10)

        resultado = self.resultado_unico(actual)

        self.assertEqual(resultado.diferencia_anterior_compensada, 0)

    def test_dif_anterior_con_diferencia_compensada(self):
        producto = self.crear_producto("Anterior compensado")
        anterior = self.crear_periodo(1)
        self.agregar_resultado_anterior(
            anterior, producto, conteo_final=10, diferencia=10
        )
        actual = self.crear_periodo(
            2, desde="2026-08-09", hasta="2026-08-16"
        )
        self.agregar_conteo(actual, producto, 0)
        self.agregar_excel(actual, producto, stock_inicial=10)

        resultado = self.resultado_unico(actual)

        self.assertEqual(resultado.diferencia_anterior_compensada, 10)

    def test_dif_anterior_inicializado_en_rama_sin_diferencia(self):
        producto = self.crear_producto("Inicialización segura")
        periodo = self.crear_periodo(1)
        self.agregar_conteo(periodo, producto, 10)
        self.agregar_excel(periodo, producto, stock_inicial=10)

        resultado = self.resultado_unico(periodo)

        self.assertEqual(resultado.causa_sugerida, "Sin diferencia")
        self.assertEqual(resultado.diferencia_anterior_compensada, 0)


if __name__ == "__main__":
    unittest.main()
