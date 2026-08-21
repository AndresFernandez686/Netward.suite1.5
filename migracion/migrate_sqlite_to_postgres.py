#!/usr/bin/env python3
"""
migrate_sqlite_to_postgres.py
=============================================================================
Migra todos los datos de la base SQLite de Netward a PostgreSQL.

Uso:
    python migrate_sqlite_to_postgres.py \
        --sqlite  instance/netward_empleado.db \
        --pg      "postgresql://usuario:clave@localhost:5432/netward"

Opciones:
    --sqlite   Ruta al archivo SQLite (default: instance/netward_empleado.db)
    --pg       URL de conexión PostgreSQL (o variable de entorno DATABASE_URL)
    --dry-run  Solo muestra cuántas filas hay por tabla, sin insertar nada
    --reset    Trunca las tablas de destino antes de insertar (CUIDADO)
    --tablas   Lista de tablas a migrar separadas por coma (default: todas)
=============================================================================
Requiere: psycopg2-binary   →  pip install psycopg2-binary
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Any

# ── Orden de migración respeta las FK ────────────────────────────────────────
TABLAS_ORDEN = [
    "clientes",
    "tiendas",
    "usuarios",
    "productos",
    "stock_thresholds",
    "producto_precios",
    "delivery_productos",
    "inventario_periodos",
    "inventario_snapshots",
    "inventario_items",
    "historial",
    "inventario_desc_snapshots",
    "delivery_ventas",
    "registros_averiados",
    "registros_vencimiento",
    "sincronizacion_log",
    # módulo auditoría
    "conteo_detalle",
    "ajustes_inventario",
    "excel_importados",
    "excel_detalles",
    "excel_detalle_ediciones",
    "facturas_compra",
    "facturas_compra_detalles",
    "auditoria_resultados",
    "asistente_ia_consultas",
    "justificaciones",
    "productos_relacionados",
]

# Columnas BOOLEAN de SQLite que vienen como 0/1
BOOL_COLS: dict[str, set[str]] = {
    "tiendas":             {"activa", "es_default"},
    "productos":           {"visible_empleado"},
    "inventario_items":    {"fue_sobreescrito"},
    "delivery_productos":  {"es_promocion", "activo"},
    "registros_averiados": {"revisado"},
    "registros_vencimiento": {"revisado"},
    "conteo_detalle":      {"fue_cargado", "fue_sobreescrito"},
    "excel_detalles":      {"excluido_auditoria"},
    "auditoria_resultados": {"alerta_continuidad"},
    "productos_relacionados": {"activo"},
}

# Tablas con secuencias SERIAL que hay que resetear tras la inserción masiva
SERIAL_TABLES = [
    "usuarios", "productos", "stock_thresholds", "producto_precios",
    "delivery_productos", "inventario_items", "historial",
    "inventario_snapshots", "inventario_desc_snapshots", "delivery_ventas",
    "registros_averiados", "registros_vencimiento", "sincronizacion_log",
    "inventario_periodos", "conteo_detalle", "ajustes_inventario",
    "excel_importados", "excel_detalles", "excel_detalle_ediciones",
    "facturas_compra", "facturas_compra_detalles", "auditoria_resultados",
    "asistente_ia_consultas", "justificaciones", "productos_relacionados",
]


def _convert_row(tabla: str, cols: list[str], row: tuple) -> tuple:
    """Convierte valores SQLite al tipo correcto para Postgres."""
    bool_cols = BOOL_COLS.get(tabla, set())
    result = []
    for col, val in zip(cols, row):
        if col in bool_cols:
            result.append(bool(val) if val is not None else None)
        else:
            result.append(val)
    return tuple(result)


def migrar(
    sqlite_path: str,
    pg_url: str,
    dry_run: bool = False,
    reset: bool = False,
    tablas_filtro: list[str] | None = None,
) -> None:
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("ERROR: psycopg2 no está instalado.")
        print("       Ejecutá: pip install psycopg2-binary")
        sys.exit(1)

    if not os.path.exists(sqlite_path):
        print(f"ERROR: archivo SQLite no encontrado: {sqlite_path}")
        sys.exit(1)

    tablas = tablas_filtro if tablas_filtro else TABLAS_ORDEN

    # ── Conexiones ────────────────────────────────────────────────────────────
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    pg_conn = psycopg2.connect(pg_url)
    pg_conn.autocommit = False

    print(f"\n{'DRY-RUN' if dry_run else 'MIGRACIÓN'} — SQLite: {sqlite_path}")
    print(f"Destino PostgreSQL: {pg_url.split('@')[-1]}\n")

    total_migradas = 0

    try:
        for tabla in tablas:
            cur_sqlite = sqlite_conn.cursor()

            # Verificar si la tabla existe en SQLite
            cur_sqlite.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabla,)
            )
            if not cur_sqlite.fetchone():
                print(f"  ⚠  {tabla:<35} — no existe en SQLite, se omite")
                continue

            cur_sqlite.execute(f"SELECT COUNT(*) FROM {tabla}")
            count = cur_sqlite.fetchone()[0]
            print(f"  →  {tabla:<35} {count:>7} filas", end="")

            if dry_run:
                print()
                continue

            cur_sqlite.execute(f"SELECT * FROM {tabla}")
            rows = cur_sqlite.fetchall()
            if not rows:
                print("  (vacía)")
                continue

            cols = [d[0] for d in cur_sqlite.description]
            pg_cur = pg_conn.cursor()

            if reset:
                pg_cur.execute(f"TRUNCATE TABLE {tabla} RESTART IDENTITY CASCADE")

            placeholders = ", ".join(["%s"] * len(cols))
            col_names    = ", ".join(cols)
            sql = f"INSERT INTO {tabla} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

            converted = [_convert_row(tabla, cols, tuple(r)) for r in rows]
            psycopg2.extras.execute_batch(pg_cur, sql, converted, page_size=500)

            pg_conn.commit()
            total_migradas += len(converted)
            print(f"  ✓")

        # ── Resetear secuencias SERIAL ────────────────────────────────────────
        if not dry_run:
            print("\nReseteando secuencias SERIAL...")
            pg_cur = pg_conn.cursor()
            for tabla in SERIAL_TABLES:
                if tablas_filtro and tabla not in tablas_filtro:
                    continue
                try:
                    pg_cur.execute(
                        f"SELECT setval(pg_get_serial_sequence('{tabla}','id'), "
                        f"COALESCE(MAX(id),0)+1, false) FROM {tabla}"
                    )
                    pg_conn.commit()
                    print(f"  ✓  secuencia de {tabla} reseteada")
                except Exception as e:
                    pg_conn.rollback()
                    print(f"  ⚠  {tabla}: {e}")

        print(f"\n{'─'*50}")
        print(f"{'DRY-RUN completado' if dry_run else 'Migración completada'}: {total_migradas} filas insertadas.\n")

    except Exception as exc:
        pg_conn.rollback()
        print(f"\n✗ ERROR: {exc}")
        raise
    finally:
        sqlite_conn.close()
        pg_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migra la base de datos de Netward de SQLite a PostgreSQL."
    )
    parser.add_argument(
        "--sqlite",
        default=os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "instance", "netward_empleado.db"
        ),
        help="Ruta al archivo SQLite (default: ../instance/netward_empleado.db)",
    )
    parser.add_argument(
        "--pg",
        default=os.getenv("DATABASE_URL", ""),
        help="URL PostgreSQL. Ej: postgresql://user:pass@host:5432/dbname",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo cuenta filas, no inserta nada.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="TRUNCATE las tablas de destino antes de insertar.",
    )
    parser.add_argument(
        "--tablas",
        default="",
        help="Tablas a migrar separadas por coma. Default: todas.",
    )

    args = parser.parse_args()

    if not args.pg:
        print("ERROR: indicá la URL de PostgreSQL con --pg o la variable DATABASE_URL.")
        sys.exit(1)

    tablas_filtro = [t.strip() for t in args.tablas.split(",") if t.strip()] or None

    migrar(
        sqlite_path=args.sqlite,
        pg_url=args.pg,
        dry_run=args.dry_run,
        reset=args.reset,
        tablas_filtro=tablas_filtro,
    )


if __name__ == "__main__":
    main()
