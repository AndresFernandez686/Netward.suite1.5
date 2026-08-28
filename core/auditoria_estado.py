"""Detecta si una auditoría dejó de representar las fuentes actuales del período."""
from __future__ import annotations

import json

from .models import (
    AjusteInventario, AuditoriaResultado, ConfiguracionSistema, ConteoDetalle,
    ExcelDetalleEdicion, ExcelImportado, FacturaCompra, RegistroAveriado,
    RegistroVencimiento, db, utc_now,
)

CLAVE_CATALOGO = "auditoria_catalogo_actualizado"


def _marcar(cliente_id: str, clave: str, motivo: str, descripcion: str) -> None:
    registro = ConfiguracionSistema.query.filter_by(cliente_id=cliente_id, clave=clave).first()
    # ConfiguracionSistema.valor admite 255 caracteres también en PostgreSQL.
    motivo = str(motivo or "Fuente actualizada")[:170]
    valor = json.dumps({"motivo": motivo, "fecha": utc_now().isoformat()})
    if registro is None:
        db.session.add(ConfiguracionSistema(
            cliente_id=cliente_id, clave=clave, valor=valor, descripcion=descripcion,
        ))
    else:
        registro.valor = valor
        registro.actualizado = utc_now()


def marcar_cambio_auditoria(periodo_id: int, cliente_id: str, motivo: str) -> None:
    _marcar(
        cliente_id, f"auditoria_periodo_{periodo_id}", motivo,
        "Último cambio que obliga a re-ejecutar la auditoría",
    )


def marcar_cambio_catalogo(cliente_id: str, motivo: str = "Catálogo sincronizado") -> None:
    _marcar(
        cliente_id, CLAVE_CATALOGO, motivo,
        "Último cambio de catálogo que puede afectar auditorías",
    )


def _motivo_config(registro, fallback: str) -> str:
    if registro is None:
        return fallback
    try:
        return str(json.loads(registro.valor or "{}").get("motivo") or fallback)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def estado_actualizacion_auditoria(periodo, *, catalogo_pendiente: bool = False) -> dict:
    """Compara la última ejecución con todas las fuentes que alimentan el motor."""
    ultima = db.session.query(db.func.max(AuditoriaResultado.creado)).filter(
        AuditoriaResultado.periodo_id == periodo.id,
        AuditoriaResultado.cliente_id == periodo.cliente_id,
    ).scalar()
    ubicacion = "Auditoría → abrir período → barra superior"
    pasos = [
        "Revisa los cambios indicados y completa cualquier dato documental pendiente.",
        "Abre la Auditoría de este período.",
        "Pulsa el botón rojo «Re-ejecutar auditoría» y revisa los resultados actualizados.",
    ]
    if ultima is None:
        return {"ejecutada": False, "desactualizada": False,
                "ultima_ejecucion": None, "ultima_actualizacion": None,
                "motivos": [], "ubicacion": ubicacion, "pasos": pasos}

    fuentes = [
        (db.session.query(db.func.max(ExcelImportado.fecha_importacion)).filter_by(
            periodo_id=periodo.id, cliente_id=periodo.cliente_id).scalar(),
         "Excel oficial reemplazado o importado"),
        (db.session.query(db.func.max(ExcelDetalleEdicion.creado)).filter_by(
            periodo_id=periodo.id, cliente_id=periodo.cliente_id).scalar(),
         "Datos del Excel oficial modificados"),
        (db.session.query(db.func.max(FacturaCompra.fecha_importacion)).filter_by(
            periodo_id=periodo.id, cliente_id=periodo.cliente_id).scalar(),
         "Factura PDF agregada"),
        (db.session.query(db.func.max(FacturaCompra.analisis_fecha)).filter_by(
            periodo_id=periodo.id, cliente_id=periodo.cliente_id).scalar(),
         "Factura PDF analizada o corregida"),
        (db.session.query(db.func.max(ConteoDetalle.fecha_carga)).filter_by(
            periodo_id=periodo.id, cliente_id=periodo.cliente_id).scalar(),
         "Conteo físico actualizado"),
        (db.session.query(db.func.max(AjusteInventario.fecha_ajuste)).filter_by(
            periodo_id=periodo.id, cliente_id=periodo.cliente_id).scalar(),
         "Ajuste administrativo agregado"),
        (db.session.query(db.func.max(RegistroAveriado.creado)).filter(
            RegistroAveriado.cliente_id == periodo.cliente_id,
            RegistroAveriado.tienda_id == periodo.tienda_id,
            RegistroAveriado.fecha >= periodo.fecha_desde,
            RegistroAveriado.fecha <= periodo.fecha_hasta,
        ).scalar(), "Averiado o merma registrado"),
        (db.session.query(db.func.max(RegistroVencimiento.creado)).filter(
            RegistroVencimiento.cliente_id == periodo.cliente_id,
            RegistroVencimiento.tienda_id == periodo.tienda_id,
            RegistroVencimiento.fecha >= periodo.fecha_desde,
            RegistroVencimiento.fecha <= periodo.fecha_hasta,
        ).scalar(), "Vencimiento registrado"),
    ]
    marca_periodo = ConfiguracionSistema.query.filter_by(
        cliente_id=periodo.cliente_id, clave=f"auditoria_periodo_{periodo.id}").first()
    fuentes.append((marca_periodo.actualizado if marca_periodo else None,
                    _motivo_config(marca_periodo, "Fuente documental actualizada")))
    marca_catalogo = ConfiguracionSistema.query.filter_by(
        cliente_id=periodo.cliente_id, clave=CLAVE_CATALOGO).first()
    fuentes.append((marca_catalogo.actualizado if marca_catalogo else None,
                    _motivo_config(marca_catalogo, "Catálogo sincronizado")))

    motivos = []
    fechas_posteriores = []
    for fecha, motivo in fuentes:
        if fecha is not None and fecha > ultima:
            fechas_posteriores.append(fecha)
            if motivo not in motivos:
                motivos.append(motivo)
    if catalogo_pendiente:
        motivos.append("Hay cambios de catálogo pendientes de revisar y sincronizar")
    return {"ejecutada": True, "desactualizada": bool(motivos),
            "ultima_ejecucion": ultima,
            "ultima_actualizacion": max(fechas_posteriores, default=None),
            "motivos": motivos, "ubicacion": ubicacion, "pasos": pasos}
