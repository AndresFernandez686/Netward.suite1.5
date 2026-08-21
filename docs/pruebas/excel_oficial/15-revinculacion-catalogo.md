# Revinculación después de actualizar el catálogo

## Caso

1. El Excel importa `Torta frutillas con crema` con código 1814.
2. El producto todavía no existe y la fila queda `sin_producto`.
3. El administrador agrega `Torta Frutilla` o sincroniza el catálogo.

## Resultado esperado

- Al agregar un producto la fila se detecta como cambio pendiente, pero todavía no
  se modifica el Excel.
- Una fila `sin_producto` no genera alerta por sí sola. Cuando se agrega un producto
  coincidente, la pantalla de Excel oficial y el menú muestran el contador porque la
  vinculación ya puede aplicarse.
- **Aplicar cambios** se habilita únicamente cuando hay renombres o filas que ya
  pueden vincularse.
- Al pulsar **Aplicar cambios**, el catálogo y las filas importadas se sincronizan.
- Cuando no hay cambios, **Aplicar cambios** permanece visible y desactivado.
- **Volver atrás** está siempre disponible.
- Los nombres se comparan normalizados, no mediante coincidencia literal sensible a
  mayúsculas o espacios.
- La fila queda `vinculado`, conserva `producto_id` y aprende el código 1814.
- `productos_nuevos` baja a cero y `estado_validacion` vuelve a `ok` cuando no quedan
  pendientes.
- Auditoría utiliza la relación nueva sin exigir que se vuelva a subir el archivo.

Automatización: `tests/test_excel_oficial.py`.
