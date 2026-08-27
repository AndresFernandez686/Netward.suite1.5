"""Reglas compartidas para ajustes administrativos de inventario."""

MOTIVOS_BAJA_NO_IMPUTABLE = frozenset({
    "Merma o averiado ya registrado",
    "Producto vencido ya registrado",
})


def ajuste_es_baja_no_imputable(motivo: str) -> bool:
    """Indica que el ajuste solo documenta una baja ya aplicada a la venta teórica."""
    valor = str(motivo or "").strip().casefold()
    return valor in {motivo_valido.casefold() for motivo_valido in MOTIVOS_BAJA_NO_IMPUTABLE}
