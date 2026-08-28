#!/usr/bin/env python3
"""Migra Netward de SQLite a PostgreSQL con respaldo y verificacion.

La URL se lee exclusivamente de ``.env``. El script no imprime credenciales y
se niega a insertar si la base PostgreSQL ya contiene datos de la aplicacion.

Uso:
    python scripts/migrar_a_postgresql.py --preflight
    python scripts/migrar_a_postgresql.py
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
import psycopg2
from sqlalchemy.engine import make_url

from migracion.migrate_sqlite_to_postgres import (
    TABLAS_ORDEN,
    migrar,
    psycopg2_url,
)
from migracion.verificar_migracion import verificar
from scripts.database_maintenance import (
    DEFAULT_BACKUPS,
    DEFAULT_SQLITE,
    backup_sqlite,
    sqlite_integrity,
    sqlite_manifest,
)


REVISION_ESPERADA = "20260828_03"


def _database_url() -> str:
    load_dotenv(ROOT / ".env", override=True)
    value = (os.getenv("DATABASE_URL") or "").strip()
    if not value:
        raise RuntimeError("Falta DATABASE_URL en .env")
    if "PON_TU_PASSWORD" in value:
        raise RuntimeError("Reemplaza PON_TU_PASSWORD en .env antes de migrar")
    parsed = make_url(value)
    if not parsed.drivername.startswith("postgresql"):
        raise RuntimeError("DATABASE_URL debe apuntar a PostgreSQL")
    if not parsed.database:
        raise RuntimeError("DATABASE_URL no indica el nombre de la base")
    return value


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _estado_postgres(pg_url: str) -> dict:
    parsed = make_url(pg_url)
    connection = psycopg2.connect(psycopg2_url(pg_url))
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user, version()")
            database, user, version = cursor.fetchone()
            cursor.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname=current_schema() ORDER BY tablename"
            )
            tables = [row[0] for row in cursor.fetchall()]
            counts = {}
            for table in tables:
                if table == "alembic_version":
                    continue
                cursor.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}")
                counts[table] = int(cursor.fetchone()[0])
            revision = None
            if "alembic_version" in tables:
                cursor.execute("SELECT version_num FROM alembic_version")
                row = cursor.fetchone()
                revision = row[0] if row else None
        return {
            "host": parsed.host or "localhost",
            "port": parsed.port or 5432,
            "database": database,
            "user": user,
            "server": version.split(",")[0],
            "tables": tables,
            "counts": counts,
            "revision": revision,
        }
    finally:
        connection.close()


def _preflight(sqlite_path: Path, pg_url: str) -> tuple[dict, dict]:
    if not sqlite_path.is_file():
        raise FileNotFoundError(f"No existe SQLite: {sqlite_path}")
    sqlite_report = sqlite_integrity(sqlite_path)
    if sqlite_report["integrity"] != "ok" or sqlite_report["foreign_key_errors"]:
        raise RuntimeError(f"SQLite no supera integridad: {sqlite_report}")
    sqlite_data = sqlite_manifest(sqlite_path)
    pg_state = _estado_postgres(pg_url)
    nonempty = {
        table: count for table, count in pg_state["counts"].items() if count
    }
    if nonempty:
        detail = ", ".join(f"{table}={count}" for table, count in nonempty.items())
        raise RuntimeError(
            "PostgreSQL ya contiene datos; se cancela para evitar mezclarlos: " + detail
        )
    print(
        f"PostgreSQL conectado: {pg_state['database']} en "
        f"{pg_state['host']}:{pg_state['port']} ({pg_state['server']})"
    )
    print(
        f"SQLite integro: {sum(item['rows'] for item in sqlite_data.values())} "
        f"filas en {len(sqlite_data)} tablas"
    )
    print(
        f"Destino seguro: {len(pg_state['tables'])} tablas existentes, "
        "ninguna con datos de la aplicacion"
    )
    return sqlite_data, pg_state


def _upgrade_schema(pg_url: str) -> None:
    os.environ["DATABASE_URL"] = pg_url
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    state = _estado_postgres(pg_url)
    if state["revision"] != REVISION_ESPERADA:
        raise RuntimeError(
            f"Alembic quedo en {state['revision']!r}; se esperaba {REVISION_ESPERADA}"
        )
    missing = sorted(set(TABLAS_ORDEN) - set(state["tables"]))
    if missing:
        raise RuntimeError("Alembic no creo estas tablas: " + ", ".join(missing))
    if any(state["counts"].values()):
        raise RuntimeError("El destino recibio datos durante la creacion del esquema")
    print(f"Esquema PostgreSQL actualizado a {REVISION_ESPERADA}")


def _write_report(
    sqlite_path: Path,
    backup: Path,
    sqlite_before: dict,
    pg_state: dict,
) -> Path:
    DEFAULT_BACKUPS.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = DEFAULT_BACKUPS / f"migracion_postgresql_{timestamp}.json"
    payload = {
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "origen_sqlite": str(sqlite_path.resolve()),
        "respaldo_sqlite": str(backup.resolve()),
        "destino": {
            "host": pg_state["host"],
            "port": pg_state["port"],
            "database": pg_state["database"],
            "user": pg_state["user"],
        },
        "alembic_revision": pg_state["revision"],
        "tablas": {
            table: {"filas": data["rows"], "sha256": data["sha256"]}
            for table, data in sqlite_before.items()
        },
        "verificacion": "correcta",
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def run(
    sqlite_path: Path,
    preflight_only: bool = False,
    verify_only: bool = False,
) -> int:
    pg_url = _database_url()
    if verify_only:
        return 0 if verificar(str(sqlite_path), pg_url) else 1
    sqlite_before, _initial_pg = _preflight(sqlite_path, pg_url)
    if preflight_only:
        print("Preflight correcto; no se modifico ninguna base de datos.")
        return 0

    backup = backup_sqlite(sqlite_path)
    print(f"Respaldo SQLite creado: {backup}")
    _upgrade_schema(pg_url)
    migrar(str(sqlite_path), pg_url)
    if not verificar(str(sqlite_path), pg_url):
        raise RuntimeError("La verificacion final de PostgreSQL fallo")
    final_pg = _estado_postgres(pg_url)
    report = _write_report(
        sqlite_path, backup, sqlite_before, final_pg,
    )
    print(f"Migracion verificada. Informe: {report}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--preflight",
        action="store_true",
        help="Comprueba origen y destino sin escribir.",
    )
    mode.add_argument(
        "--verify-only",
        action="store_true",
        help="Repite la verificacion de una migracion ya realizada.",
    )
    args = parser.parse_args()
    try:
        return run(args.sqlite.resolve(), args.preflight, args.verify_only)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
