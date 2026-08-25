import ast
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask

from core.auditoria import ejecutar_auditoria
from core.models import (
    AjusteInventario,
    AuditoriaResultado,
    ConteoDetalle,
    ExcelDetalle,
    ExcelImportado,
    HistorialMovimiento,
    InventarioItem,
    InventarioPeriodo,
    Producto,
    db,
)
from core.admin_inventario import _inventario_agregado
from core.periodos import (
    asegurar_conteo_admin, cerrar_periodo, registrar_estado_operativo_admin,
    total_conteo_con_ajustes,
)
from core.scheduler import actualizar_estados_periodos
from core.sync_bridge import retroalimentar_periodo_desde_items


CLIENTE = "TEST"
TIENDA = "TTEST"
PRODUCTO = "Producto de prueba"


class PruebasPeriodos(unittest.TestCase):
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
        db.session.add(Producto(
            nombre=PRODUCTO,
            categoria="Pruebas",
            visible_empleado=True,
        ))
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()

    def crear_periodo(self, numero, desde, hasta, estado="Abierto"):
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

    def agregar_conteo(self, periodo, cantidad, fue_cargado=True):
        conteo = ConteoDetalle(
            periodo_id=periodo.id,
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario="tester",
            producto_nombre=PRODUCTO,
            categoria="Pruebas",
            cantidad_unidad=cantidad,
            cantidad_caja=0,
            cantidad_bulto=0,
            total_unidad_base=cantidad,
            fue_cargado=fue_cargado,
        )
        db.session.add(conteo)
        db.session.flush()
        return conteo

    def test_vista_admin_periodos_envia_mapa_de_tiendas_a_la_plantilla(self):
        """Evita el 500 de Jinja cuando la tabla muestra el nombre de tienda."""
        codigo = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
        arbol = ast.parse(codigo)
        funcion = next(
            nodo for nodo in ast.walk(arbol)
            if isinstance(nodo, ast.FunctionDef) and nodo.name == "admin_periodos"
        )
        render = next(
            nodo for nodo in ast.walk(funcion)
            if isinstance(nodo, ast.Call)
            and isinstance(nodo.func, ast.Name)
            and nodo.func.id == "render_template"
        )
        argumentos = {kw.arg for kw in render.keywords}
        self.assertIn("tiendas_map", argumentos)

    def test_detalle_periodo_envia_productos_y_categorias_a_los_buscadores(self):
        """Evita renderizar vacíos el autocompletado y selector manual."""
        codigo = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
        arbol = ast.parse(codigo)
        funcion = next(
            nodo for nodo in ast.walk(arbol)
            if isinstance(nodo, ast.FunctionDef) and nodo.name == "admin_periodo_detalle"
        )
        render = next(
            nodo for nodo in ast.walk(funcion)
            if isinstance(nodo, ast.Call)
            and isinstance(nodo.func, ast.Name)
            and nodo.func.id == "render_template"
        )
        argumentos = {kw.arg for kw in render.keywords}
        self.assertIn("productos_catalogo", argumentos)
        self.assertIn("categorias", argumentos)

    def test_vistas_del_periodo_muestran_nombre_de_tienda_y_no_su_id(self):
        codigo = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(
            encoding="utf-8"
        )
        plantilla = Path(__file__).resolve().parents[1].joinpath(
            "templates", "admin_reporte_gerencial.html"
        ).read_text(encoding="utf-8")

        self.assertIn("def _nombre_tienda_periodo", codigo)
        self.assertIn('ctx["tienda_nombre"] = _nombre_tienda_periodo(periodo)', codigo)
        self.assertIn("{{ tienda_nombre }}", plantilla)
        self.assertNotIn("{{ periodo.tienda_id }}", plantilla)
        self.assertIn("btn btn--ghost btn--sm", plantilla)

    def test_crear_periodo_sin_historial_deja_producto_pendiente(self):
        periodo = self.crear_periodo(1, "2026-08-01", "2026-08-08")

        importados = retroalimentar_periodo_desde_items(periodo)
        conteo = ConteoDetalle.query.filter_by(
            periodo_id=periodo.id,
            producto_nombre=PRODUCTO,
        ).one()

        self.assertEqual(importados, 0)
        self.assertFalse(conteo.fue_cargado)
        self.assertEqual(conteo.total_unidad_base, 0)
        self.assertEqual(periodo.estado, "Abierto")

    def test_ajuste_admin_nuevo_producto_impacta_stock_dashboard_e_historial(self):
        periodo = self.crear_periodo(1, "2026-08-01", "2026-08-08", estado="Cargado")
        conteo = asegurar_conteo_admin(
            periodo, producto_nombre=PRODUCTO, categoria="Pruebas", usuario="admin",
        )
        db.session.add(AjusteInventario(
            periodo_id=periodo.id, cliente_id=CLIENTE,
            producto_nombre=PRODUCTO, usuario_admin="admin",
            cantidad_ajustada=6, motivo="Producto encontrado luego",
            impacta_stock=True,
        ))
        db.session.flush()
        total = total_conteo_con_ajustes(periodo.id, PRODUCTO)
        registrar_estado_operativo_admin(
            periodo, producto_nombre=PRODUCTO, categoria="Pruebas",
            cantidad_final=total, usuario="admin", detalle="Ajuste administrativo",
        )
        db.session.flush()

        self.assertTrue(conteo.fue_cargado)
        self.assertEqual(total, 6)
        self.assertEqual(InventarioItem.query.filter_by(producto=PRODUCTO).one().cantidad, 6)
        self.assertEqual(HistorialMovimiento.query.filter_by(producto=PRODUCTO).one().cantidad, 6)
        self.assertEqual(_inventario_agregado(TIENDA, CLIENTE)[("Pruebas", PRODUCTO)]["cantidad"], 6)

    def test_ajuste_sin_impacto_no_se_interpreta_como_stock(self):
        periodo = self.crear_periodo(1, "2026-08-01", "2026-08-08", estado="Cargado")
        self.agregar_conteo(periodo, 5)
        db.session.add(AjusteInventario(
            periodo_id=periodo.id, cliente_id=CLIENTE,
            producto_nombre=PRODUCTO, usuario_admin="admin",
            cantidad_ajustada=3, motivo="Trazabilidad", impacta_stock=False,
        ))
        db.session.flush()

        self.assertEqual(total_conteo_con_ajustes(periodo.id, PRODUCTO), 5)
        self.assertEqual(_inventario_agregado(TIENDA, CLIENTE)[("Pruebas", PRODUCTO)]["cantidad"], 5)

    def test_crear_periodo_con_historial_importa_ultima_carga(self):
        db.session.add_all([
            HistorialMovimiento(
                cliente_id=CLIENTE,
                tienda_id=TIENDA,
                fecha="2026-08-03",
                hora="08:00",
                usuario="empleado",
                categoria="Pruebas",
                producto=PRODUCTO,
                cantidad=7,
            ),
            HistorialMovimiento(
                cliente_id=CLIENTE,
                tienda_id=TIENDA,
                fecha="2026-08-05",
                hora="09:00",
                usuario="empleado",
                categoria="Pruebas",
                producto=PRODUCTO,
                cantidad=11,
            ),
        ])
        periodo = self.crear_periodo(1, "2026-08-01", "2026-08-08")
        db.session.flush()

        importados = retroalimentar_periodo_desde_items(periodo)
        conteo = ConteoDetalle.query.filter_by(
            periodo_id=periodo.id,
            producto_nombre=PRODUCTO,
        ).one()

        self.assertEqual(importados, 1)
        self.assertTrue(conteo.fue_cargado)
        self.assertEqual(conteo.total_unidad_base, 11)
        self.assertEqual(periodo.estado, "Cargado")

    def test_cierre_falla_con_pendientes_y_pasa_con_todo_cargado(self):
        periodo = self.crear_periodo(1, "2026-08-01", "2026-08-08")
        conteo = self.agregar_conteo(periodo, 0, fue_cargado=False)

        cerrado, pendientes = cerrar_periodo(periodo)

        self.assertFalse(cerrado)
        self.assertEqual(pendientes, [PRODUCTO])
        self.assertEqual(periodo.estado, "Abierto")
        self.assertIsNone(periodo.fecha_cierre)

        conteo.fue_cargado = True
        cerrado, pendientes = cerrar_periodo(periodo)

        self.assertTrue(cerrado)
        self.assertEqual(pendientes, [])
        self.assertEqual(periodo.estado, "Cerrado")
        self.assertIsNotNone(periodo.fecha_cierre)

    def test_fecha_hasta_es_inclusiva_para_el_cierre_automatico(self):
        periodo = self.crear_periodo(1, "2026-08-20", "2026-08-21")
        db.session.commit()
        zona = ZoneInfo("America/Asuncion")

        actualizar_estados_periodos(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            ahora=datetime(2026, 8, 21, 23, 59, tzinfo=zona),
        )
        self.assertEqual(periodo.estado, "Abierto")

        actualizar_estados_periodos(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            ahora=datetime(2026, 8, 22, 0, 0, tzinfo=zona),
        )
        self.assertEqual(periodo.estado, "Cerrado")

    def test_scheduler_no_se_duplica_en_el_supervisor_de_desarrollo(self):
        codigo = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('os.environ.get("WERKZEUG_RUN_MAIN"', codigo)
        self.assertIn("_debe_iniciar_scheduler = not _modo_desarrollo or _es_proceso_reloader", codigo)
        self.assertIn("if _debe_iniciar_scheduler:", codigo)

    def preparar_continuidad(self, stock_inicial_actual):
        anterior = self.crear_periodo(
            1, "2026-08-01", "2026-08-08", estado="Cerrado"
        )
        self.agregar_conteo(anterior, 10)

        actual = self.crear_periodo(
            2, "2026-08-09", "2026-08-16", estado="Cerrado"
        )
        self.agregar_conteo(actual, 10)
        excel = ExcelImportado(
            periodo_id=actual.id,
            cliente_id=CLIENTE,
            nombre_archivo="continuidad.xlsx",
            usuario_importador="tester",
            estado_validacion="ok",
        )
        db.session.add(excel)
        db.session.flush()
        db.session.add(ExcelDetalle(
            excel_id=excel.id,
            articulo="TEST-001",
            artdescrip=PRODUCTO,
            producto_nombre_interno=PRODUCTO,
            stockinicial=stock_inicial_actual,
            stockfinal=10,
            estado_vinculacion="vinculado",
            excluido_auditoria=False,
        ))
        db.session.flush()
        return actual

    def test_continuidad_coincidente_no_genera_alerta(self):
        actual = self.preparar_continuidad(stock_inicial_actual=10)

        resultados = ejecutar_auditoria(actual)

        self.assertEqual(len(resultados), 1)
        self.assertFalse(resultados[0].alerta_continuidad)
        self.assertEqual(resultados[0].stock_inicial_anterior, 10)
        self.assertEqual(resultados[0].stock_inicial_excel, 10)

    def test_continuidad_distinta_genera_alerta(self):
        actual = self.preparar_continuidad(stock_inicial_actual=7)

        resultados = ejecutar_auditoria(actual)

        self.assertEqual(len(resultados), 1)
        self.assertTrue(resultados[0].alerta_continuidad)


if __name__ == "__main__":
    unittest.main()
