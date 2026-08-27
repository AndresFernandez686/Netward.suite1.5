"""Esquema unificado, integridad referencial y JSONB.

Revision ID: 20260827_01
Revises: None
Create Date: 2026-08-27
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from core.models import db


revision = "20260827_01"
down_revision = None
branch_labels = None
depends_on = None

JSON_COLUMNS = {
    "inventario_desc_snapshots": ("stock_final_json",),
    "inventario_borradores": ("contenido_json",),
    "excel_detalle_ediciones": ("cambios_json",),
    "facturas_compra": ("analisis_json",),
    "asistente_ia_consultas": ("contexto_json",),
}


def _fk_signature(fk):
    return (
        tuple(fk.get("constrained_columns") or ()),
        fk.get("referred_table"),
        tuple(fk.get("referred_columns") or ()),
    )


def _default_sql(column):
    default = column.default
    if default is None or default.is_callable:
        return None
    value = default.arg
    if value is None:
        return None
    if isinstance(value, bool):
        return sa.text("TRUE" if value else "FALSE")
    if isinstance(value, (int, float)):
        return sa.text(str(value))
    return sa.text("'" + str(value).replace("'", "''") + "'")


def _ensure_columns(connection):
    inspector = sa.inspect(connection)
    existing_tables = set(inspector.get_table_names())
    for table_name, table in db.metadata.tables.items():
        if table_name not in existing_tables:
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        missing = [column for column in table.columns if column.name not in existing]
        if not missing:
            continue
        row_count = connection.execute(sa.text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one()
        with op.batch_alter_table(table_name, recreate="auto") as batch:
            for column in missing:
                server_default = _default_sql(column)
                if row_count and not column.nullable and server_default is None:
                    raise RuntimeError(
                        f"No se puede agregar {table_name}.{column.name}: es obligatoria y no tiene default"
                    )
                batch.add_column(sa.Column(
                    column.name,
                    column.type,
                    nullable=column.nullable,
                    server_default=server_default,
                ))


def _repair_or_validate_fk(connection, table, columns, target, target_columns, nullable):
    if len(columns) != 1 or len(target_columns) != 1:
        return
    column = columns[0]
    target_column = target_columns[0]
    preparer = connection.dialect.identifier_preparer
    table_q = preparer.quote(table)
    column_q = preparer.quote(column)
    target_q = preparer.quote(target)
    target_column_q = preparer.quote(target_column)
    invalid = connection.execute(sa.text(
        f"SELECT COUNT(*) FROM {table_q} src "
        f"WHERE src.{column_q} IS NOT NULL AND NOT EXISTS ("
        f"SELECT 1 FROM {target_q} dst WHERE dst.{target_column_q}=src.{column_q})"
    )).scalar_one()
    if not invalid:
        return
    if not nullable:
        raise RuntimeError(
            f"No se puede crear la FK {table}.{column}: hay {invalid} referencias huerfanas"
        )
    connection.execute(sa.text(
        f"UPDATE {table_q} SET {column_q}=NULL WHERE {column_q} IS NOT NULL AND NOT EXISTS ("
        f"SELECT 1 FROM {target_q} dst WHERE dst.{target_column_q}={table_q}.{column_q})"
    ))


def _ensure_foreign_keys(connection):
    inspector = sa.inspect(connection)
    existing_tables = set(inspector.get_table_names())
    for table_name, table in db.metadata.tables.items():
        if table_name not in existing_tables:
            continue
        existing = {_fk_signature(fk) for fk in inspector.get_foreign_keys(table_name)}
        missing = []
        for constraint in table.foreign_key_constraints:
            elements = list(constraint.elements)
            columns = tuple(element.parent.name for element in elements)
            target = elements[0].column.table.name
            target_columns = tuple(element.column.name for element in elements)
            signature = (columns, target, target_columns)
            nullable = all(table.c[name].nullable for name in columns)
            _repair_or_validate_fk(
                connection, table_name, columns, target, target_columns, nullable
            )
            if signature not in existing:
                missing.append((columns, target, target_columns))
        if not missing:
            continue
        with op.batch_alter_table(table_name, recreate="auto") as batch:
            for columns, target, target_columns in missing:
                name = f"fk_{table_name}_{'_'.join(columns)}_{target}"
                batch.create_foreign_key(name, target, list(columns), list(target_columns))


def _repair_existing_foreign_keys(connection):
    """Sanea primero todas las FK fisicas de instalaciones historicas."""
    inspector = sa.inspect(connection)
    for table_name in inspector.get_table_names():
        column_info = {item["name"]: item for item in inspector.get_columns(table_name)}
        for fk in inspector.get_foreign_keys(table_name):
            columns = tuple(fk.get("constrained_columns") or ())
            target_columns = tuple(fk.get("referred_columns") or ())
            target = fk.get("referred_table")
            if not target or not columns:
                continue
            nullable = all(column_info[name].get("nullable", True) for name in columns)
            _repair_or_validate_fk(
                connection, table_name, columns, target, target_columns, nullable
            )


def _ensure_indexes(connection):
    inspector = sa.inspect(connection)
    existing_tables = set(inspector.get_table_names())
    for table_name, table in db.metadata.tables.items():
        if table_name not in existing_tables:
            continue
        existing = {index["name"] for index in inspector.get_indexes(table_name)}
        for index in table.indexes:
            if index.name and index.name not in existing:
                op.create_index(
                    index.name,
                    table_name,
                    [column.name for column in index.columns],
                    unique=index.unique,
                )


def _validate_and_upgrade_jsonb(connection):
    if connection.dialect.name != "postgresql":
        return
    inspector = sa.inspect(connection)
    existing_tables = set(inspector.get_table_names())
    for table_name, columns in JSON_COLUMNS.items():
        if table_name not in existing_tables:
            continue
        types = {column["name"]: column["type"] for column in inspector.get_columns(table_name)}
        for column_name in columns:
            if isinstance(types.get(column_name), postgresql.JSONB):
                continue
            rows = connection.execute(sa.text(
                f'SELECT "{column_name}" FROM "{table_name}" '
                f'WHERE "{column_name}" IS NOT NULL'
            ))
            for (value,) in rows:
                if isinstance(value, str):
                    json.loads(value)
            op.alter_column(
                table_name,
                column_name,
                existing_type=types[column_name],
                type_=postgresql.JSONB(),
                postgresql_using=f'"{column_name}"::jsonb',
            )


def upgrade() -> None:
    connection = op.get_bind()
    # Permite tanto instalaciones nuevas como bases SQLite historicas.
    db.metadata.create_all(bind=connection, checkfirst=True)
    _repair_existing_foreign_keys(connection)
    _ensure_columns(connection)

    for table_name in (
        "productos", "inventario_items", "historial", "producto_precios",
        "registros_averiados", "registros_vencimiento", "conteo_detalle",
        "auditoria_resultados",
    ):
        if table_name in sa.inspect(connection).get_table_names():
            columns = {item["name"] for item in sa.inspect(connection).get_columns(table_name)}
            if "categoria" in columns:
                connection.execute(sa.text(
                    f"UPDATE {table_name} SET categoria='Fanee' WHERE categoria='Extras'"
                ))

    _ensure_foreign_keys(connection)
    _ensure_indexes(connection)
    _validate_and_upgrade_jsonb(connection)


def downgrade() -> None:
    # La revision inicial protege datos existentes: no elimina el esquema al retroceder.
    pass
