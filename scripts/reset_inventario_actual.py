#!/usr/bin/env python3
"""Reinicia el inventario operativo sin borrar catálogo ni historial."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.reset_periodos_contables import (
    INSTANCE,
    _safe_pg_label,
    _sqlite_backup,
    configured_targets,
)


def reset_sqlite_inventory(path: Path, *, dry_run: bool, backup_dir: Path) -> dict[str, object]:
    if not path.exists():
        return {"target": str(path), "items": 0, "backup": None}
    conn = sqlite3.connect(path, timeout=30)
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='inventario_items'"
    ).fetchone()
    items = int(conn.execute("SELECT COUNT(*) FROM inventario_items").fetchone()[0]) if exists else 0
    conn.close()
    if dry_run or not exists:
        return {"target": str(path), "items": items, "backup": None}

    backup = _sqlite_backup(path, backup_dir, marker="antes_inventario")
    conn = sqlite3.connect(path, timeout=30)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM inventario_items")
        has_sequence = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
        ).fetchone()
        if has_sequence:
            conn.execute("DELETE FROM sqlite_sequence WHERE name='inventario_items'")
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("VACUUM")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"target": str(path), "items": items, "backup": backup}


def reset_postgresql_inventory(url: str, *, dry_run: bool, no_backup: bool) -> dict[str, object]:
    if not dry_run and not no_backup:
        raise RuntimeError("PostgreSQL requiere pg_dump previo o la confirmación --no-backup.")
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(url)
    with engine.begin() as conn:
        exists = "inventario_items" in set(inspect(conn).get_table_names())
        items = int(conn.execute(text("SELECT COUNT(*) FROM inventario_items")).scalar_one()) if exists else 0
        if not dry_run and exists:
            conn.execute(text("DELETE FROM inventario_items"))
    engine.dispose()
    return {"target": _safe_pg_label(url), "items": items, "backup": None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Reinicia las cantidades actuales de inventario.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()
    targets = configured_targets()
    if not targets:
        print("No hay bases configuradas.")
        return 2
    if not args.dry_run and not args.yes:
        if input("Escribe REINICIAR INVENTARIO para continuar: ").strip() != "REINICIAR INVENTARIO":
            print("Operación cancelada.")
            return 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = INSTANCE / "backups_inventario" / stamp
    total = 0
    for engine, target in targets:
        result = (
            reset_sqlite_inventory(Path(target), dry_run=args.dry_run, backup_dir=backup_dir)
            if engine == "sqlite"
            else reset_postgresql_inventory(target, dry_run=args.dry_run, no_backup=args.no_backup)
        )
        total += int(result["items"])
        action = "Se reiniciarían" if args.dry_run else "Reiniciados"
        print(f"{result['target']}: {action} {result['items']} registro(s) de inventario.")
        if result["backup"]:
            print(f"  Respaldo: {result['backup']}")
    print(f"Total de registros {'detectados' if args.dry_run else 'reiniciados'}: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
