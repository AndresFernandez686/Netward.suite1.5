"""Almacena el informe Markdown reutilizable de Nexa por período.

Revision ID: 20260904_06
Revises: 20260831_05
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa


revision = "20260904_06"
down_revision = "20260831_05"
branch_labels = None
depends_on = None


TABLA = "inventario_periodos"
COLUMNAS = {
    "informe_ia_markdown": sa.Text(),
    "informe_ia_generado": sa.DateTime(),
}


def _columnas_existentes(connection) -> set[str]:
    inspector = sa.inspect(connection)
    if TABLA not in set(inspector.get_table_names()):
        return set()
    return {columna["name"] for columna in inspector.get_columns(TABLA)}


def upgrade() -> None:
    connection = op.get_bind()
    existentes = _columnas_existentes(connection)
    faltantes = [nombre for nombre in COLUMNAS if nombre not in existentes]
    if not faltantes:
        return
    with op.batch_alter_table(TABLA, recreate="auto") as batch:
        for nombre in faltantes:
            batch.add_column(sa.Column(nombre, COLUMNAS[nombre], nullable=True))


def downgrade() -> None:
    connection = op.get_bind()
    existentes = _columnas_existentes(connection)
    presentes = [nombre for nombre in reversed(COLUMNAS) if nombre in existentes]
    if not presentes:
        return
    with op.batch_alter_table(TABLA, recreate="auto") as batch:
        for nombre in presentes:
            batch.drop_column(nombre)
