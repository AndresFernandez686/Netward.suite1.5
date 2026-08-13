"""Respalda y restaura precios de productos (SQLite, sin dependencias externas).

Uso rápido:
  1) Exportar valores actuales a archivo default:
     python scripts/restore_precios_default.py export

  2) Restaurar (sobrescribir) desde el archivo default:
     python scripts/restore_precios_default.py import --mode overwrite

  3) Restaurar solo faltantes (no pisa valores existentes):
     python scripts/restore_precios_default.py import --mode fill-missing
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FILE = os.path.join(ROOT_DIR, "scripts", "default_producto_precios.json")


def _resolve_db_path(db_arg: str | None) -> str:
    if db_arg:
        return db_arg

    uri = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_EMPLEADO") or "sqlite:///netward_empleado.db"
    if not uri.startswith("sqlite:///"):
        raise RuntimeError("Este script actualmente soporta solo SQLite (sqlite:///...).")

    rel_or_abs = uri.replace("sqlite:///", "", 1)
    if os.path.isabs(rel_or_abs):
        return rel_or_abs

    candidates = [
        os.path.join(ROOT_DIR, rel_or_abs),
        os.path.join(ROOT_DIR, "instance", rel_or_abs),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


def _to_float(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(".", "").replace(",", ".")
    return float(text) if text else None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cur.fetchall()}


def _ensure_precio_por_caja_column(conn: sqlite3.Connection):
    cols = _table_columns(conn, "producto_precios")
    if "precio_por_caja" not in cols:
        conn.execute("ALTER TABLE producto_precios ADD COLUMN precio_por_caja REAL")
        conn.commit()


def export_defaults(conn: sqlite3.Connection, output_path: str) -> int:
    _ensure_precio_por_caja_column(conn)
    rows = conn.execute(
        """
        SELECT producto_nombre, categoria, precio, precio_por_caja, unidades_por_caja, unidades_por_bulto
        FROM producto_precios
        ORDER BY categoria ASC, producto_nombre ASC
        """
    ).fetchall()

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "count": len(rows),
        "items": [
            {
                "producto_nombre": r[0],
                "categoria": r[1],
                "precio": r[2],
                "precio_por_caja": r[3],
                "unidades_por_caja": r[4],
                "unidades_por_bulto": r[5],
            }
            for r in rows
        ],
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    return len(rows)


def import_defaults(conn: sqlite3.Connection, input_path: str, mode: str) -> tuple[int, int]:
    _ensure_precio_por_caja_column(conn)

    with open(input_path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("Formato inválido: el archivo no contiene una lista de items.")

    productos_rows = conn.execute("SELECT id, nombre, categoria FROM productos").fetchall()
    productos_map = {str(row[1]).strip().lower(): (row[0], row[2]) for row in productos_rows}

    created = 0
    processed = 0

    for item in items:
        nombre = (item.get("producto_nombre") or "").strip()
        if not nombre:
            continue

        precio = _to_float(item.get("precio"))
        precio_caja = _to_float(item.get("precio_por_caja"))
        unid_caja = _to_float(item.get("unidades_por_caja"))
        unid_bulto = _to_float(item.get("unidades_por_bulto"))

        producto_info = productos_map.get(nombre.lower())
        producto_id = producto_info[0] if producto_info else None
        categoria = (item.get("categoria") or (producto_info[1] if producto_info else "Impulsivo")).strip()

        cur = conn.execute(
            "SELECT id, precio, precio_por_caja, unidades_por_caja, unidades_por_bulto, producto_id FROM producto_precios WHERE producto_nombre = ?",
            (nombre,),
        )
        existing = cur.fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO producto_precios (cliente_id, producto_nombre, producto_id, categoria, precio, precio_por_caja, unidades_por_caja, unidades_por_bulto)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("C001", nombre, producto_id, categoria, precio, precio_caja, unid_caja, unid_bulto),
            )
            created += 1
            processed += 1
            continue

        rec_id, old_precio, old_precio_caja, old_unid_caja, old_unid_bulto, old_producto_id = existing

        if mode == "fill-missing":
            new_precio = old_precio if old_precio is not None else precio
            new_precio_caja = old_precio_caja if old_precio_caja is not None else precio_caja
            new_unid_caja = old_unid_caja if old_unid_caja is not None else unid_caja
            new_unid_bulto = old_unid_bulto if old_unid_bulto is not None else unid_bulto
        else:
            new_precio = precio
            new_precio_caja = precio_caja
            new_unid_caja = unid_caja
            new_unid_bulto = unid_bulto

        new_producto_id = old_producto_id if old_producto_id is not None else producto_id
        conn.execute(
            """
            UPDATE producto_precios
            SET categoria = ?, precio = ?, precio_por_caja = ?, unidades_por_caja = ?, unidades_por_bulto = ?, producto_id = ?
            WHERE id = ?
            """,
            (categoria, new_precio, new_precio_caja, new_unid_caja, new_unid_bulto, new_producto_id, rec_id),
        )
        processed += 1

    conn.commit()
    return created, processed


def main() -> int:
    parser = argparse.ArgumentParser(description="Respaldo/restauración de precios de productos")
    parser.add_argument("action", choices=["export", "import"], help="Acción a ejecutar")
    parser.add_argument("--file", default=DEFAULT_FILE, help="Ruta del archivo JSON de respaldo")
    parser.add_argument("--db", default=None, help="Ruta al archivo SQLite (opcional)")
    parser.add_argument(
        "--mode",
        choices=["overwrite", "fill-missing"],
        default="overwrite",
        help="Modo de importación: overwrite pisa todo, fill-missing solo completa vacíos",
    )
    args = parser.parse_args()

    db_path = _resolve_db_path(args.db)
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"No se encontró la base SQLite: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        if args.action == "export":
            count = export_defaults(conn, args.file)
            print(f"OK exportado: {count} registros -> {args.file}")
            print(f"Base usada: {db_path}")
            return 0

        created, processed = import_defaults(conn, args.file, args.mode)
        print(f"OK importado ({args.mode}): creados={created}, procesados={processed} <- {args.file}")
        print(f"Base usada: {db_path}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
