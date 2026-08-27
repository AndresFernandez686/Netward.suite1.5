#!/usr/bin/env python3
"""Respaldo, reparacion y simulacro de restauracion de Netward.

Nunca sobrescribe un respaldo existente. Las reparaciones SQLite crean primero
una copia consistente mediante la API de backup de SQLite.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import unquote, urlparse
import uuid


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_SQLITE = ROOT / "instance" / "netward_empleado.db"
DEFAULT_BACKUPS = ROOT / "backups" / "database"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _canonical(value):
    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, bytes):
        return {"binary_sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in ("{", "["):
            try:
                return _canonical(json.loads(stripped))
            except (TypeError, ValueError):
                pass
        try:
            if len(stripped) >= 19 and stripped[4:5] == "-" and stripped[10:11] in (" ", "T"):
                return datetime.fromisoformat(stripped).isoformat(sep=" ")
        except ValueError:
            pass
        return value
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _rows_digest(rows) -> str:
    row_hashes = []
    for row in rows:
        payload = json.dumps(
            [_canonical(value) for value in row],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        row_hashes.append(hashlib.sha256(payload).hexdigest())
    digest = hashlib.sha256()
    for row_hash in sorted(row_hashes):
        digest.update(row_hash.encode("ascii"))
    return digest.hexdigest()


def sqlite_manifest(path: Path) -> dict:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        result = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            rows = connection.execute(f"SELECT * FROM {quoted}").fetchall()
            result[table] = {"rows": len(rows), "sha256": _rows_digest(rows)}
        return result
    finally:
        connection.close()


def sqlite_integrity(path: Path) -> dict:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        return {"integrity": integrity, "foreign_key_errors": foreign_keys}
    finally:
        connection.close()


def backup_sqlite(source: Path, output_dir: Path = DEFAULT_BACKUPS) -> Path:
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{source.stem}_{_timestamp()}.sqlite3"
    if target.exists():
        raise FileExistsError(target)
    source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()
    if sqlite_integrity(target)["integrity"] != "ok":
        target.unlink(missing_ok=True)
        raise RuntimeError("El respaldo SQLite no supera integrity_check")
    return target


def repair_sqlite_foreign_keys(path: Path) -> tuple[Path, int]:
    backup = backup_sqlite(path)
    connection = sqlite3.connect(path)
    repaired = 0
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        for table in tables:
            info = {row[1]: row for row in connection.execute(f'PRAGMA table_info("{table}")')}
            for fk in connection.execute(f'PRAGMA foreign_key_list("{table}")'):
                _id, _seq, target, source_col, target_col, *_rest = fk
                if info[source_col][3]:
                    continue
                table_q = '"' + table.replace('"', '""') + '"'
                target_q = '"' + target.replace('"', '""') + '"'
                source_q = '"' + source_col.replace('"', '""') + '"'
                target_col_q = '"' + target_col.replace('"', '""') + '"'
                cursor = connection.execute(
                    f"UPDATE {table_q} SET {source_q}=NULL "
                    f"WHERE {source_q} IS NOT NULL AND NOT EXISTS ("
                    f"SELECT 1 FROM {target_q} WHERE {target_q}.{target_col_q}={table_q}.{source_q})"
                )
                repaired += max(cursor.rowcount, 0)
        connection.commit()
        report = sqlite_integrity(path)
        if report["integrity"] != "ok" or report["foreign_key_errors"]:
            raise RuntimeError(f"La reparacion no dejo la base integra: {report}")
    except Exception:
        connection.rollback()
        connection.close()
        shutil.copy2(backup, path)
        raise
    finally:
        if connection:
            connection.close()
    return backup, repaired


def verify_sqlite_restore(source: Path) -> Path:
    before = sqlite_manifest(source)
    backup = backup_sqlite(source)
    with tempfile.TemporaryDirectory(prefix="netward_restore_") as temp_dir:
        restored = Path(temp_dir) / "restored.sqlite3"
        shutil.copy2(backup, restored)
        report = sqlite_integrity(restored)
        after = sqlite_manifest(restored)
        if report["integrity"] != "ok" or report["foreign_key_errors"]:
            raise RuntimeError(f"Restauracion SQLite no integra: {report}")
        if before != after:
            raise RuntimeError("La restauracion SQLite no coincide en filas o hashes")
    return backup


def audit_sqlite_schema(path: Path) -> dict:
    from sqlalchemy import create_engine, inspect
    from core.models import db

    engine = create_engine(f"sqlite:///{path.resolve().as_posix()}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    missing_tables = sorted(set(db.metadata.tables) - tables)
    missing_foreign_keys = []
    missing_indexes = []
    for table_name, table in db.metadata.tables.items():
        if table_name not in tables:
            continue
        actual_fks = {
            (
                tuple(item.get("constrained_columns") or ()),
                item.get("referred_table"),
                tuple(item.get("referred_columns") or ()),
            )
            for item in inspector.get_foreign_keys(table_name)
        }
        for constraint in table.foreign_key_constraints:
            elements = list(constraint.elements)
            expected = (
                tuple(element.parent.name for element in elements),
                elements[0].column.table.name,
                tuple(element.column.name for element in elements),
            )
            if expected not in actual_fks:
                missing_foreign_keys.append(f"{table_name}.{','.join(expected[0])}")
        actual_indexes = {item["name"] for item in inspector.get_indexes(table_name)}
        for index in table.indexes:
            if index.name not in actual_indexes:
                missing_indexes.append(index.name)
    with engine.connect() as connection:
        version = None
        if "alembic_version" in tables:
            version = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar()
    engine.dispose()
    return {
        **sqlite_integrity(path),
        "alembic_version": version,
        "missing_tables": missing_tables,
        "missing_foreign_keys": sorted(missing_foreign_keys),
        "missing_indexes": sorted(missing_indexes),
    }


def _pg_parts(url: str):
    parsed = urlparse(url.replace("postgresql+psycopg2://", "postgresql://", 1))
    if parsed.scheme not in {"postgresql", "postgres"} or not parsed.hostname:
        raise ValueError("DATABASE_URL no es una URL PostgreSQL valida")
    return {
        "host": parsed.hostname,
        "port": str(parsed.port or 5432),
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": unquote(parsed.path.lstrip("/")),
    }


def _pg_env(parts: dict) -> dict:
    environment = os.environ.copy()
    if parts["password"]:
        environment["PGPASSWORD"] = parts["password"]
    return environment


def backup_postgres(url: str, output_dir: Path = DEFAULT_BACKUPS) -> Path:
    parts = _pg_parts(url)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{parts['database']}_{_timestamp()}.dump"
    command = [
        "pg_dump", "--format=custom", "--no-owner", "--no-acl",
        "--host", parts["host"], "--port", parts["port"],
        "--username", parts["user"], "--file", str(target), parts["database"],
    ]
    subprocess.run(command, check=True, env=_pg_env(parts))
    subprocess.run(["pg_restore", "--list", str(target)], check=True, capture_output=True)
    return target


def postgres_manifest(connection) -> dict:
    cursor = connection.cursor()
    cursor.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname=current_schema() ORDER BY tablename"
    )
    result = {}
    for (table,) in cursor.fetchall():
        table_q = '"' + table.replace('"', '""') + '"'
        table_cursor = connection.cursor()
        table_cursor.execute(f"SELECT * FROM {table_q}")
        rows = table_cursor.fetchall()
        result[table] = {"rows": len(rows), "sha256": _rows_digest(rows)}
        table_cursor.close()
    cursor.close()
    return result


def verify_postgres_restore(url: str) -> Path:
    try:
        import psycopg2
        from psycopg2 import sql
    except ImportError as exc:
        raise RuntimeError("Instala psycopg2-binary antes del simulacro PostgreSQL") from exc
    parts = _pg_parts(url)
    backup = backup_postgres(url)
    test_database = f"netward_restore_{uuid.uuid4().hex[:12]}"
    admin = psycopg2.connect(
        host=parts["host"], port=parts["port"], user=parts["user"],
        password=parts["password"], dbname="postgres",
    )
    admin.autocommit = True
    source = restored = None
    try:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_database)))
        restore_command = [
            "pg_restore", "--no-owner", "--no-acl", "--exit-on-error",
            "--host", parts["host"], "--port", parts["port"],
            "--username", parts["user"], "--dbname", test_database, str(backup),
        ]
        subprocess.run(restore_command, check=True, env=_pg_env(parts))
        source = psycopg2.connect(
            host=parts["host"], port=parts["port"], user=parts["user"],
            password=parts["password"], dbname=parts["database"],
        )
        restored = psycopg2.connect(
            host=parts["host"], port=parts["port"], user=parts["user"],
            password=parts["password"], dbname=test_database,
        )
        if postgres_manifest(source) != postgres_manifest(restored):
            raise RuntimeError("La restauracion PostgreSQL no coincide en filas o hashes")
    finally:
        if source:
            source.close()
        if restored:
            restored.close()
        with admin.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()",
                (test_database,),
            )
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(test_database)))
        admin.close()
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("backup-sqlite", "verify-sqlite", "repair-sqlite", "audit-sqlite"):
        command = subparsers.add_parser(name)
        command.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    for name in ("backup-postgres", "verify-postgres"):
        command = subparsers.add_parser(name)
        command.add_argument("--url", default=os.getenv("DATABASE_URL", ""))

    args = parser.parse_args()
    if args.command == "backup-sqlite":
        print(backup_sqlite(args.sqlite))
    elif args.command == "verify-sqlite":
        print(f"Restauracion SQLite verificada. Respaldo: {verify_sqlite_restore(args.sqlite)}")
    elif args.command == "repair-sqlite":
        backup, repaired = repair_sqlite_foreign_keys(args.sqlite)
        print(f"Referencias reparadas: {repaired}. Respaldo: {backup}")
    elif args.command == "audit-sqlite":
        print(json.dumps(audit_sqlite_schema(args.sqlite), ensure_ascii=False, indent=2))
    else:
        if not args.url:
            parser.error("Indica --url o DATABASE_URL")
        if args.command == "backup-postgres":
            print(backup_postgres(args.url))
        else:
            print(f"Restauracion PostgreSQL verificada. Respaldo: {verify_postgres_restore(args.url)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
