"""Vincula los averiados con su período contable.

Revision ID: 20260829_04
Revises: 20260828_03
Create Date: 2026-08-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260829_04"
down_revision = "20260828_03"
branch_labels = None
depends_on = None


TABLA = "registros_averiados"
COLUMNA = "periodo_id"
INDICE = "ix_registros_averiados_periodo_id"
FK = "fk_registros_averiados_periodo_id_inventario_periodos"


def _agregar_columna_si_falta(connection) -> None:
    inspector = sa.inspect(connection)
    columnas = {columna["name"] for columna in inspector.get_columns(TABLA)}
    if COLUMNA not in columnas:
        op.add_column(TABLA, sa.Column(COLUMNA, sa.Integer(), nullable=True))


def _asignar_historicos(connection) -> None:
    # Se elige el período más reciente de la misma empresa/tienda que contiene
    # la fecha. Los registros sin coincidencia quedan NULL y el motor los excluye.
    connection.execute(sa.text(
        """
        UPDATE registros_averiados
           SET periodo_id = (
               SELECT p.id
                 FROM inventario_periodos AS p
                WHERE p.cliente_id = registros_averiados.cliente_id
                  AND p.tienda_id = registros_averiados.tienda_id
                  AND registros_averiados.fecha >= p.fecha_desde
                  AND registros_averiados.fecha <= p.fecha_hasta
                ORDER BY p.id DESC
                LIMIT 1
           )
         WHERE periodo_id IS NULL
        """
    ))


def _asegurar_indice_y_fk(connection) -> None:
    inspector = sa.inspect(connection)
    indices = {indice["name"] for indice in inspector.get_indexes(TABLA)}
    if INDICE not in indices:
        op.create_index(INDICE, TABLA, [COLUMNA])

    inspector = sa.inspect(connection)
    tiene_fk = any(
        fk.get("constrained_columns") == [COLUMNA]
        and fk.get("referred_table") == "inventario_periodos"
        for fk in inspector.get_foreign_keys(TABLA)
    )
    if not tiene_fk:
        with op.batch_alter_table(TABLA, recreate="auto") as batch:
            batch.create_foreign_key(
                FK, "inventario_periodos", [COLUMNA], ["id"], ondelete="RESTRICT",
            )


def upgrade() -> None:
    connection = op.get_bind()
    tablas = set(sa.inspect(connection).get_table_names())
    if TABLA not in tablas or "inventario_periodos" not in tablas:
        return
    _agregar_columna_si_falta(connection)
    _asignar_historicos(connection)
    _asegurar_indice_y_fk(connection)


def downgrade() -> None:
    connection = op.get_bind()
    if TABLA not in set(sa.inspect(connection).get_table_names()):
        return
    inspector = sa.inspect(connection)
    fk = next(
        (
            item for item in inspector.get_foreign_keys(TABLA)
            if item.get("constrained_columns") == [COLUMNA]
            and item.get("referred_table") == "inventario_periodos"
        ),
        None,
    )
    with op.batch_alter_table(TABLA, recreate="auto") as batch:
        if fk and fk.get("name"):
            batch.drop_constraint(fk["name"], type_="foreignkey")
        indices = {indice["name"] for indice in sa.inspect(connection).get_indexes(TABLA)}
        if INDICE in indices:
            batch.drop_index(INDICE)
        columnas = {columna["name"] for columna in sa.inspect(connection).get_columns(TABLA)}
        if COLUMNA in columnas:
            batch.drop_column(COLUMNA)
