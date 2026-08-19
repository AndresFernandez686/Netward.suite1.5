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
        self.assertEqual(len(verificador.CLAVES_CRITICAS), 3)


if __name__ == "__main__":
    unittest.main()
