import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRACION = ROOT / "migracion"


def cargar_modulo(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, MIGRACION / archivo)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class PruebasMigracionPostgresMultiempleado(unittest.TestCase):
    def test_schema_completo_e_incremental_contienen_columnas_nuevas(self):
        completo = (MIGRACION / "01_schema_completo.sql").read_text(encoding="utf-8")
        incremental = (MIGRACION / "05_multiempleado.sql").read_text(encoding="utf-8")
        columnas = {
            "periodo_id",
            "usuario_ultima_carga",
            "version",
            "fue_sobreescrito",
            "tipo_movimiento",
            "usuario_anterior",
            "cantidad_anterior",
            "version_ultima_carga",
        }
        for columna in columnas:
            self.assertIn(columna, completo)
            self.assertIn(columna, incremental)

    def test_orden_de_datos_respeta_nuevas_claves_foraneas(self):
        modulo = cargar_modulo("migracion_datos", "migrate_sqlite_to_postgres.py")
        orden = modulo.TABLAS_ORDEN
        self.assertLess(orden.index("inventario_periodos"), orden.index("inventario_items"))
        self.assertLess(orden.index("inventario_snapshots"), orden.index("historial"))
        self.assertLess(orden.index("inventario_items"), orden.index("historial"))
        self.assertLess(orden.index("inventario_periodos"), orden.index("conteo_detalle"))

    def test_conversion_booleana_y_verificador_incluyen_multiempleado(self):
        migrador = cargar_modulo("migracion_booleanos", "migrate_sqlite_to_postgres.py")
        verificador = cargar_modulo("verificador_schema", "verificar_migracion.py")
        self.assertIn("fue_sobreescrito", migrador.BOOL_COLS["inventario_items"])
        self.assertIn("fue_sobreescrito", migrador.BOOL_COLS["conteo_detalle"])
        self.assertIn("usuario_ultima_carga", verificador.COLUMNAS_CRITICAS["inventario_items"])
        self.assertIn("tipo_movimiento", verificador.COLUMNAS_CRITICAS["historial"])
        self.assertIn("version_ultima_carga", verificador.COLUMNAS_CRITICAS["conteo_detalle"])
        self.assertIn("periodo_id", verificador.COLUMNAS_CRITICAS["delivery_ventas"])
        self.assertIn("estado_periodo", verificador.COLUMNAS_CRITICAS["delivery_ventas"])
        self.assertGreaterEqual(len(verificador.CLAVES_CRITICAS), 9)

    def test_migracion_delivery_periodos_es_idempotente(self):
        completo = (MIGRACION / "01_schema_completo.sql").read_text(encoding="utf-8")
        incremental = (MIGRACION / "06_delivery_periodos.sql").read_text(encoding="utf-8")
        indices = (MIGRACION / "03_indices_rendimiento.sql").read_text(encoding="utf-8")
        for texto in (completo, incremental):
            self.assertIn("periodo_id", texto)
            self.assertIn("estado_periodo", texto)
            self.assertIn("fk_delivery_venta_periodo", texto)
        self.assertIn("ix_delivery_ventas_periodo_estado", indices)

    def test_migracion_asistente_ia_es_trazable_e_idempotente(self):
        completo = (MIGRACION / "01_schema_completo.sql").read_text(encoding="utf-8")
        incremental = (MIGRACION / "07_asistente_ia.sql").read_text(encoding="utf-8")
        indices = (MIGRACION / "03_indices_rendimiento.sql").read_text(encoding="utf-8")
        migrador = cargar_modulo("migracion_asistente", "migrate_sqlite_to_postgres.py")
        verificador = cargar_modulo("verificador_asistente", "verificar_migracion.py")
        for texto in (completo, incremental):
            self.assertIn("asistente_ia_consultas", texto)
            self.assertIn("periodo_id", texto)
            self.assertIn("resultado_id", texto)
            self.assertIn("contexto_json", texto)
        self.assertIn("ix_asistente_ia_periodo_creado", indices)
        self.assertGreater(migrador.TABLAS_ORDEN.index("asistente_ia_consultas"),
                           migrador.TABLAS_ORDEN.index("auditoria_resultados"))
        self.assertIn("asistente_ia_consultas", verificador.TABLAS)
        self.assertGreaterEqual(len(verificador.CLAVES_CRITICAS), 9)

    def test_ediciones_excel_tienen_trazabilidad_y_orden_de_fk(self):
        completo = (MIGRACION / "01_schema_completo.sql").read_text(encoding="utf-8")
        modulo = (MIGRACION / "02_modulo_auditoria.sql").read_text(encoding="utf-8")
        incremental = (MIGRACION / "08_edicion_datos_excel.sql").read_text(encoding="utf-8")
        migrador = cargar_modulo("migracion_ediciones_excel", "migrate_sqlite_to_postgres.py")
        verificador = cargar_modulo("verificador_ediciones_excel", "verificar_migracion.py")
        for texto in (completo, modulo, incremental):
            self.assertIn("excel_detalle_ediciones", texto)
            self.assertIn("cambios_json", texto)
            self.assertIn("detalle_id", texto)
        orden = migrador.TABLAS_ORDEN
        self.assertGreater(orden.index("excel_detalle_ediciones"), orden.index("excel_detalles"))
        self.assertIn("excel_detalle_ediciones", verificador.TABLAS)
        self.assertIn("cambios_json", verificador.COLUMNAS_CRITICAS["excel_detalle_ediciones"])

    def test_facturas_pdf_tienen_schema_migracion_y_orden_de_fk(self):
        completo = (MIGRACION / "01_schema_completo.sql").read_text(encoding="utf-8")
        incremental = (MIGRACION / "12_documentacion_oficial_facturas.sql").read_text(encoding="utf-8")
        migrador = cargar_modulo("migracion_facturas", "migrate_sqlite_to_postgres.py")
        verificador = cargar_modulo("verificador_facturas", "verificar_migracion.py")
        for texto in (completo, incremental):
            self.assertIn("facturas_compra", texto)
            self.assertIn("facturas_compra_detalles", texto)
            self.assertIn("archivo_pdf", texto)
            self.assertIn("factor_conversion", texto)
        orden = migrador.TABLAS_ORDEN
        self.assertLess(orden.index("inventario_periodos"), orden.index("facturas_compra"))
        self.assertLess(orden.index("facturas_compra"), orden.index("facturas_compra_detalles"))
        self.assertIn("facturas_compra", verificador.TABLAS)
        self.assertIn("facturas_compra_detalles", verificador.TABLAS)


if __name__ == "__main__":
    unittest.main()
