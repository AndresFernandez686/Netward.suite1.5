"""Trazabilidad segura al re-ejecutar auditorias.

Revision ID: 20260828_03
Revises: 20260827_02
Create Date: 2026-08-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260828_03"
down_revision = "20260827_02"
branch_labels = None
depends_on = None


FK_DESEADAS = (
    ("auditoria_resultados", "periodo_id", "inventario_periodos", "CASCADE"),
    ("asistente_ia_consultas", "resultado_id", "auditoria_resultados", "SET NULL"),
    ("justificaciones", "resultado_id", "auditoria_resultados", "RESTRICT"),
)

INDICES = (
    ("auditoria_resultados", "ix_auditoria_resultados_periodo_id", ("periodo_id",)),
    ("justificaciones", "ix_justificaciones_resultado_id", ("resultado_id",)),
)


def _normalizar_accion(valor) -> str:
    return str(valor or "").replace("_", " ").upper()


def _actualizar_fks_postgresql(connection) -> None:
    if connection.dialect.name != "postgresql":
        # La aplicacion ya no elimina resultados al re-ejecutar. En SQLite
        # historico no se recrean tablas solo para cambiar acciones de borrado.
        return
    inspector = sa.inspect(connection)
    tablas = set(inspector.get_table_names())
    for tabla, columna, destino, accion in FK_DESEADAS:
        if tabla not in tablas or destino not in tablas:
            continue
        fk = next(
            (
                item for item in inspector.get_foreign_keys(tabla)
                if item.get("constrained_columns") == [columna]
                and item.get("referred_table") == destino
            ),
            None,
        )
        actual = _normalizar_accion((fk or {}).get("options", {}).get("ondelete"))
        if actual == accion:
            continue
        with op.batch_alter_table(tabla, recreate="auto") as batch:
            if fk:
                if not fk.get("name"):
                    raise RuntimeError(
                        f"La FK {tabla}.{columna} no tiene nombre en PostgreSQL"
                    )
                batch.drop_constraint(fk["name"], type_="foreignkey")
            batch.create_foreign_key(
                f"fk_{tabla}_{columna}_{destino}",
                destino,
                [columna],
                ["id"],
                ondelete=accion,
            )
        inspector = sa.inspect(connection)


def _asegurar_indices(connection) -> None:
    inspector = sa.inspect(connection)
    tablas = set(inspector.get_table_names())
    for tabla, nombre, columnas in INDICES:
        if tabla not in tablas:
            continue
        existentes = {item["name"] for item in inspector.get_indexes(tabla)}
        if nombre not in existentes:
            op.create_index(nombre, tabla, list(columnas))
            inspector = sa.inspect(connection)


def upgrade() -> None:
    connection = op.get_bind()
    _actualizar_fks_postgresql(connection)
    _asegurar_indices(connection)


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tablas = set(inspector.get_table_names())
    for tabla, nombre, _columnas in reversed(INDICES):
        if tabla in tablas:
            existentes = {item["name"] for item in inspector.get_indexes(tabla)}
            if nombre in existentes:
                op.drop_index(nombre, table_name=tabla)
