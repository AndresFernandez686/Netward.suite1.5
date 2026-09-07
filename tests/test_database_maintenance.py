import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlalchemy.dialects import postgresql, sqlite

from core.models import PortableJSONText
from scripts.database_maintenance import (
    backup_sqlite,
    sqlite_integrity,
    sqlite_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


class PruebasMantenimientoBaseDatos(unittest.TestCase):
    def test_json_es_texto_en_sqlite_y_jsonb_en_postgres(self):
        tipo = PortableJSONText()
        self.assertEqual(str(tipo.load_dialect_impl(sqlite.dialect())), "TEXT")
        self.assertIsInstance(
            tipo.load_dialect_impl(postgresql.dialect()), postgresql.JSONB
        )
        original = '{"origen": "facturas_pdf"}'
        self.assertEqual(tipo.process_bind_param(original, sqlite.dialect()), original)
        with self.assertRaises(ValueError):
            tipo.process_bind_param("{json invalido", sqlite.dialect())

    def test_respaldo_sqlite_conserva_filas_y_binarios(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "source.sqlite3"
            connection = sqlite3.connect(source)
            connection.execute("CREATE TABLE documentos (id INTEGER PRIMARY KEY, datos BLOB)")
            connection.execute("INSERT INTO documentos(datos) VALUES (?)", (b"PDF-prueba",))
            connection.commit()
            connection.close()

            backup = backup_sqlite(source, directory / "backups")
            self.assertEqual(sqlite_integrity(backup)["integrity"], "ok")
            self.assertEqual(sqlite_manifest(source), sqlite_manifest(backup))

    def test_configuracion_y_revision_alembic_existen(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn('app.config["SQLALCHEMY_BINDS"]', app_source)
        self.assertTrue((ROOT / "alembic.ini").is_file())
        revision = ROOT / "migrations" / "versions" / "20260827_02_indice_excel_cliente.py"
        self.assertTrue(revision.is_file())
        self.assertIn('revision = "20260827_02"', revision.read_text(encoding="utf-8"))
        head = ROOT / "migrations" / "versions" / "20260906_08_origen_confirmacion_sin_stock.py"
        self.assertTrue(head.is_file())
        self.assertIn('revision = "20260906_08"', head.read_text(encoding="utf-8"))
        self.assertIn('version != "20260906_08"', app_source)

    def test_migracion_informe_nexa_tolera_schema_inicial_completo(self):
        revision = (
            ROOT / "migrations" / "versions" / "20260904_06_informe_markdown_nexa.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_columnas_existentes", revision)
        self.assertIn("if not faltantes:", revision)
        self.assertIn("if nombre not in existentes", revision)


if __name__ == "__main__":
    unittest.main()
