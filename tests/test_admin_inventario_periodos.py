import unittest

from flask import Flask

from core.admin_inventario import _inventario_agregado, build_admin_inventory_context
from core.models import ConteoDetalle, InventarioPeriodo, Producto, Tienda, db


class PruebasInventarioAdminPorPeriodo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(cls.app)
        for endpoint in ("admin_inventario", "admin_vencimientos", "admin_historial"):
            cls.app.add_url_rule(f"/{endpoint}", endpoint, lambda: "")
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
        db.session.add(Producto(nombre="Alfajor", categoria="Impulsivo", visible_empleado=True))
        db.session.add_all([
            Tienda(id="T1", cliente_id="C1", nombre="Uno", activa=True),
            Tienda(id="T2", cliente_id="C1", nombre="Dos", activa=True),
        ])
        db.session.commit()

    def periodo(self, tienda, numero, estado, cantidad=None, cliente="C1"):
        periodo = InventarioPeriodo(
            cliente_id=cliente, tienda_id=tienda, numero=numero,
            fecha_desde="2026-08-01", fecha_hasta="2026-08-02",
            estado=estado, usuario_creador="admin",
        )
        db.session.add(periodo)
        db.session.flush()
        if cantidad is not None:
            db.session.add(ConteoDetalle(
                periodo_id=periodo.id, cliente_id=cliente, tienda_id=tienda,
                usuario="empleado", producto_nombre="Alfajor", categoria="Impulsivo",
                total_unidad_base=cantidad, cantidad_unidad=cantidad, fue_cargado=True,
            ))
        db.session.commit()
        return periodo

    def test_usa_ultimo_periodo_cargado_e_ignora_un_periodo_abierto(self):
        self.periodo("T1", 1, "Cerrado", 7)
        self.periodo("T1", 2, "Abierto")
        inventario = _inventario_agregado("T1", "C1")
        self.assertEqual(inventario[("Impulsivo", "Alfajor")]["cantidad"], 7)

    def test_nuevo_periodo_cargado_reemplaza_al_anterior_incluso_con_cero(self):
        self.periodo("T1", 1, "Cerrado", 7)
        self.periodo("T1", 2, "Cargado", 0)
        inventario = _inventario_agregado("T1", "C1")
        self.assertEqual(inventario[("Impulsivo", "Alfajor")]["cantidad"], 0)
        self.assertTrue(inventario[("Impulsivo", "Alfajor")]["cargado"])

        with self.app.test_request_context():
            context = build_admin_inventory_context(
                cliente_id="C1", tiendas=Tienda.query.filter_by(cliente_id="C1").all(),
                tienda_id="T1", categoria_filtro="Todas", busqueda="",
                estado_filtro="Todos", alerta_filtro="Todos",
            )
        self.assertEqual(context["resumen"]["Impulsivo"]["cargados"], 1)

    def test_todas_las_tiendas_suma_el_ultimo_periodo_de_cada_una_y_aisla_cliente(self):
        self.periodo("T1", 1, "Cargado", 5)
        self.periodo("T2", 1, "Cerrado", 3)
        self.periodo("T1", 99, "Auditado", 100, cliente="OTRO")
        inventario = _inventario_agregado("ALL", "C1")
        self.assertEqual(inventario[("Impulsivo", "Alfajor")]["cantidad"], 8)


if __name__ == "__main__":
    unittest.main()
