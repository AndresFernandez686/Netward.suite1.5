import io
import unittest
from pathlib import Path

import openpyxl
from flask import Flask

from core import empleado as empleado_service
from core.catalogo import catalogo_pendiente_usuario, get_productos_db
from core.excel_importer import (
    descartar_detalles_sin_producto,
    _safe_float, corregir_vinculaciones_empaque, contar_detalles_pendientes,
    contar_detalles_revinculables,
    importar_excel, importar_excel_transaccional,
    revincular_detalles_pendientes,
)
from core.inventario import (
    _calcular_plan_renombrado,
    _procesar_filas,
    desc_bp,
    estado_sincronizacion_catalogo,
)
from core.models import (
    ExcelDetalle,
    ExcelImportado,
    InventarioPeriodo,
    Producto,
    Usuario,
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
            SECRET_KEY="test",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(cls.app)
        cls.app.register_blueprint(desc_bp)
        cls.contexto = cls.app.app_context()
        cls.contexto.push()
        cls.client = cls.app.test_client()

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

    def test_columnas_auxiliares_se_descartan_del_excel_procesado(self):
        excel, _ = self.importar([fila_oficial()])
        detalle = ExcelDetalle.query.filter_by(excel_id=excel.id).one()

        self.assertEqual(detalle.importedesvio, 0)
        self.assertEqual(detalle.kilos, 0)
        self.assertEqual(detalle.unidades, 0)
        self.assertEqual(detalle.grupo, "")
        self.assertEqual(detalle.grudescrip, "")

    def test_depdescrip_se_usa_para_excluir_y_luego_se_descarta(self):
        headers = ["depdescrip" if h == "grudescrip" else h for h in HEADERS]
        fila = fila_oficial("X-DEP", "Producto de promoción")
        fila[-1] = "Promociones"

        excel, _ = self.importar([fila], headers=headers)
        detalle = ExcelDetalle.query.filter_by(excel_id=excel.id).one()

        self.assertTrue(detalle.excluido_auditoria)
        self.assertEqual(detalle.estado_vinculacion, "excluido")
        self.assertEqual(detalle.grudescrip, "")

    def test_importar_excel_no_cambia_el_estado_operativo_del_periodo(self):
        self.periodo.estado = "Abierto"
        db.session.commit()

        importar_excel_transaccional(
            periodo_id=self.periodo.id,
            cliente_id=CLIENTE,
            usuario="tester",
            filename="oficial.xlsx",
            contenido=crear_xlsx(HEADERS, [fila_oficial()]),
        )

        db.session.refresh(self.periodo)
        self.assertEqual(self.periodo.estado, "Abierto")

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

    def test_columnas_y_filas_reordenadas_no_cambian_los_datos(self):
        orden = [
            "diferencia", "artdescrip", "ventareal", "compras", "articulo",
            "stockfinal", "otrosingresos", "artcosto", "stockinicial",
            "otrassalidas", "ventateorica", "grupo", "grudescrip",
            "importedesvio", "kilos", "unidades",
        ]
        base = dict(zip(HEADERS, fila_oficial()))
        producto_nuevo = dict(base)
        producto_nuevo.update(articulo="NUEVO", artdescrip="Producto agregado")
        filas = [
            [producto_nuevo[c] for c in orden],
            [base[c] for c in orden],
        ]

        excel, _ = self.importar(filas, headers=orden)
        detalle = ExcelDetalle.query.filter_by(
            excel_id=excel.id,
            artdescrip=PRODUCTO,
        ).one()

        self.assertEqual(detalle.compras, 5)
        self.assertEqual(detalle.stockinicial, 10)
        self.assertEqual(detalle.stockfinal, 8)
        self.assertEqual(detalle.ventareal, 6)
        self.assertEqual(detalle.producto_id, self.producto.id)

        filas_salida, _, _ = _procesar_filas(
            [orden, *filas],
            stock_map={},
            ventas_map={},
            prev_snapshot=None,
            precios_map={},
        )
        salida = next(fila for fila in filas_salida if fila[0] == PRODUCTO)
        self.assertEqual(salida[1:9], [10, 5, 2, 1, 8, 8, 6, 2])

    def test_falta_columna_necesaria_no_se_convierte_en_cero(self):
        headers = [h for h in HEADERS if h != "compras"]
        fila = [v for h, v in zip(HEADERS, fila_oficial()) if h != "compras"]

        with self.assertRaisesRegex(ValueError, "compras"):
            self.importar([fila], headers=headers)

    def test_codigo_numerico_identifica_producto_sin_depender_de_fila(self):
        self.producto.codigo_articulo = "100"
        db.session.flush()

        excel, _ = self.importar([fila_oficial(100.0, "Nombre externo diferente")])
        detalle = ExcelDetalle.query.filter_by(excel_id=excel.id).one()

        self.assertEqual(detalle.articulo, "100")
        self.assertEqual(detalle.producto_id, self.producto.id)

    def test_nombre_generico_no_produce_vinculacion_incorrecta(self):
        chocolate = Producto(nombre="Chocolate", categoria="Helados", visible_empleado=True)
        db.session.add(chocolate)
        db.session.flush()

        excel, _ = self.importar([
            fila_oficial("F-001", "Familiar 1 litro chocolate y frutilla")
        ])
        detalle = ExcelDetalle.query.filter_by(excel_id=excel.id).one()

        self.assertEqual(detalle.estado_vinculacion, "sin_producto")
        self.assertIsNone(detalle.producto_id)

    def test_alias_oficial_identifica_nombre_distinto_del_catalogo(self):
        producto = Producto(
            nombre="Alfajor Almendrado",
            categoria="Impulsivo",
            visible_empleado=True,
        )
        db.session.add(producto)
        db.session.flush()

        excel, _ = self.importar([
            fila_oficial("38", "Almendrado x unidad")
        ])
        detalle = ExcelDetalle.query.filter_by(excel_id=excel.id).one()

        self.assertEqual(detalle.producto_id, producto.id)
        self.assertEqual(detalle.producto_nombre_interno, "Alfajor Almendrado")

    def test_numeros_localizados_se_extraen_correctamente(self):
        self.assertEqual(_safe_float("1.234,50"), 1234.5)
        self.assertEqual(_safe_float("1,234.50"), 1234.5)
        self.assertEqual(_safe_float("(25,5)"), -25.5)

    def test_excel_definitivo_conserva_compras_reales(self):
        ruta = Path(__file__).resolve().parents[1] / "templates" / "exceltest" / "andresdefinitivo.xls"
        contenido = ruta.read_bytes()

        excel, _ = importar_excel(
            periodo_id=self.periodo.id,
            cliente_id=CLIENTE,
            usuario="tester",
            filename=ruta.name,
            contenido=contenido,
        )
        db.session.flush()

        almendrado = ExcelDetalle.query.filter_by(
            excel_id=excel.id,
            artdescrip="Almendrado x unidad",
        ).one()
        compras_producto = sum(
            detalle.compras or 0
            for detalle in ExcelDetalle.query.filter_by(
                excel_id=excel.id,
                excluido_auditoria=False,
            ).all()
            if detalle.artdescrip
        )

        self.assertEqual(almendrado.compras, 48)
        self.assertEqual(almendrado.articulo, "38")
        self.assertFalse(hasattr(almendrado, "artcosto"))
        self.assertEqual(almendrado.stockinicial, 88)
        self.assertEqual(almendrado.stockfinal, 166)
        self.assertEqual(almendrado.ventateorica, -30)
        self.assertEqual(almendrado.ventareal, 83)
        self.assertEqual(almendrado.diferencia, -113)
        self.assertEqual(compras_producto, 4270)

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

    def test_descarta_sin_producto_y_deja_el_excel_listo_para_auditoria(self):
        excel, _ = self.importar([fila_oficial("", "Salsa de frutilla especial")])
        detalle = ExcelDetalle.query.filter_by(excel_id=excel.id).one()

        self.assertEqual(descartar_detalles_sin_producto(excel.id), 1)
        self.assertTrue(detalle.excluido_auditoria)
        self.assertEqual(
            detalle.motivo_exclusion,
            "Sin producto coincidente; descartado automáticamente",
        )
        self.assertEqual(excel.productos_nuevos, 0)
        self.assertEqual(excel.estado_validacion, "ok")
        self.assertEqual(contar_detalles_pendientes(CLIENTE), 0)

    def test_presentaciones_x54_y_x78_no_se_vinculan_aunque_compartan_codigo_y_alias(self):
        producto = Producto(
            nombre="Cucurucho Nacional x54",
            categoria="Extras",
            codigo_articulo="138",
        )
        db.session.add(producto)
        db.session.commit()
        excel, advertencias = self.importar([
            fila_oficial("138", "Cucuruchón nacional x 78 u")
        ])
        detalle = ExcelDetalle.query.filter_by(excel_id=excel.id).one()

        self.assertEqual(detalle.estado_vinculacion, "sin_producto")
        self.assertIsNone(detalle.producto_id)
        self.assertIsNone(detalle.producto_nombre_interno)
        self.assertIsNone(producto.codigo_articulo)
        self.assertTrue(any("empaque no coincide" in texto for texto in advertencias))

    def test_corrige_una_vinculacion_antigua_con_empaque_incompatible(self):
        producto = Producto(
            nombre="Cucurucho Nacional x54", categoria="Extras", codigo_articulo="138"
        )
        db.session.add(producto)
        db.session.flush()
        excel = ExcelImportado(
            periodo_id=self.periodo.id, cliente_id=CLIENTE,
            nombre_archivo="antiguo.xlsx", usuario_importador="admin",
            estado_validacion="ok",
        )
        db.session.add(excel)
        db.session.flush()
        detalle = ExcelDetalle(
            excel_id=excel.id, articulo="138",
            artdescrip="Cucuruchón nacional x 78 u",
            producto_id=producto.id,
            producto_nombre_interno=producto.nombre,
            estado_vinculacion="vinculado",
        )
        db.session.add(detalle)
        db.session.flush()

        self.assertEqual(corregir_vinculaciones_empaque(excel.id), 1)
        self.assertIsNone(detalle.producto_id)
        self.assertIsNone(detalle.producto_nombre_interno)
        self.assertEqual(detalle.estado_vinculacion, "pendiente")
        self.assertEqual(excel.estado_validacion, "pendiente_vinculacion")
        self.assertIsNone(producto.codigo_articulo)

    def test_producto_agregado_despues_revincula_el_excel_existente(self):
        excel, _ = self.importar([
            fila_oficial("1814", "Torta frutillas con crema")
        ])
        detalle = ExcelDetalle.query.filter_by(excel_id=excel.id).one()
        self.assertEqual(detalle.estado_vinculacion, "sin_producto")
        self.assertEqual(contar_detalles_pendientes(CLIENTE), 1)
        self.assertEqual(
            estado_sincronizacion_catalogo(CLIENTE)["revinculables"], 0
        )

        producto = Producto(nombre="Torta Frutilla", categoria="Impulsivo")
        db.session.add(producto)
        db.session.flush()
        self.assertEqual(contar_detalles_revinculables(CLIENTE), 1)
        self.assertEqual(contar_detalles_pendientes(CLIENTE), 1)
        estado = estado_sincronizacion_catalogo(CLIENTE)
        self.assertGreater(estado["total"], 0)
        self.assertEqual(estado["revinculables"], 1)
        self.assertEqual(detalle.estado_vinculacion, "sin_producto")
        self.assertEqual(revincular_detalles_pendientes(CLIENTE), 1)
        db.session.flush()

        self.assertEqual(detalle.estado_vinculacion, "vinculado")
        self.assertEqual(detalle.producto_id, producto.id)
        self.assertEqual(detalle.producto_nombre_interno, "Torta Frutilla")
        self.assertEqual(producto.codigo_articulo, "1814")
        self.assertEqual(excel.estado_validacion, "ok")
        self.assertEqual(excel.productos_nuevos, 0)
        self.assertEqual(contar_detalles_revinculables(CLIENTE), 0)
        self.assertEqual(contar_detalles_pendientes(CLIENTE), 0)
        self.assertEqual(
            estado_sincronizacion_catalogo(CLIENTE)["revinculables"], 0
        )

    def test_plan_de_sincronizacion_normaliza_el_nombre_del_catalogo(self):
        producto = Producto(nombre="TORTA FRUTILLA", categoria="Impulsivo")
        db.session.add(producto)
        db.session.flush()

        item = next(
            fila for fila in _calcular_plan_renombrado()
            if fila["de"] == "Torta Frutilla"
        )
        self.assertEqual(item["accion"], "renombrar")
        self.assertEqual(item["id"], producto.id)

        producto.nombre = "Torta frutillas con crema"
        db.session.flush()
        aplicado = next(
            fila for fila in _calcular_plan_renombrado()
            if fila["de"] == "Torta Frutilla"
        )
        self.assertEqual(aplicado["accion"], "sin_cambios")

    def test_todos_los_productos_nuevos_aparecen_y_se_publican_al_aplicar(self):
        nuevos = [
            Producto(nombre="Pizza", categoria="Extras", visible_empleado=False),
            Producto(nombre="Empanada", categoria="Extras", visible_empleado=False),
        ]
        empleado = Usuario(
            username="empleado-catalogo",
            cliente_id=CLIENTE,
            rol="empleado",
            tienda_id=TIENDA,
            catalogo_version_recibida=0,
        )
        db.session.add_all(nuevos + [empleado])
        db.session.commit()

        plan = _calcular_plan_renombrado()
        nombres_nuevos = {
            item["de"] for item in plan if item["accion"] == "nuevo_producto"
        }
        self.assertEqual(nombres_nuevos, {"Pizza", "Empanada"})
        self.assertEqual(
            [item["de"] for item in plan[:2]],
            ["Empanada", "Pizza"],
        )
        estado = estado_sincronizacion_catalogo(CLIENTE)
        self.assertEqual(estado["nuevos_productos"], 2)
        self.assertEqual(estado["total"], 2)

        with self.client.session_transaction() as sesion:
            sesion["rol"] = "administrador"
            sesion["usuario"] = "admin"
            sesion["cliente_id"] = CLIENTE
        respuesta = self.client.post("/admin/desc/sincronizar")
        self.assertEqual(respuesta.status_code, 302)

        db.session.expire_all()
        self.assertTrue(all(db.session.get(Producto, p.id).visible_empleado for p in nuevos))
        self.assertEqual(estado_sincronizacion_catalogo(CLIENTE)["total"], 0)

        catalogo_antes = get_productos_db(
            cliente_id=CLIENTE,
            username=empleado.username,
        )
        self.assertNotIn("Pizza", catalogo_antes["Extras"])
        self.assertEqual(catalogo_pendiente_usuario(CLIENTE, empleado.username), (True, 2))

        solo_envio = empleado_service.procesar_sincronizacion(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario=empleado.username,
            accion="solo_enviar",
        )
        self.assertEqual(solo_envio["catalogo_actualizado"], 0)
        self.assertTrue(catalogo_pendiente_usuario(CLIENTE, empleado.username)[0])

        recepcion = empleado_service.procesar_sincronizacion(
            cliente_id=CLIENTE,
            tienda_id=TIENDA,
            usuario=empleado.username,
            accion="enviar_recibir",
        )
        db.session.commit()
        self.assertEqual(recepcion["catalogo_actualizado"], 2)
        self.assertEqual(catalogo_pendiente_usuario(CLIENTE, empleado.username), (False, 0))
        catalogo_despues = get_productos_db(
            cliente_id=CLIENTE,
            username=empleado.username,
        )
        self.assertIn("Pizza", catalogo_despues["Extras"])
        self.assertIn("Empanada", catalogo_despues["Extras"])

    def test_producto_publicado_rescata_fila_de_un_grupo_excluido(self):
        fila_pizza = fila_oficial("158", "Pizza frizzio mozzarella")
        fila_sobre = fila_oficial("583", "Sobre pizza")
        for fila in (fila_pizza, fila_sobre):
            fila[14] = "Frizzio"
            fila[15] = "Frizzio"
        excel, _ = self.importar([fila_pizza, fila_sobre])
        detalle = ExcelDetalle.query.filter_by(
            excel_id=excel.id,
            articulo="158",
        ).one()
        self.assertTrue(detalle.excluido_auditoria)
        self.assertEqual(detalle.estado_vinculacion, "excluido")

        pizza = Producto(
            nombre="Pizza",
            categoria="Impulsivo",
            visible_empleado=False,
        )
        db.session.add(pizza)
        db.session.commit()
        with self.client.session_transaction() as sesion:
            sesion["rol"] = "administrador"
            sesion["usuario"] = "admin"
            sesion["cliente_id"] = CLIENTE
        respuesta = self.client.post("/admin/desc/sincronizar")
        self.assertEqual(respuesta.status_code, 302)

        db.session.expire_all()
        detalle = db.session.get(ExcelDetalle, detalle.id)
        pizza = db.session.get(Producto, pizza.id)
        self.assertFalse(detalle.excluido_auditoria)
        self.assertIsNone(detalle.motivo_exclusion)
        self.assertEqual(detalle.estado_vinculacion, "vinculado")
        self.assertEqual(detalle.producto_id, pizza.id)
        self.assertEqual(detalle.producto_nombre_interno, "Pizza")
        self.assertEqual(pizza.codigo_articulo, "158")
        sobre = ExcelDetalle.query.filter_by(excel_id=excel.id, articulo="583").one()
        self.assertTrue(sobre.excluido_auditoria)
        self.assertEqual(sobre.estado_vinculacion, "excluido")
        self.assertIsNone(sobre.producto_id)

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
