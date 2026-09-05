"""Agrega conversaciones persistentes para Nexa.

Revision ID: 20260831_05
Revises: 20260829_04
Create Date: 2026-08-31
"""
from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "20260831_05"
down_revision = "20260829_04"
branch_labels = None
depends_on = None


CONVERSACIONES = "asistente_ia_conversaciones"
CONSULTAS = "asistente_ia_consultas"
FK_CONVERSACION = "fk_asistente_consultas_conversacion"
IX_CONVERSACION = "ix_asistente_ia_consultas_conversacion_id"
IX_ACTUALIZADO = "ix_asistente_ia_conversaciones_actualizado"
IX_CLIENTE = "ix_asistente_ia_conversaciones_cliente_id"
IX_USUARIO = "ix_asistente_ia_conversaciones_usuario"
IX_COMPUESTO = "ix_asistente_conversaciones_cliente_usuario_actualizado"


def _crear_tabla(connection) -> None:
    if CONVERSACIONES in set(sa.inspect(connection).get_table_names()):
        return
    op.create_table(
        CONVERSACIONES,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cliente_id", sa.String(length=10), nullable=False),
        sa.Column("usuario", sa.String(length=80), nullable=False),
        sa.Column("titulo", sa.String(length=120), nullable=False),
        sa.Column("seccion_inicial", sa.String(length=40), nullable=False),
        sa.Column("creado", sa.DateTime(), nullable=False),
        sa.Column("actualizado", sa.DateTime(), nullable=False),
    )
    op.create_index(IX_CLIENTE, CONVERSACIONES, ["cliente_id"])
    op.create_index(IX_USUARIO, CONVERSACIONES, ["usuario"])
    op.create_index(IX_ACTUALIZADO, CONVERSACIONES, ["actualizado"])
    op.create_index(IX_COMPUESTO, CONVERSACIONES, ["cliente_id", "usuario", "actualizado"])


def _adaptar_consultas(connection) -> None:
    if CONSULTAS not in set(sa.inspect(connection).get_table_names()):
        return
    columnas = {item["name"]: item for item in sa.inspect(connection).get_columns(CONSULTAS)}
    with op.batch_alter_table(CONSULTAS, recreate="auto") as batch:
        if "conversacion_id" not in columnas:
            batch.add_column(sa.Column("conversacion_id", sa.Integer(), nullable=True))
        if "periodo_id" in columnas and not columnas["periodo_id"].get("nullable", True):
            batch.alter_column("periodo_id", existing_type=sa.Integer(), nullable=True)

    inspector = sa.inspect(connection)
    indices = {item["name"] for item in inspector.get_indexes(CONSULTAS)}
    if IX_CONVERSACION not in indices:
        op.create_index(IX_CONVERSACION, CONSULTAS, ["conversacion_id"])
    tiene_fk = any(
        fk.get("constrained_columns") == ["conversacion_id"]
        and fk.get("referred_table") == CONVERSACIONES
        for fk in sa.inspect(connection).get_foreign_keys(CONSULTAS)
    )
    if not tiene_fk:
        with op.batch_alter_table(CONSULTAS, recreate="auto") as batch:
            batch.create_foreign_key(
                FK_CONVERSACION,
                CONVERSACIONES,
                ["conversacion_id"],
                ["id"],
                ondelete="SET NULL",
            )


def _migrar_consultas_anteriores(connection) -> None:
    if CONSULTAS not in set(sa.inspect(connection).get_table_names()):
        return
    conversaciones = sa.table(
        CONVERSACIONES,
        sa.column("id", sa.Integer()),
        sa.column("cliente_id", sa.String()),
        sa.column("usuario", sa.String()),
        sa.column("titulo", sa.String()),
        sa.column("seccion_inicial", sa.String()),
        sa.column("creado", sa.DateTime()),
        sa.column("actualizado", sa.DateTime()),
    )
    rows = connection.execute(sa.text(
        "SELECT id, cliente_id, usuario, tipo, pregunta, creado "
        "FROM asistente_ia_consultas WHERE conversacion_id IS NULL ORDER BY id"
    )).mappings().all()
    for row in rows:
        creado = row["creado"] or datetime.utcnow()
        if not isinstance(creado, datetime):
            try:
                creado = datetime.fromisoformat(str(creado).replace("Z", "+00:00"))
                if creado.tzinfo is not None:
                    creado = creado.replace(tzinfo=None)
            except (TypeError, ValueError):
                creado = datetime.utcnow()
        titulo = (str(row["pregunta"] or "Conversación anterior").strip() or "Conversación anterior")[:120]
        conversation_id = connection.execute(
            sa.insert(conversaciones).values(
                cliente_id=row["cliente_id"],
                usuario=row["usuario"],
                titulo=titulo,
                seccion_inicial=str(row["tipo"] or "auditoria")[:40],
                creado=creado,
                actualizado=creado,
            ).returning(conversaciones.c.id)
        ).scalar_one()
        connection.execute(
            sa.text(
                "UPDATE asistente_ia_consultas SET conversacion_id = :conversation_id "
                "WHERE id = :consulta_id"
            ),
            {"conversation_id": conversation_id, "consulta_id": row["id"]},
        )


def upgrade() -> None:
    connection = op.get_bind()
    # SQLite puede dejar esta tabla auxiliar si una ejecución anterior se interrumpió.
    # Nunca contiene datos oficiales: Alembic la usa solo durante batch_alter_table.
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(
            "DROP TABLE IF EXISTS _alembic_tmp_asistente_ia_consultas"
        )
    _crear_tabla(connection)
    _adaptar_consultas(connection)
    _migrar_consultas_anteriores(connection)


def downgrade() -> None:
    connection = op.get_bind()
    tablas = set(sa.inspect(connection).get_table_names())
    if CONSULTAS in tablas:
        connection.execute(sa.text(
            "DELETE FROM asistente_ia_consultas WHERE periodo_id IS NULL"
        ))
        inspector = sa.inspect(connection)
        fk = next((
            item for item in inspector.get_foreign_keys(CONSULTAS)
            if item.get("constrained_columns") == ["conversacion_id"]
        ), None)
        with op.batch_alter_table(CONSULTAS, recreate="auto") as batch:
            if fk and fk.get("name"):
                batch.drop_constraint(fk["name"], type_="foreignkey")
            indices = {item["name"] for item in sa.inspect(connection).get_indexes(CONSULTAS)}
            if IX_CONVERSACION in indices:
                batch.drop_index(IX_CONVERSACION)
            columnas = {item["name"]: item for item in sa.inspect(connection).get_columns(CONSULTAS)}
            if "conversacion_id" in columnas:
                batch.drop_column("conversacion_id")
            if "periodo_id" in columnas:
                batch.alter_column("periodo_id", existing_type=sa.Integer(), nullable=False)
    if CONVERSACIONES in set(sa.inspect(connection).get_table_names()):
        op.drop_table(CONVERSACIONES)
