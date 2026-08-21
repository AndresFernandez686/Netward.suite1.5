#!/usr/bin/env python3
"""
verificar_migracion.py
=============================================================================
Verifica que la migración SQLite → PostgreSQL fue exitosa:
  - Compara conteo de filas por tabla
  - Detecta tablas faltantes en Postgres
  - Verifica que las secuencias SERIAL apunten al valor correcto

Uso:
    python verificar_migracion.py \
        --sqlite  instance/netward_empleado.db \
        --pg      "postgresql://usuario:clave@localhost:5432/netward"
=============================================================================
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

TABLAS = [
    "clientes", "tiendas", "usuarios", "productos",
    "stock_thresholds", "producto_precios", "delivery_productos",
    "inventario_items", "historial", "inventario_snapshots",
    "inventario_desc_snapshots", "delivery_ventas",
    "registros_averiados", "registros_vencimiento", "sincronizacion_log",
    "inventario_periodos", "conteo_detalle", "ajustes_inventario",
    "excel_importados", "excel_detalles", "excel_detalle_ediciones",
    "facturas_compra", "facturas_compra_detalles", "auditoria_resultados",
    "asistente_ia_consultas", "justificaciones", "productos_relacionados",
]

SERIAL_TABLES = [
    t for t in TABLAS if t != "clientes"
]

COLUMNAS_CRITICAS = {
    "usuarios": {"catalogo_version_recibida"},
    "productos": {"catalogo_version"},
    "inventario_items": {
        "periodo_id", "usuario_ultima_carga", "version", "fue_sobreescrito",
    },
    "historial": {
        "snapshot_id", "periodo_id", "tipo_movimiento", "usuario_anterior",
        "cantidad_anterior", "version",
    },
    "conteo_detalle": {
        "primera_carga", "veces_sincronizado", "fue_sobreescrito",
        "version_ultima_carga",
    },
    "delivery_ventas": {"periodo_id", "estado_periodo"},
    "asistente_ia_consultas": {
        "cliente_id", "tienda_id", "periodo_id", "resultado_id", "usuario",
        "pregunta", "respuesta", "proveedor", "modelo", "estado", "creado",
    },
    "excel_detalle_ediciones": {
        "cliente_id", "periodo_id", "excel_id", "detalle_id", "usuario",
        "cambios_json", "creado",
    },
    "facturas_compra": {
        "periodo_id", "cliente_id", "proveedor", "numero_factura", "fecha_emision",
        "sha256", "archivo_pdf", "metodo_extraccion", "estado", "total_factura",
    },
    "facturas_compra_detalles": {
        "factura_id", "cantidad_facturada", "factor_conversion", "compras_calculadas",
        "producto_id", "estado_vinculacion", "confianza",
    },
}

CLAVES_CRITICAS = (
    ("inventario_items", "periodo_id", "inventario_periodos"),
    ("historial", "snapshot_id", "inventario_snapshots"),
    ("historial", "periodo_id", "inventario_periodos"),
    ("delivery_ventas", "periodo_id", "inventario_periodos"),
    ("excel_detalle_ediciones", "periodo_id", "inventario_periodos"),
    ("excel_detalle_ediciones", "excel_id", "excel_importados"),
    ("excel_detalle_ediciones", "detalle_id", "excel_detalles"),
    ("facturas_compra", "periodo_id", "inventario_periodos"),
    ("facturas_compra_detalles", "factura_id", "facturas_compra"),
    ("facturas_compra_detalles", "producto_id", "productos"),
    ("asistente_ia_consultas", "periodo_id", "inventario_periodos"),
    ("asistente_ia_consultas", "resultado_id", "auditoria_resultados"),
)


def verificar(sqlite_path: str, pg_url: str) -> bool:
    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 no está instalado. Ejecutá: pip install psycopg2-binary")
        sys.exit(1)

    if not os.path.exists(sqlite_path):
        print(f"ERROR: SQLite no encontrado: {sqlite_path}")
        sys.exit(1)

    sqlite_conn = sqlite3.connect(sqlite_path)
    pg_conn     = psycopg2.connect(pg_url)
    pg_conn.autocommit = True

    print(f"\nVerificación de migración")
    print(f"SQLite : {sqlite_path}")
    print(f"Postgres: {pg_url.split('@')[-1]}\n")
    print(f"{'Tabla':<35} {'SQLite':>8} {'Postgres':>10} {'Estado':>10}")
    print("─" * 70)

    errores = 0

    for tabla in TABLAS:
        # SQLite
        cur_s = sqlite_conn.cursor()
        cur_s.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabla,)
        )
        if not cur_s.fetchone():
            print(f"  {tabla:<33} {'—':>8} {'—':>10}  ⚠ no en SQLite")
            continue

        cur_s.execute(f"SELECT COUNT(*) FROM {tabla}")
        count_sqlite = cur_s.fetchone()[0]

        # Postgres
        cur_p = pg_conn.cursor()
        try:
            cur_p.execute(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=%s)",
                (tabla,),
            )
            existe_tabla = cur_p.fetchone()
            if not existe_tabla or not existe_tabla[0]:
                print(f"  {tabla:<33} {count_sqlite:>8} {'—':>10}  ✗ NO EXISTE en Postgres")
                errores += 1
                continue

            cur_p.execute(f"SELECT COUNT(*) FROM {tabla}")
            fila_count_pg = cur_p.fetchone()
            count_pg = fila_count_pg[0] if fila_count_pg else 0

            ok = count_pg >= count_sqlite
            estado = "✓ OK" if ok else f"✗ FALTAN {count_sqlite - count_pg}"
            if not ok:
                errores += 1
            print(f"  {tabla:<33} {count_sqlite:>8} {count_pg:>10}  {estado}")
        except Exception as e:
            print(f"  {tabla:<33} {count_sqlite:>8} {'ERROR':>10}  ✗ {e}")
            errores += 1

    # ── Verificar esquema multi-empleado ─────────────────────────────────────
    print(f"\n{'─'*70}")
    print("Verificando columnas y claves multi-empleado...\n")
    cur_p = pg_conn.cursor()
    for tabla, esperadas in COLUMNAS_CRITICAS.items():
        cur_p.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s",
            (tabla,),
        )
        existentes = {row[0] for row in cur_p.fetchall()}
        faltantes = sorted(esperadas - existentes)
        if faltantes:
            print(f"  {tabla:<35} ✗ faltan: {', '.join(faltantes)}")
            errores += len(faltantes)
        else:
            print(f"  {tabla:<35} ✓ columnas completas")

    for tabla, columna, destino in CLAVES_CRITICAS:
        cur_p.execute(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_constraint c "
            "JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=ANY(c.conkey) "
            "WHERE c.contype='f' AND c.conrelid=%s::regclass "
            "AND c.confrelid=%s::regclass AND a.attname=%s)",
            (tabla, destino, columna),
        )
        etiqueta = f"{tabla}.{columna} → {destino}"
        fila_fk = cur_p.fetchone()
        if fila_fk and fila_fk[0]:
            print(f"  {etiqueta:<50} ✓ FK presente")
        else:
            print(f"  {etiqueta:<50} ✗ FK ausente")
            errores += 1

    # ── Verificar secuencias ─────────────────────────────────────────────────
    print(f"\n{'─'*70}")
    print("Verificando secuencias SERIAL...\n")
    cur_p = pg_conn.cursor()
    for tabla in SERIAL_TABLES:
        try:
            cur_p.execute(
                f"SELECT last_value FROM pg_sequences WHERE sequencename = "
                f"(SELECT pg_get_serial_sequence('{tabla}', 'id'))"
            )
            row = cur_p.fetchone()
            seq_val = row[0] if row else "—"
            cur_p.execute(f"SELECT COALESCE(MAX(id), 0) FROM {tabla}")
            fila_max_id = cur_p.fetchone()
            max_id = fila_max_id[0] if fila_max_id else 0
            ok = (seq_val is None or seq_val == "—" or seq_val >= max_id)
            estado = "✓" if ok else f"✗ seq={seq_val} max_id={max_id}"
            print(f"  {tabla:<35} seq_val={str(seq_val):>8}  max_id={max_id:>8}  {estado}")
            if not ok:
                errores += 1
        except Exception as e:
            print(f"  {tabla:<35}  ⚠ {e}")

    print(f"\n{'─'*70}")
    if errores == 0:
        print("✓ Migración verificada sin errores.\n")
    else:
        print(f"✗ Se encontraron {errores} problema(s). Revisá los ítems marcados.\n")

    sqlite_conn.close()
    pg_conn.close()

    return errores == 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verifica que la migración SQLite → PostgreSQL sea correcta."
    )
    parser.add_argument(
        "--sqlite",
        default=os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "instance", "netward_empleado.db"
        ),
    )
    parser.add_argument("--pg", default=os.getenv("DATABASE_URL", ""))
    args = parser.parse_args()

    if not args.pg:
        print("ERROR: indicá la URL de PostgreSQL con --pg o la variable DATABASE_URL.")
        sys.exit(1)

    ok = verificar(args.sqlite, args.pg)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
