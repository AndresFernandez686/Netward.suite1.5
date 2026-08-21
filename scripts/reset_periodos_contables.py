#!/usr/bin/env python3
"""Elimina períodos contables y sus datos dependientes sin borrar maestros.

Uso:
    python scripts/reset_periodos_contables.py --dry-run
    python scripts/reset_periodos_contables.py --yes

Por seguridad, las bases SQLite deben estar dentro del proyecto y se respaldan
antes de modificarse. En PostgreSQL se requiere un respaldo externo o la opción
explícita --no-backup.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlparse

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
INSTANCE = ROOT / "instance"
ENV_KEYS = ("DATABASE_URL", "DATABASE_URL_EMPLEADO", "DATABASE_URL_ADMIN")

# Tablas compuestas exclusivamente por datos de períodos. El orden respeta FK.
PERIOD_TABLES_DELETE_ORDER = (
    "asistente_ia_consultas",
    "justificaciones",
    "auditoria_resultados",
    "facturas_compra_detalles",
    "facturas_compra",
    "excel_detalle_ediciones",
    "excel_detalles",
    "excel_importados",
    "ajustes_inventario",
    "conteo_detalle",
    "inventario_borradores",
)


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _sqlite_path(url: str) -> Path:
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError("La URL no es SQLite.")
    raw = url[len(prefix):].replace("/", os.sep)
    path = Path(raw)
    if not path.is_absolute():
        path = INSTANCE / path
    path = path.resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError(f"Se rechazó una base SQLite fuera del proyecto: {path}") from exc
    return path


def _safe_pg_label(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.hostname or '?'}:{parsed.port or 5432}{parsed.path}"


def configured_targets() -> list[tuple[str, str]]:
    env = dotenv_values(ROOT / ".env")
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key in ENV_KEYS:
        url = str(env.get(key) or "").strip()
        if not url:
            continue
        if url.startswith("sqlite:///"):
            path = _sqlite_path(url)
            canonical = f"sqlite:{path}"
            target = str(path)
        elif url.startswith(("postgresql://", "postgresql+psycopg2://", "postgresql+psycopg://")):
            canonical = url
            target = url
        else:
            print(f"AVISO: {key} usa un motor no soportado y se omitirá.", file=sys.stderr)
            continue
        if canonical not in seen:
            seen.add(canonical)
            targets.append(("sqlite" if canonical.startswith("sqlite:") else "postgresql", target))
    return targets


def _sqlite_backup(path: Path, backup_dir: Path, marker: str = "antes_periodos") -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f"{path.stem}.{marker}{path.suffix}.bak"
    source_conn = sqlite3.connect(path, timeout=30)
    backup_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(backup_conn)
    finally:
        backup_conn.close()
        source_conn.close()
    return destination


def _existing_tables_sqlite(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def reset_sqlite(path: Path, *, dry_run: bool, backup_dir: Path) -> dict[str, object]:
    if not path.exists():
        return {"target": str(path), "periodos": 0, "deleted": {}, "backup": None, "missing": True}
    backup = None if dry_run else _sqlite_backup(path, backup_dir)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    tables = _existing_tables_sqlite(conn)
    counts: dict[str, int] = {}
    relevant = list(PERIOD_TABLES_DELETE_ORDER) + ["inventario_periodos"]
    for table in relevant:
        if table in tables:
            counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {_q(table)}").fetchone()[0])
    periodos = counts.get("inventario_periodos", 0)
    if dry_run or not periodos:
        conn.close()
        return {"target": str(path), "periodos": periodos, "deleted": counts, "backup": backup, "missing": False}

    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN IMMEDIATE")
        for table in PERIOD_TABLES_DELETE_ORDER:
            if table in tables:
                conn.execute(f"DELETE FROM {_q(table)}")
        if "notificaciones_usuario" in tables:
            conn.execute(
                "DELETE FROM notificaciones_usuario WHERE tipo IN ('periodo_abierto','periodo_cargado')"
            )
        if "inventario_items" in tables:
            conn.execute("UPDATE inventario_items SET periodo_id=NULL WHERE periodo_id IS NOT NULL")
        if "historial" in tables:
            conn.execute("UPDATE historial SET periodo_id=NULL WHERE periodo_id IS NOT NULL")
        if "delivery_ventas" in tables:
            conn.execute(
                "UPDATE delivery_ventas SET periodo_id=NULL, estado_periodo='sin_periodo' "
                "WHERE periodo_id IS NOT NULL"
            )
        conn.execute("DELETE FROM inventario_periodos")
        if "sqlite_sequence" in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }:
            sequence_tables = list(PERIOD_TABLES_DELETE_ORDER) + ["inventario_periodos"]
            placeholders = ",".join("?" for _ in sequence_tables)
            conn.execute(
                f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})",
                sequence_tables,
            )
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("VACUUM")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"target": str(path), "periodos": periodos, "deleted": counts, "backup": backup, "missing": False}


def reset_postgresql(url: str, *, dry_run: bool, no_backup: bool) -> dict[str, object]:
    if not dry_run and not no_backup:
        raise RuntimeError(
            "PostgreSQL requiere un respaldo externo. Ejecuta pg_dump o confirma con --no-backup."
        )
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(url)
    with engine.begin() as conn:
        tables = set(inspect(conn).get_table_names())
        counts = {
            table: int(conn.execute(text(f"SELECT COUNT(*) FROM {_q(table)}")).scalar_one())
            for table in (*PERIOD_TABLES_DELETE_ORDER, "inventario_periodos")
            if table in tables
        }
        periodos = counts.get("inventario_periodos", 0)
        if dry_run or not periodos:
            return {"target": _safe_pg_label(url), "periodos": periodos, "deleted": counts,
                    "backup": None, "missing": False}
        for table in PERIOD_TABLES_DELETE_ORDER:
            if table in tables:
                conn.execute(text(f"DELETE FROM {_q(table)}"))
        if "notificaciones_usuario" in tables:
            conn.execute(text(
                "DELETE FROM notificaciones_usuario WHERE tipo IN ('periodo_abierto','periodo_cargado')"
            ))
        if "inventario_items" in tables:
            conn.execute(text("UPDATE inventario_items SET periodo_id=NULL WHERE periodo_id IS NOT NULL"))
        if "historial" in tables:
            conn.execute(text("UPDATE historial SET periodo_id=NULL WHERE periodo_id IS NOT NULL"))
        if "delivery_ventas" in tables:
            conn.execute(text(
                "UPDATE delivery_ventas SET periodo_id=NULL, estado_periodo='sin_periodo' "
                "WHERE periodo_id IS NOT NULL"
            ))
        conn.execute(text("DELETE FROM inventario_periodos"))
    engine.dispose()
    return {"target": _safe_pg_label(url), "periodos": periodos, "deleted": counts,
            "backup": None, "missing": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Borra solo los períodos contables de Netward.")
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra lo que se eliminaría.")
    parser.add_argument("--yes", action="store_true", help="Confirma el borrado sin pregunta interactiva.")
    parser.add_argument("--no-backup", action="store_true", help="Permite PostgreSQL sin respaldo automático.")
    args = parser.parse_args()
    targets = configured_targets()
    if not targets:
        print("No se encontraron bases configuradas.", file=sys.stderr)
        return 2

    print("Bases configuradas:")
    for engine, target in targets:
        print(f"  - {target if engine == 'sqlite' else _safe_pg_label(target)}")
    if not args.dry_run and not args.yes:
        confirmation = input("Escribe BORRAR PERIODOS para continuar: ").strip()
        if confirmation != "BORRAR PERIODOS":
            print("Operación cancelada.")
            return 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = INSTANCE / "backups_periodos" / stamp
    total = 0
    for engine, target in targets:
        result = (
            reset_sqlite(Path(target), dry_run=args.dry_run, backup_dir=backup_dir)
            if engine == "sqlite"
            else reset_postgresql(target, dry_run=args.dry_run, no_backup=args.no_backup)
        )
        total += int(result["periodos"])
        action = "Se eliminarían" if args.dry_run else "Eliminados"
        print(f"{result['target']}: {action} {result['periodos']} período(s).")
        if result["backup"]:
            print(f"  Respaldo: {result['backup']}")
    print(f"Total de períodos {'detectados' if args.dry_run else 'eliminados'}: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
