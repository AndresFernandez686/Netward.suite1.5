"""Inspecciona separación de tenants en SQLite sin mostrar nombres ni documentos."""
from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASES = (
    ROOT / "instance" / "netward_empleado.db",
    ROOT / "instance" / "netward_admin.db",
)


def inspect_database(path: Path) -> None:
    print(path.name)
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        tenant_ids = (
            [row[0] for row in connection.execute("SELECT id FROM clientes ORDER BY id")]
            if "clientes" in tables else []
        )
        user_counts = (
            list(connection.execute(
                "SELECT cliente_id, COUNT(*) FROM usuarios GROUP BY cliente_id ORDER BY cliente_id"
            ))
            if "usuarios" in tables else []
        )
        print(f"  clientes: {len(tenant_ids)} {','.join(tenant_ids)}")
        print(f"  usuarios_por_cliente: {user_counts}")
    finally:
        connection.close()


if __name__ == "__main__":
    for database in DATABASES:
        if database.exists():
            inspect_database(database)
