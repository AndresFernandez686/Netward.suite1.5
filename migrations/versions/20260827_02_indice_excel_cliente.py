"""Índice de aislamiento para detalles del Excel oficial.

Revision ID: 20260827_02
Revises: 20260827_01
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa


revision = "20260827_02"
down_revision = "20260827_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    indexes = {
        item["name"] for item in sa.inspect(connection).get_indexes("excel_detalles")
    }
    if "ix_excel_detalles_cliente_id" not in indexes:
        op.create_index(
            "ix_excel_detalles_cliente_id", "excel_detalles", ["cliente_id"]
        )


def downgrade() -> None:
    connection = op.get_bind()
    indexes = {
        item["name"] for item in sa.inspect(connection).get_indexes("excel_detalles")
    }
    if "ix_excel_detalles_cliente_id" in indexes:
        op.drop_index("ix_excel_detalles_cliente_id", table_name="excel_detalles")
