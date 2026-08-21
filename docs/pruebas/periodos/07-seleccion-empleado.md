# Períodos 07: selección persistente del empleado

## Objetivo

Garantizar que, cuando una tienda tenga dos períodos disponibles, el empleado
cargue, visualice y sincronice únicamente el período seleccionado.

## Validaciones

- El selector conserva marcada la opción activa después de cada recarga.
- La pantalla identifica claramente el número de período seleccionado.
- Cada formulario incluye el `periodo_id` visible al momento de la acción.
- El identificador del formulario prevalece sobre cambios de sesión causados por
  otra pestaña del navegador.
- La sincronización muestra el período destino y filtra el inventario pendiente
  por ese identificador.
- Dos cargas del mismo producto, una en cada período, conservan cantidades
  independientes en `conteo_detalle`.
- Las consultas compartidas muestran solamente las cargas del período activo.

## Resultado esperado

Seleccionar el período 1 y cargar 5 unidades no modifica el período 2. Al
seleccionar posteriormente el período 2 y cargar 9 unidades, cada período muestra
su propia cantidad y la auditoría puede analizarlos por separado.
