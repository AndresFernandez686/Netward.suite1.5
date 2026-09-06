"""Registra el origen de cada carga de inventario.

Revision ID: 20260906_08
Revises: 20260904_07
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa


revision = "20260906_08"
down_revision = "20260904_07"
branch_labels = None
depends_on = None


_TABLAS = ("inventario_items", "conteo_detalle", "historial")


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tablas = set(inspector.get_table_names())
    for tabla in _TABLAS:
        if tabla not in tablas:
            continue
        columnas = {columna["name"] for columna in inspector.get_columns(tabla)}
        if "origen_carga" not in columnas:
            with op.batch_alter_table(tabla) as batch_op:
                batch_op.add_column(sa.Column(
                    "origen_carga",
                    sa.String(length=40),
                    nullable=False,
                    server_default="carga_manual",
                ))


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tablas = set(inspector.get_table_names())
    for tabla in reversed(_TABLAS):
        if tabla not in tablas:
            continue
        columnas = {columna["name"] for columna in inspector.get_columns(tabla)}
        if "origen_carga" in columnas:
            with op.batch_alter_table(tabla) as batch_op:
                batch_op.drop_column("origen_carga")
