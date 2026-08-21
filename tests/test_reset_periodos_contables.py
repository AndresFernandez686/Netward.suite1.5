import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.reset_periodos_contables import reset_sqlite
from scripts.reset_inventario_actual import reset_sqlite_inventory


class PruebasResetPeriodosContables(unittest.TestCase):
    def test_borra_periodos_y_dependencias_pero_conserva_maestros_y_movimientos(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "prueba.db"
            conn = sqlite3.connect(db_path)
            conn.executescript("""
                CREATE TABLE clientes(id TEXT PRIMARY KEY);
                CREATE TABLE productos(id INTEGER PRIMARY KEY, nombre TEXT);
                CREATE TABLE inventario_periodos(id INTEGER PRIMARY KEY AUTOINCREMENT);
                CREATE TABLE conteo_detalle(id INTEGER PRIMARY KEY AUTOINCREMENT, periodo_id INTEGER);
                CREATE TABLE auditoria_resultados(id INTEGER PRIMARY KEY AUTOINCREMENT, periodo_id INTEGER);
                CREATE TABLE justificaciones(id INTEGER PRIMARY KEY AUTOINCREMENT, resultado_id INTEGER);
                CREATE TABLE inventario_items(id INTEGER PRIMARY KEY, periodo_id INTEGER, cantidad REAL);
                CREATE TABLE historial(id INTEGER PRIMARY KEY, periodo_id INTEGER, producto TEXT);
                CREATE TABLE delivery_ventas(id INTEGER PRIMARY KEY, periodo_id INTEGER, estado_periodo TEXT);
                INSERT INTO clientes VALUES ('C001');
                INSERT INTO productos VALUES (1, 'Producto');
                INSERT INTO inventario_periodos DEFAULT VALUES;
                INSERT INTO conteo_detalle(periodo_id) VALUES (1);
                INSERT INTO auditoria_resultados(periodo_id) VALUES (1);
                INSERT INTO justificaciones(resultado_id) VALUES (1);
                INSERT INTO inventario_items VALUES (1, 1, 7);
                INSERT INTO historial VALUES (1, 1, 'Producto');
                INSERT INTO delivery_ventas VALUES (1, 1, 'en_rango');
            """)
            conn.commit()
            conn.close()

            result = reset_sqlite(db_path, dry_run=False, backup_dir=root / "backups")

            conn = sqlite3.connect(db_path)
            self.assertEqual(result["periodos"], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM inventario_periodos").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM conteo_detalle").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM auditoria_resultados").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM justificaciones").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT cantidad, periodo_id FROM inventario_items").fetchone(), (7.0, None))
            self.assertEqual(conn.execute("SELECT producto, periodo_id FROM historial").fetchone(), ("Producto", None))
            self.assertEqual(conn.execute("SELECT periodo_id, estado_periodo FROM delivery_ventas").fetchone(), (None, "sin_periodo"))
            conn.close()
            self.assertTrue(Path(result["backup"]).exists())

    def test_reinicia_inventario_actual_sin_borrar_productos_ni_historial(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "inventario.db"
            conn = sqlite3.connect(db_path)
            conn.executescript("""
                CREATE TABLE productos(id INTEGER PRIMARY KEY, nombre TEXT);
                CREATE TABLE historial(id INTEGER PRIMARY KEY, producto TEXT);
                CREATE TABLE inventario_items(id INTEGER PRIMARY KEY AUTOINCREMENT, producto TEXT, cantidad REAL);
                INSERT INTO productos VALUES (1, 'Producto');
                INSERT INTO historial VALUES (1, 'Producto');
                INSERT INTO inventario_items(producto, cantidad) VALUES ('Producto', 31);
            """)
            conn.commit()
            conn.close()

            result = reset_sqlite_inventory(
                db_path, dry_run=False, backup_dir=root / "backups_inventario"
            )

            conn = sqlite3.connect(db_path)
            self.assertEqual(result["items"], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM inventario_items").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM historial").fetchone()[0], 1)
            conn.close()
            self.assertTrue(Path(result["backup"]).exists())


if __name__ == "__main__":
    unittest.main()
