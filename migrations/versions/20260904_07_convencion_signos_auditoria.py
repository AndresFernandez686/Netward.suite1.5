"""Normaliza la diferencia: positivo sobrante y negativo faltante.

Revision ID: 20260904_07
Revises: 20260904_06
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa


revision = "20260904_07"
down_revision = "20260904_06"
branch_labels = None
depends_on = None


def _invertir_signos_y_descartar_informes() -> None:
    connection = op.get_bind()
    tablas = set(sa.inspect(connection).get_table_names())
    if "auditoria_resultados" in tablas:
        connection.execute(sa.text(
            "UPDATE auditoria_resultados "
            "SET diferencia = -COALESCE(diferencia, 0), "
            "diferencia_anterior_compensada = -COALESCE(diferencia_anterior_compensada, 0)"
        ))
    if "inventario_periodos" in tablas:
        columnas = {
            columna["name"]
            for columna in sa.inspect(connection).get_columns("inventario_periodos")
        }
        if {"informe_ia_markdown", "informe_ia_generado"} <= columnas:
            connection.execute(sa.text(
                "UPDATE inventario_periodos "
                "SET informe_ia_markdown = NULL, informe_ia_generado = NULL"
            ))


def upgrade() -> None:
    _invertir_signos_y_descartar_informes()


def downgrade() -> None:
    _invertir_signos_y_descartar_informes()
