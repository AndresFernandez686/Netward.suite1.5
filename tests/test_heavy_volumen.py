import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path

from flask import Flask
from sqlalchemy import text

from core import empleado as empleado_service
from core.auditoria import ejecutar_auditoria
from core.models import (
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
from core.sync_bridge import propagar_conteo_a_periodo


CLIENTE = "VOLUMEN"
TIENDA = "T-VOLUMEN"
MIB = 1024 * 1024


class PruebasHeavyVolumen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporal = tempfile.TemporaryDirectory(prefix="netward-volumen-")
        db_path = Path(cls.temporal.name) / "volumen.db"
        cls.app = Flask(__name__)
        cls.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path.as_posix()}",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            SQLALCHEMY_ENGINE_OPTIONS={"connect_args": {"timeout": 30}},
        )
        db.init_app(cls.app)
        cls.contexto = cls.app.app_context()
        cls.contexto.push()
        db.create_all()
        with db.engine.begin() as conexion:
            conexion.execute(text("PRAGMA journal_mode=WAL"))
            conexion.execute(text("PRAGMA busy_timeout=30000"))

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.engine.dispose()
        cls.contexto.pop()
        cls.temporal.cleanup()

    def setUp(self):
        db.session.remove()
        db.drop_all()
        db.create_all()

    def tearDown(self):
        db.session.rollback()
        db.session.remove()

    def crear_periodo(self, numero, fecha):
        periodo = InventarioPeriodo(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            numero=numero,
            fecha_desde=fecha,
            fecha_hasta=fecha,
            dias_periodo=1,
            estado="Abierto",
            usuario_creador="heavy",
        )
        db.session.add(periodo)
        db.session.flush()
        return periodo

    @staticmethod
    def entrada(producto, indice, fecha):
        ume, factor = (("Unidad", 1), ("Caja", 6), ("Bulto", 60))[indice % 3]
        cantidad = (indice % 5) + 1
        return {
            "categoria": "Masivo",
            "producto": producto,
            "cantidad": cantidad,
            "cantidad_unidades": cantidad * factor,
            "ume": ume,
            "factor": factor,
            "desc_conversion": f"{cantidad} {ume} = {cantidad * factor} unidades",
            "tipo_inventario": "Diario",
            "fecha": fecha,
            "detalle": "Carga masiva",
            "hora": "12:00:00",
            "version_esperada": 0,
            "confirmar_sobreescritura": False,
        }

    def test_inventario_masivo_1000_productos_tres_umes_tres_periodos(self):
        total_productos = 1000
        nombres = [f"Producto masivo {i:04d}" for i in range(total_productos)]
        db.session.bulk_insert_mappings(Producto, [
            {"nombre": nombre, "categoria": "Masivo", "visible_empleado": True}
            for nombre in nombres
        ])
        db.session.commit()

        tracemalloc.start()
        inicio = time.monotonic()
        periodos = []
        try:
            for numero, fecha in enumerate(
                ["2026-08-01", "2026-08-02", "2026-08-03"],
                start=1,
            ):
                periodo = self.crear_periodo(numero, fecha)
                db.session.commit()
                periodos.append(periodo.id)
                carrito = [
                    self.entrada(nombre, indice, fecha)
                    for indice, nombre in enumerate(nombres)
                ]
                guardados = empleado_service.build_carrito_guardado(
                    carrito,
                    TIENDA,
                    f"Empleado {numero}",
                    cliente_id=CLIENTE,
                    periodo_id=periodo.id,
                )
                propagados = propagar_conteo_a_periodo(
                    tienda_id=TIENDA,
                    cliente_id=CLIENTE,
                    usuario=f"Empleado {numero}",
                    periodo_id=periodo.id,
                )
                resumen = empleado_service.procesar_sincronizacion(
                    cliente_id=CLIENTE,
                    tienda_id=TIENDA,
                    usuario=f"Empleado {numero}",
                    accion="solo_enviar",
                )
                db.session.commit()
                self.assertEqual(guardados, total_productos)
                self.assertEqual(propagados, total_productos)
                self.assertEqual(resumen["n_inv"], total_productos)
            duracion = time.monotonic() - inicio
            _, memoria_pico = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        print(
            f"\n[HEAVY] Inventario masivo: {duracion:.2f}s, "
            f"{memoria_pico / MIB:.1f} MiB pico"
        )

        self.assertLess(duracion, 60, f"Carga masiva tardó {duracion:.2f}s")
        self.assertLess(memoria_pico, 300 * MIB, f"Pico de memoria: {memoria_pico / MIB:.1f} MiB")
        self.assertEqual(InventarioItem.query.filter_by(cliente_id=CLIENTE, tienda_id=TIENDA).count(), total_productos)
        self.assertEqual(InventarioItem.query.filter_by(sinc_estado="sincronizado").count(), total_productos)
        self.assertEqual(HistorialMovimiento.query.filter_by(cliente_id=CLIENTE).count(), total_productos * 3)
        for periodo_id in periodos:
            self.assertEqual(
                ConteoDetalle.query.filter_by(periodo_id=periodo_id, fue_cargado=True).count(),
                total_productos,
            )
            duplicados = (
                db.session.query(ConteoDetalle.producto_nombre)
                .filter_by(periodo_id=periodo_id)
                .group_by(ConteoDetalle.producto_nombre)
                .having(db.func.count(ConteoDetalle.id) > 1)
                .count()
            )
            self.assertEqual(duplicados, 0)

    def test_historial_5000_movimientos_y_500_productos_correlativos(self):
        total_productos = 500
        nombres = [f"Producto histórico {i:04d}" for i in range(total_productos)]
        db.session.bulk_insert_mappings(Producto, [
            {
                "nombre": nombre,
                "categoria": "Histórico",
                "visible_empleado": True,
                "codigo_articulo": f"H-{i:04d}",
            }
            for i, nombre in enumerate(nombres)
        ])
        db.session.commit()
        productos = Producto.query.filter(Producto.nombre.in_(nombres)).all()
        ids = {p.nombre: p.id for p in productos}

        movimientos = []
        for vuelta in range(10):
            for i, nombre in enumerate(nombres):
                movimientos.append({
                    "cliente_id": CLIENTE,
                    "fecha": f"2026-08-{(vuelta % 4) + 1:02d}",
                    "hora": f"{vuelta + 8:02d}:00:00",
                    "usuario": f"Empleado {vuelta % 3}",
                    "categoria": "Histórico",
                    "producto": nombre,
                    "cantidad": (i % 20) + vuelta,
                    "modo": ("Unidad", "Caja", "Bulto")[vuelta % 3],
                    "tipo_inventario": "Diario",
                    "detalle": "Movimiento histórico masivo",
                    "tienda_id": TIENDA,
                    "tipo_movimiento": "original" if vuelta == 0 else "sobreescritura",
                    "version": vuelta + 1,
                })
        db.session.bulk_insert_mappings(HistorialMovimiento, movimientos)

        conteos_por_periodo = [80, 120, 100, 95]
        compras_por_periodo = [0, 20, 0, 0]
        salidas_por_periodo = [0, 0, 20, 0]
        periodos = []
        for indice, conteo in enumerate(conteos_por_periodo, start=1):
            periodo = self.crear_periodo(indice, f"2026-08-{indice:02d}")
            db.session.flush()
            excel = ExcelImportado(
                periodo_id=periodo.id,
                cliente_id=CLIENTE,
                nombre_archivo=f"correlativo-{indice}.xlsx",
                usuario_importador="heavy",
                estado_validacion="ok",
            )
            db.session.add(excel)
            db.session.flush()
            db.session.bulk_insert_mappings(ConteoDetalle, [
                {
                    "periodo_id": periodo.id,
                    "cliente_id": CLIENTE,
                    "tienda_id": TIENDA,
                    "usuario": f"Empleado {indice}",
                    "producto_nombre": nombre,
                    "categoria": "Histórico",
                    "cantidad_unidad": conteo,
                    "total_unidad_base": conteo,
                    "fue_cargado": True,
                }
                for nombre in nombres
            ])
            db.session.bulk_insert_mappings(ExcelDetalle, [
                {
                    "excel_id": excel.id,
                    "articulo": f"H-{i:04d}",
                    "artdescrip": nombre,
                    "artcosto": 1000,
                    "stockinicial": 100,
                    "compras": compras_por_periodo[indice - 1],
                    "otrosingresos": 0,
                    "otrassalidas": salidas_por_periodo[indice - 1],
                    "stockfinal": conteo,
                    "ventateorica": 0,
                    "ventareal": 0,
                    "diferencia": 0,
                    "importedesvio": 0,
                    "kilos": 0,
                    "unidades": 0,
                    "grupo": "Pruebas",
                    "grudescrip": "Pruebas",
                    "producto_nombre_interno": nombre,
                    "producto_id": ids[nombre],
                    "estado_vinculacion": "vinculado",
                    "excluido_auditoria": False,
                }
                for i, nombre in enumerate(nombres)
            ])
            periodos.append(periodo)
        db.session.commit()
        self.assertEqual(HistorialMovimiento.query.count(), 5000)

        tracemalloc.start()
        inicio = time.monotonic()
        try:
            for periodo in periodos:
                resultados = ejecutar_auditoria(periodo)
                self.assertEqual(len(resultados), total_productos)
                db.session.commit()
            duracion = time.monotonic() - inicio
            _, memoria_pico = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        print(
            f"\n[HEAVY] Historial extenso: {duracion:.2f}s, "
            f"{memoria_pico / MIB:.1f} MiB pico"
        )

        self.assertLess(duracion, 60, f"Auditoría masiva tardó {duracion:.2f}s")
        self.assertLess(memoria_pico, 300 * MIB, f"Pico de memoria: {memoria_pico / MIB:.1f} MiB")
        self.assertEqual(AuditoriaResultado.query.count(), total_productos * 4)
        self.assertEqual(
            AuditoriaResultado.query.filter_by(
                periodo_id=periodos[1].id,
                tipo_diferencia="compensado",
                severidad="Correcto",
                estado_auditoria="Sin diferencia real",
            ).count(),
            total_productos,
        )
        self.assertEqual(
            AuditoriaResultado.query.filter_by(
                periodo_id=periodos[3].id,
                tipo_diferencia="faltante",
            ).count(),
            total_productos,
        )


if __name__ == "__main__":
    unittest.main()
