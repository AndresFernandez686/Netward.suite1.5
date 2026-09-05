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


def upgrade() -> None:
    with op.batch_alter_table("inventario_periodos", recreate="auto") as batch:
        batch.add_column(sa.Column("informe_ia_markdown", sa.Text(), nullable=True))
        batch.add_column(sa.Column("informe_ia_generado", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("inventario_periodos", recreate="auto") as batch:
        batch.drop_column("informe_ia_generado")
        batch.drop_column("informe_ia_markdown")
