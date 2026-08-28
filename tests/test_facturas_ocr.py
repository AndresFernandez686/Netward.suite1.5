from pathlib import Path
import ast
from datetime import date
import unittest

from flask import Flask

from core.factura_ocr import (
    FacturaError, aplicar_compras_facturas, extraer_factura, importar_factura,
)
from core.auditoria import ejecutar_auditoria
from core.models import (
    Cliente, ExcelDetalle, ExcelDetalleEdicion, ExcelImportado, FacturaCompra,
    FacturaCompraDetalle, InventarioPeriodo, Producto, ProductoPrecio, Tienda, db,
)


ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "templates" / "pdftext"


class PruebasFacturasOCR(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(cls.app)
        cls.ctx = cls.app.app_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        cls.ctx.pop()

    def setUp(self):
        db.drop_all()
        db.create_all()
        db.session.add(Cliente(id="C001", nombre="Prueba"))
        db.session.add(Tienda(id="T001", cliente_id="C001", nombre="Seminario"))
        for nombre, categoria in [
            ("Palito Crema Americana", "Impulsivo"),
            ("Palito Bombon", "Impulsivo"),
            ("Alfajor Bombon Cookies and Crema", "Impulsivo"),
            ("Cucurucho Biscoito Dulce x300", "Extras"),
            ("Cucurucho Cascao x120", "Extras"),
            ("Servilleta Grido", "Extras"),
            ("Isopor 1 kilo", "Extras"),
        ]:
            db.session.add(Producto(nombre=nombre, categoria=categoria))
        db.session.commit()

    def tearDown(self):
        db.session.rollback()

    def _periodo(self, desde="2026-08-10", hasta="2026-08-18"):
        periodo = InventarioPeriodo(
            cliente_id="C001", tienda_id="T001", numero=1,
            fecha_desde=desde, fecha_hasta=hasta, estado="Abierto",
            usuario_creador="admin",
        )
        db.session.add(periodo)
        db.session.flush()
        return periodo

    def _pdf(self, fragmento):
        archivo = next(path for path in PDF_DIR.glob("*.pdf") if fragmento.lower() in path.name.lower())
        return archivo.name, archivo.read_bytes()

    def test_extrae_los_dos_formatos_y_sus_lineas(self):
        _nombre, helacor_pdf = self._pdf("helacor")
        _nombre, fane_pdf = self._pdf("fane")
        helacor = extraer_factura(helacor_pdf)
        fane = extraer_factura(fane_pdf)
        self.assertEqual((helacor.proveedor, helacor.numero, len(helacor.lineas)),
                         ("Helacor", "001-001-0051204", 16))
        self.assertEqual((fane.proveedor, fane.numero, len(fane.lineas)),
                         ("Fane", "003-002-0044162", 13))
        self.assertEqual(helacor.fecha_emision.isoformat(), "2026-08-17")
        self.assertEqual(fane.fecha_emision.isoformat(), "2026-07-20")

    def test_factura_asignada_al_periodo_se_aplica_con_advertencia_de_fecha(self):
        periodo = self._periodo()
        nombre, contenido = self._pdf("fane")
        factura, avisos = importar_factura(
            periodo=periodo, cliente_id="C001", usuario="admin",
            nombre_archivo=nombre, contenido=contenido,
        )
        db.session.commit()
        self.assertEqual(factura.estado, "procesada")
        self.assertFalse(any(d.estado_vinculacion == "fuera_rango" for d in factura.detalles))
        self.assertTrue(any("fecha de emisión" in aviso for aviso in avisos))

    def test_factura_acepta_periodo_cerrado_y_conserva_su_asignacion(self):
        periodo = self._periodo()
        periodo.estado = "Cerrado"
        db.session.add(ExcelImportado(
            periodo_id=periodo.id,
            cliente_id="C001",
            nombre_archivo="oficial-cerrado.xlsx",
            usuario_importador="admin",
            estado_validacion="ok",
        ))
        nombre, contenido = self._pdf("fane")

        factura, _avisos = importar_factura(
            periodo=periodo,
            cliente_id="C001",
            usuario="admin",
            nombre_archivo=nombre,
            contenido=contenido,
        )
        db.session.commit()

        self.assertEqual(factura.periodo_id, periodo.id)
        self.assertEqual(factura.periodo.estado, "Cerrado")

    def test_aplica_compras_convertidas_y_registra_trazabilidad(self):
        periodo = self._periodo()
        palito = Producto.query.filter_by(nombre="Palito Crema Americana").one()
        excel = ExcelImportado(
            periodo_id=periodo.id, cliente_id="C001", nombre_archivo="inventario.xls",
            usuario_importador="admin", estado_validacion="ok",
        )
        db.session.add(excel)
        db.session.flush()
        detalle_excel = ExcelDetalle(
            excel_id=excel.id, articulo="P1", artdescrip="Palito cremoso americana x unidad",
            producto_id=palito.id, producto_nombre_interno=palito.nombre,
            estado_vinculacion="vinculado", compras=999,
        )
        db.session.add(detalle_excel)
        nombre, contenido = self._pdf("helacor")
        factura, avisos = importar_factura(
            periodo=periodo, cliente_id="C001", usuario="admin",
            nombre_archivo=nombre, contenido=contenido,
        )
        db.session.flush()
        linea = FacturaCompraDetalle.query.filter_by(
            factura_id=factura.id, producto_id=palito.id,
        ).one()
        self.assertEqual(linea.compras_calculadas, 80)
        # Esta prueba evalúa una aplicación completa de una sola línea.
        # Las demás líneas del PDF se prueban por separado como pendientes.
        for otra in list(factura.detalles):
            if otra.id != linea.id:
                db.session.delete(otra)
        db.session.flush()

        resumen = aplicar_compras_facturas(periodo, "C001", "admin")
        db.session.commit()
        self.assertEqual(resumen["cambios"], 1)
        self.assertEqual(detalle_excel.compras, 80)
        self.assertEqual(ExcelDetalleEdicion.query.count(), 1)
        self.assertIn('"origen": "facturas_pdf"', ExcelDetalleEdicion.query.one().cambios_json)
        self.assertGreater(len(avisos), 0)  # líneas sin vínculo seguro quedan para revisión

    def test_no_aplica_ninguna_compra_si_hay_lineas_incompletas(self):
        periodo = self._periodo()
        palito = Producto.query.filter_by(nombre="Palito Crema Americana").one()
        excel = ExcelImportado(
            periodo_id=periodo.id, cliente_id="C001", nombre_archivo="inventario.xls",
            usuario_importador="admin", estado_validacion="ok",
        )
        db.session.add(excel)
        db.session.flush()
        detalle_excel = ExcelDetalle(
            excel_id=excel.id, articulo="P1", artdescrip="Palito cremoso americana x unidad",
            producto_id=palito.id, producto_nombre_interno=palito.nombre,
            estado_vinculacion="vinculado", compras=999,
        )
        db.session.add(detalle_excel)
        nombre, contenido = self._pdf("helacor")
        importar_factura(
            periodo=periodo, cliente_id="C001", usuario="admin",
            nombre_archivo=nombre, contenido=contenido,
        )
        db.session.flush()

        with self.assertRaisesRegex(FacturaError, "completa y guarda"):
            aplicar_compras_facturas(periodo, "C001", "admin")

        self.assertEqual(detalle_excel.compras, 999)
        self.assertEqual(ExcelDetalleEdicion.query.count(), 0)

        with self.assertRaisesRegex(FacturaError, "completa y guarda"):
            ejecutar_auditoria(periodo)

    def test_helacor_usa_presentacion_especifica_de_cada_producto(self):
        """2 bultos de 6 unidades/caja y 6 cajas/bulto son 72, no 96."""
        periodo = self._periodo()
        cookies = Producto.query.filter_by(
            nombre="Alfajor Bombon Cookies and Crema"
        ).one()
        db.session.add(ProductoPrecio(
            cliente_id="C001", producto_id=cookies.id,
            producto_nombre=cookies.nombre, categoria=cookies.categoria,
            unidades_por_caja=6, unidades_por_bulto=6,
        ))
        nombre, contenido = self._pdf("helacor")

        factura, _avisos = importar_factura(
            periodo=periodo, cliente_id="C001", usuario="admin",
            nombre_archivo=nombre, contenido=contenido,
        )
        linea = FacturaCompraDetalle.query.filter_by(
            factura_id=factura.id, codigo_proveedor="4000833",
        ).one()

        self.assertEqual(linea.cantidad_facturada, 2)
        self.assertEqual(linea.factor_conversion, 36)
        self.assertEqual(linea.compras_calculadas, 72)
        self.assertIn("6 unidades/caja × 6 cajas/bulto", linea.observacion)

    def test_aplicar_recalcula_todos_los_productos_desde_cantidad_y_factor(self):
        """Una copia cacheada vieja no puede llegar a Auditoría ni al Excel."""
        periodo = self._periodo()
        escoces = Producto(nombre="Alfajor Bombon Escoces", categoria="Impulsivo")
        db.session.add(escoces)
        db.session.flush()
        excel = ExcelImportado(
            periodo_id=periodo.id, cliente_id="C001", nombre_archivo="inventario.xls",
            usuario_importador="admin", estado_validacion="ok",
        )
        db.session.add(excel)
        db.session.flush()
        detalle_excel = ExcelDetalle(
            excel_id=excel.id, articulo="24", artdescrip="Bombon escoces x unidad",
            producto_id=escoces.id, producto_nombre_interno=escoces.nombre,
            estado_vinculacion="vinculado", compras=240,
        )
        factura = FacturaCompra(
            periodo_id=periodo.id, cliente_id="C001", proveedor="Helacor",
            numero_factura="001-001-0051204", fecha_emision=date(2026, 8, 17),
            nombre_archivo="helacor.pdf", sha256="regresion-4-bultos",
            archivo_pdf=b"%PDF", metodo_extraccion="texto_pdf", estado="procesada",
            usuario_importador="admin",
        )
        db.session.add_all((detalle_excel, factura))
        db.session.flush()
        linea = FacturaCompraDetalle(
            factura_id=factura.id, codigo_proveedor="4000116",
            descripcion="PACK6 CAJAS BOMBON ESCOCES X8 GRIDO EXPO",
            cantidad_facturada=4, factor_conversion=48,
            # Simula el valor viejo que produjo 240 antes de corregir a 4 bultos.
            compras_calculadas=240, producto_id=escoces.id,
            producto_nombre=escoces.nombre, estado_vinculacion="vinculado",
        )
        db.session.add(linea)
        db.session.flush()

        aplicar_compras_facturas(periodo, "C001", "admin")
        db.session.flush()

        self.assertEqual(linea.compras_calculadas, 192)
        self.assertEqual(detalle_excel.compras, 192)

    def test_no_duplica_la_misma_factura_aunque_cambie_el_nombre(self):
        periodo = self._periodo()
        nombre, contenido = self._pdf("helacor")
        primera, _ = importar_factura(
            periodo=periodo, cliente_id="C001", usuario="admin",
            nombre_archivo=nombre, contenido=contenido,
        )
        db.session.commit()
        segunda, avisos = importar_factura(
            periodo=periodo, cliente_id="C001", usuario="admin",
            nombre_archivo="copia-renombrada.pdf", contenido=contenido,
        )
        self.assertIsNotNone(primera)
        self.assertIsNone(segunda)
        self.assertEqual(FacturaCompra.query.count(), 1)
        self.assertIn("duplicada", avisos[0])

    def test_facturas_distintas_se_acumulan_en_el_mismo_periodo(self):
        periodo = self._periodo()
        for fragmento in ("helacor", "fane"):
            nombre, contenido = self._pdf(fragmento)
            factura, _avisos = importar_factura(
                periodo=periodo, cliente_id="C001", usuario="admin",
                nombre_archivo=nombre, contenido=contenido,
            )
            self.assertIsNotNone(factura)
            db.session.flush()

        self.assertEqual(FacturaCompra.query.filter_by(periodo_id=periodo.id).count(), 2)

    def test_un_mismo_pdf_no_puede_quedar_en_dos_periodos(self):
        periodo_origen = self._periodo()
        nombre, contenido = self._pdf("helacor")
        factura, _avisos = importar_factura(
            periodo=periodo_origen,
            cliente_id="C001",
            usuario="admin",
            nombre_archivo=nombre,
            contenido=contenido,
        )
        db.session.commit()

        periodo_otro = InventarioPeriodo(
            cliente_id="C001",
            tienda_id="T001",
            numero=2,
            fecha_desde="2026-09-01",
            fecha_hasta="2026-09-30",
            estado="Cerrado",
            usuario_creador="admin",
        )
        db.session.add(periodo_otro)
        db.session.flush()
        repetida, avisos = importar_factura(
            periodo=periodo_otro,
            cliente_id="C001",
            usuario="admin",
            nombre_archivo="mismo-documento.pdf",
            contenido=contenido,
        )

        self.assertIsNotNone(factura)
        self.assertIsNone(repetida)
        self.assertIn(f"período #{periodo_origen.numero}", avisos[0])
        self.assertEqual(FacturaCompra.query.count(), 1)

    def test_todas_las_rutas_de_facturas_exigen_administrador(self):
        codigo = (ROOT / "core" / "inventario.py").read_text(encoding="utf-8-sig")
        funciones = {
            nodo.name: nodo for nodo in ast.walk(ast.parse(codigo))
            if isinstance(nodo, ast.FunctionDef)
        }
        for nombre in (
            "desc_facturas_importar", "desc_factura_detalle_actualizar",
            "desc_facturas_detalles_guardar",
            "desc_facturas_aplicar", "desc_factura_pdf",
            "desc_factura_descargar", "desc_factura_analisis",
        ):
            llamadas = [
                nodo for nodo in ast.walk(funciones[nombre])
                if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                and nodo.func.id == "_requiere_admin"
            ]
            self.assertTrue(llamadas, f"{nombre} debe exigir administrador")


if __name__ == "__main__":
    unittest.main()
