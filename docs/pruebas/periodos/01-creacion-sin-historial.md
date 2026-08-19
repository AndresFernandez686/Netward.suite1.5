# Períodos 01: creación sin historial

## Objetivo

Comprobar que `retroalimentar_periodo_desde_items()` crea un registro pendiente para cada producto visible cuando no existen cargas anteriores.

## Preparación y pasos

1. Crear un producto visible.
2. Crear un período abierto sin movimientos ni inventarios sincronizados.
3. Ejecutar `retroalimentar_periodo_desde_items(periodo)`.
4. Consultar `conteo_detalle`.

## Resultado esperado

- Se importan 0 productos.
- Existe el `conteo_detalle` del producto.
- `fue_cargado=False` y `total_unidad_base=0`.
- El período continúa `Abierto`.

## Resultado obtenido

**APROBADO.** El sistema creó el placeholder pendiente y conservó el período abierto.

Prueba: `test_crear_periodo_sin_historial_deja_producto_pendiente`.
