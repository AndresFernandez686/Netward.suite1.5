"""Políticas pequeñas y comprobables de autorización."""


def rol_permitido(rol_actual: str | None, rol_requerido: str | None) -> bool:
    """Un rol requerido solo autoriza una coincidencia exacta."""
    return rol_requerido is None or rol_actual == rol_requerido
