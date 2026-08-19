import io
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import openpyxl
from flask import Flask
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from core import empleado as empleado_service
from core.auditoria import ejecutar_auditoria
from core.excel_importer import importar_excel
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


CLIENTE = "HEAVY"
TIENDA = "T-HEAVY"

HEADERS = [
    "articulo", "artdescrip", "artcosto", "stockinicial", "compras",
    "otrosingresos", "otrassalidas", "stockfinal", "ventateorica",
    "ventareal", "diferencia", "importedesvio", "kilos", "unidades",
    "grupo", "grudescrip",
]


def crear_excel(filas):
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.append(HEADERS)
    for codigo, producto, stock in filas:
        hoja.append([
            codigo, producto, 1000, stock, 0, 0, 0, stock,
            0, 0, 0, 0, 0, 0, "Pruebas", "Pruebas",
        ])
    contenido = io.BytesIO()
    libro.save(contenido)
    libro.close()
    return contenido.getvalue()


class PruebasHeavyConcurrencia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporal = tempfile.TemporaryDirectory(prefix="netward-heavy-")
        db_path = Path(cls.temporal.name) / "heavy.db"
        cls.app = Flask(__name__)
        cls.app.config.update(
            TESTING=True,
            SECRET_KEY="heavy-test",
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path.as_posix()}",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            SQLALCHEMY_ENGINE_OPTIONS={
                "connect_args": {"timeout": 10, "check_same_thread": False},
            },
        )
        db.init_app(cls.app)
        cls.contexto = cls.app.app_context()
        cls.contexto.push()
        db.create_all()
        with db.engine.begin() as conexion:
            conexion.execute(text("PRAGMA journal_mode=WAL"))
            conexion.execute(text("PRAGMA busy_timeout=10000"))

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

    def crear_periodo(self, numero, desde, hasta):
        periodo = InventarioPeriodo(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            numero=numero,
            fecha_desde=desde,
            fecha_hasta=hasta,
            dias_periodo=2,
            estado="Abierto",
            usuario_creador="heavy",
        )
        db.session.add(periodo)
        db.session.flush()
        return periodo

    def carrito(self, producto, cantidad, *, version=0, confirmar=False):
        carrito, _ = empleado_service.add_carrito_item(
            carrito=[],
            categoria="Pruebas",
            producto=producto,
            cantidad=cantidad,
            ume="Unidad",
            tipo_inventario="Diario",
            fecha="2026-08-19",
            detalle="Heavy concurrencia",
            version_esperada=version,
            confirmar_sobreescritura=confirmar,
        )
        return carrito

    def test_multiples_empleados_mismo_producto_sin_perdida_ni_doble_conteo(self):
        producto_nombre = "Producto concurrente"
        db.session.add(Producto(
            nombre=producto_nombre,
            categoria="Pruebas",
            visible_empleado=True,
        ))
        periodo = self.crear_periodo(1, "2026-08-19", "2026-08-20")
        db.session.commit()

        # Versión base sincronizada; los tres empleados competirán sobre versión 1.
        empleado_service.build_carrito_guardado(
            self.carrito(producto_nombre, 7),
            TIENDA,
            "Empleado inicial",
            cliente_id=CLIENTE,
            periodo_id=periodo.id,
        )
        propagar_conteo_a_periodo(
            tienda_id=TIENDA,
            cliente_id=CLIENTE,
            usuario="Empleado inicial",
            periodo_id=periodo.id,
        )
        empleado_service.procesar_sincronizacion(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario="Empleado inicial",
            accion="solo_enviar",
        )
        db.session.commit()

        participantes = [
            ("Empleado A", 11),
            ("Empleado B", 12),
            ("Empleado C", 13),
        ]
        barrera = threading.Barrier(len(participantes))

        def cargar_y_sincronizar(usuario, cantidad):
            inicio = time.monotonic()
            with self.app.app_context():
                try:
                    carrito = self.carrito(
                        producto_nombre,
                        cantidad,
                        version=1,
                        confirmar=True,
                    )
                    barrera.wait(timeout=5)
                    empleado_service.build_carrito_guardado(
                        carrito,
                        TIENDA,
                        usuario,
                        cliente_id=CLIENTE,
                        periodo_id=periodo.id,
                    )
                    propagar_conteo_a_periodo(
                        tienda_id=TIENDA,
                        cliente_id=CLIENTE,
                        usuario=usuario,
                        periodo_id=periodo.id,
                    )
                    empleado_service.procesar_sincronizacion(
                        cliente_id=CLIENTE,
                        tienda_id=TIENDA,
                        usuario=usuario,
                        accion="solo_enviar",
                    )
                    db.session.commit()
                    return "aplicado", usuario, cantidad, time.monotonic() - inicio
                except empleado_service.ConflictoCarga:
                    db.session.rollback()
                    return "conflicto", usuario, cantidad, time.monotonic() - inicio
                except OperationalError as exc:
                    db.session.rollback()
                    return "bloqueo", usuario, str(exc), time.monotonic() - inicio
                finally:
                    db.session.remove()

        with ThreadPoolExecutor(max_workers=3) as executor:
            futuros = [executor.submit(cargar_y_sincronizar, *p) for p in participantes]
            resultados = [f.result(timeout=20) for f in futuros]

        aplicados = [r for r in resultados if r[0] == "aplicado"]
        conflictos = [r for r in resultados if r[0] == "conflicto"]
        bloqueos = [r for r in resultados if r[0] == "bloqueo"]
        self.assertEqual(len(aplicados), 1, resultados)
        self.assertEqual(len(conflictos), 2, resultados)
        self.assertEqual(bloqueos, [], resultados)
        self.assertTrue(all(r[3] < 20 for r in resultados), resultados)

        db.session.expire_all()
        item = InventarioItem.query.filter_by(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            producto=producto_nombre,
        ).one()
        conteos = ConteoDetalle.query.filter_by(
            periodo_id=periodo.id,
            producto_nombre=producto_nombre,
        ).all()
        self.assertEqual(item.version, 2)
        self.assertEqual(item.sinc_estado, "sincronizado")
        self.assertEqual(len(conteos), 1)
        self.assertEqual(conteos[0].total_unidad_base, item.cantidad)
        self.assertEqual(conteos[0].usuario, item.usuario_ultima_carga)
        self.assertEqual(
            HistorialMovimiento.query.filter_by(producto=producto_nombre).count(),
            2,
        )

    def test_importacion_excel_y_auditoria_paralelas_no_mezclan_archivos_ni_periodos(self):
        nombres = ["Producto paralelo A", "Producto paralelo B", "Producto otro período"]
        productos = [
            Producto(nombre=nombre, categoria="Pruebas", visible_empleado=True)
            for nombre in nombres
        ]
        db.session.add_all(productos)
        periodo_a = self.crear_periodo(1, "2026-08-01", "2026-08-02")
        periodo_b = self.crear_periodo(2, "2026-08-03", "2026-08-04")
        db.session.flush()
        for nombre in nombres[:2]:
            db.session.add(ConteoDetalle(
                periodo_id=periodo_a.id,
                cliente_id=CLIENTE,
                tienda_id=TIENDA,
                usuario="Empleado A",
                producto_nombre=nombre,
                categoria="Pruebas",
                cantidad_unidad=10,
                total_unidad_base=10,
                fue_cargado=True,
            ))
        db.session.add(ConteoDetalle(
            periodo_id=periodo_b.id,
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario="Empleado B",
            producto_nombre=nombres[2],
            categoria="Pruebas",
            cantidad_unidad=5,
            total_unidad_base=5,
            fue_cargado=True,
        ))
        db.session.commit()

        excel_viejo = crear_excel([
            ("PA", nombres[0], 10),
            ("PB", nombres[1], 10),
        ])
        excel_nuevo = crear_excel([
            ("PA", nombres[0], 20),
            ("PB", nombres[1], 30),
        ])
        excel_otro = crear_excel([("PC", nombres[2], 5)])

        importar_excel(periodo_a.id, CLIENTE, "admin", "periodo-a-v1.xlsx", excel_viejo)
        importar_excel(periodo_b.id, CLIENTE, "admin", "periodo-b.xlsx", excel_otro)
        db.session.commit()
        ejecutar_auditoria(periodo_b)
        db.session.commit()
        resultado_b_antes = [
            (r.producto_nombre, r.diferencia)
            for r in AuditoriaResultado.query.filter_by(periodo_id=periodo_b.id).all()
        ]

        barrera = threading.Barrier(2)

        def importar_nuevo():
            with self.app.app_context():
                try:
                    barrera.wait(timeout=5)
                    excel, _ = importar_excel(
                        periodo_a.id,
                        CLIENTE,
                        "admin-importador",
                        "periodo-a-v2.xlsx",
                        excel_nuevo,
                    )
                    db.session.commit()
                    return "importado", excel.id
                except OperationalError as exc:
                    db.session.rollback()
                    return "bloqueo", str(exc)
                finally:
                    db.session.remove()

        def auditar_en_paralelo():
            with self.app.app_context():
                try:
                    periodo = db.session.get(InventarioPeriodo, periodo_a.id)
                    barrera.wait(timeout=5)
                    resultados = ejecutar_auditoria(periodo)
                    diferencias = {
                        r.producto_nombre: r.diferencia
                        for r in resultados
                        if r.producto_nombre in nombres[:2]
                    }
                    db.session.commit()
                    return "auditado", diferencias
                except OperationalError as exc:
                    db.session.rollback()
                    return "bloqueo", str(exc)
                finally:
                    db.session.remove()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futuro_import = executor.submit(importar_nuevo)
            futuro_audit = executor.submit(auditar_en_paralelo)
            resultado_import = futuro_import.result(timeout=20)
            resultado_audit = futuro_audit.result(timeout=20)

        self.assertEqual(resultado_import[0], "importado", resultado_import)
        self.assertEqual(resultado_audit[0], "auditado", resultado_audit)
        par_diferencias = (
            resultado_audit[1][nombres[0]],
            resultado_audit[1][nombres[1]],
        )
        self.assertIn(par_diferencias, {(0.0, 0.0), (-10.0, -20.0)})

        db.session.expire_all()
        excels_a = ExcelImportado.query.filter_by(periodo_id=periodo_a.id).order_by(
            ExcelImportado.id
        ).all()
        self.assertEqual([e.nombre_archivo for e in excels_a], ["periodo-a-v1.xlsx", "periodo-a-v2.xlsx"])
        self.assertTrue(all(len(e.detalles) == 2 for e in excels_a))
        self.assertEqual(ExcelImportado.query.filter_by(periodo_id=periodo_b.id).count(), 1)
        resultado_b_despues = [
            (r.producto_nombre, r.diferencia)
            for r in AuditoriaResultado.query.filter_by(periodo_id=periodo_b.id).all()
        ]
        self.assertEqual(resultado_b_despues, resultado_b_antes)
        self.assertEqual(ExcelDetalle.query.join(ExcelImportado).filter(
            ExcelImportado.periodo_id == periodo_a.id
        ).count(), 4)


if __name__ == "__main__":
    unittest.main()
