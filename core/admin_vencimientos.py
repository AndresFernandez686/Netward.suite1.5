"""Lógica de negocio para vencimientos administrativos."""
from datetime import date

from core.models import RegistroVencimiento


def build_admin_vencimientos_context(*, cliente_id: str, tiendas, tienda_f: str,
                                     desde: str, hasta: str, local_notice=None):
    """Calcula el contexto de la vista de vencimientos."""
    q = RegistroVencimiento.query.filter_by(
        cliente_id=cliente_id,
        sinc_estado="sincronizado",
    )
    if tienda_f != "Todas":
        q = q.filter_by(tienda_id=tienda_f)
    q = q.filter(
        RegistroVencimiento.fecha >= desde,
        RegistroVencimiento.fecha <= hasta,
    )
    # Las fechas se guardan en formato ISO (AAAA-MM-DD), por lo que el orden
    # ascendente coloca primero los vencimientos más próximos.
    registros = q.order_by(
        RegistroVencimiento.fecha_vencimiento.asc(),
        RegistroVencimiento.creado.desc(),
    ).all()

    return {
        "registros": registros,
        "tiendas": tiendas,
        "tienda_f": tienda_f,
        "desde": desde,
        "hasta": hasta,
        "hoy": date.today().isoformat(),
        "local_notice": local_notice,
        "notif_vencimientos": 0,
        "hide_global_flash": True,
    }


def marcar_vencimientos_vistos(cliente_id: str) -> int:
    """Marca como revisados los vencimientos sincronizados aún no vistos."""
    revisados = (
        RegistroVencimiento.query.filter_by(
            cliente_id=cliente_id,
            sinc_estado="sincronizado",
            revisado=False,
        ).update({"revisado": True}, synchronize_session=False)
    )
    return revisados


def marcar_vencimientos_filtrados(cliente_id: str, tienda_f: str, desde: str, hasta: str) -> int:
    """Marca como revisados los vencimientos que coinciden con el filtro actual."""
    q = RegistroVencimiento.query.filter(
        RegistroVencimiento.cliente_id == cliente_id,
        RegistroVencimiento.sinc_estado == "sincronizado",
        RegistroVencimiento.revisado.is_(False),
        RegistroVencimiento.fecha >= desde,
        RegistroVencimiento.fecha <= hasta,
    )
    if tienda_f != "Todas":
        q = q.filter(RegistroVencimiento.tienda_id == tienda_f)
    return q.update({"revisado": True}, synchronize_session=False)
