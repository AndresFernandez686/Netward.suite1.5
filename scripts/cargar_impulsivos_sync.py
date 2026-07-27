"""Carga masiva de productos Impulsivo y sincronizacion a administrador.

Uso rapido:
python scripts/cargar_impulsivos_sync.py --usuario empleado1
"""

from __future__ import annotations

import argparse
import os
import sys
import zlib
from datetime import date, datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import app
from core.models import (
    db,
    Usuario,
    Producto,
    InventarioItem,
    HistorialMovimiento,
    InventarioSnapshot,
    SincronizacionLog,
)


def _cantidad_logica(nombre: str) -> int:
    """Genera cantidad estable y razonable segun tipo de producto."""
    n = nombre.lower()
    seed = zlib.crc32(nombre.encode("utf-8"))

    if "torta" in n:
        base, span = 2, 6
    elif "palito" in n:
        base, span = 30, 121
    elif "tentacion" in n:
        base, span = 20, 81
    elif "familiar" in n:
        base, span = 8, 31
    elif "yogurt" in n or "sin azucar" in n:
        base, span = 6, 25
    else:
        base, span = 10, 61

    return base + (seed % span)


def _resolver_usuario_tienda(usuario: str, tienda_id_arg: str | None):
    user = Usuario.query.filter_by(username=usuario, rol="empleado").first()
    if not user:
        raise RuntimeError(f"No existe empleado con username='{usuario}'.")
    tienda_id = tienda_id_arg or user.tienda_id
    if not tienda_id or tienda_id == "ALL":
        raise RuntimeError("El usuario no tiene tienda valida asignada.")
    return user, tienda_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga y sincroniza productos Impulsivo")
    parser.add_argument("--usuario", default="empleado1", help="Username empleado")
    parser.add_argument("--tienda", default=None, help="Tienda destino (opcional)")
    parser.add_argument("--fecha", default=date.today().isoformat(), help="Fecha inventario YYYY-MM-DD")
    parser.add_argument("--tipo", default="Diario", help="Tipo inventario: Diario/Semanal/Quincenal")
    parser.add_argument("--accion", default="solo_enviar", choices=["solo_enviar", "enviar_recibir"])
    args = parser.parse_args()

    with app.app_context():
        user, tienda_id = _resolver_usuario_tienda(args.usuario, args.tienda)
        cliente_id = user.cliente_id or "C001"

        productos = (
            Producto.query.filter_by(categoria="Impulsivo")
            .order_by(Producto.nombre.asc())
            .all()
        )
        if not productos:
            raise RuntimeError("No hay productos en categoria Impulsivo.")

        ahora = datetime.now()
        hora = ahora.strftime("%H:%M")
        fecha = args.fecha

        creados = 0
        actualizados = 0

        for p in productos:
            cantidad = float(_cantidad_logica(p.nombre))
            item = InventarioItem.query.filter_by(
                tienda_id=tienda_id,
                categoria="Impulsivo",
                producto=p.nombre,
            ).first()

            if item:
                item.cliente_id = cliente_id
                item.cantidad = cantidad
                item.ume = "Unidad"
                item.tipo_inventario = args.tipo
                item.fecha = fecha
                item.sinc_estado = "pendiente"
                actualizados += 1
            else:
                db.session.add(
                    InventarioItem(
                        cliente_id=cliente_id,
                        tienda_id=tienda_id,
                        categoria="Impulsivo",
                        producto=p.nombre,
                        cantidad=cantidad,
                        ume="Unidad",
                        tipo_inventario=args.tipo,
                        fecha=fecha,
                        sinc_estado="pendiente",
                    )
                )
                creados += 1

            db.session.add(
                HistorialMovimiento(
                    cliente_id=cliente_id,
                    fecha=fecha,
                    hora=hora,
                    usuario=args.usuario,
                    categoria="Impulsivo",
                    producto=p.nombre,
                    cantidad=cantidad,
                    modo="Unidad",
                    tipo_inventario=args.tipo,
                    detalle="Carga masiva automatica de impulsivos",
                    tienda_id=tienda_id,
                )
            )

        total_impulsivo = len(productos)

        snapshot = InventarioSnapshot.query.filter_by(
            fecha=fecha, tienda_id=tienda_id, usuario=args.usuario
        ).first()
        if snapshot:
            snapshot.total_items = total_impulsivo
            snapshot.tipo_inventario = args.tipo
        else:
            db.session.add(
                InventarioSnapshot(
                    cliente_id=cliente_id,
                    fecha=fecha,
                    tienda_id=tienda_id,
                    usuario=args.usuario,
                    tipo_inventario=args.tipo,
                    total_items=total_impulsivo,
                )
            )

        # Enviar al administrador: marcar como sincronizado solo los impulsivos de esta corrida.
        pendientes_impulsivo = InventarioItem.query.filter_by(
            cliente_id=cliente_id,
            tienda_id=tienda_id,
            categoria="Impulsivo",
            sinc_estado="pendiente",
        ).all()
        enviados = len(pendientes_impulsivo)
        for row in pendientes_impulsivo:
            row.sinc_estado = "sincronizado"

        db.session.add(
            SincronizacionLog(
                cliente_id=cliente_id,
                tienda_id=tienda_id,
                usuario=args.usuario,
                tipo="envio",
                accion=args.accion,
            )
        )

        if args.accion == "enviar_recibir":
            db.session.add(
                SincronizacionLog(
                    cliente_id=cliente_id,
                    tienda_id=tienda_id,
                    usuario=args.usuario,
                    tipo="recepcion",
                    accion=args.accion,
                )
            )

        db.session.commit()

        print("Carga masiva completada")
        print(f"Usuario: {args.usuario} | Cliente: {cliente_id} | Tienda: {tienda_id}")
        print(f"Productos impulsivo procesados: {total_impulsivo}")
        print(f"Inventario creado: {creados} | actualizado: {actualizados}")
        print(f"Enviados al administrador: {enviados}")


if __name__ == "__main__":
    main()
