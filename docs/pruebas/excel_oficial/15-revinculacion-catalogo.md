# Revinculación después de actualizar el catálogo

## Caso

1. El Excel importa `Torta frutillas con crema` con código 1814.
2. El producto todavía no existe y la fila queda `sin_producto`.
3. El administrador agrega `Torta Frutilla` o sincroniza el catálogo.

## Resultado esperado

- Al agregar un producto se reintentan las filas pendientes de la empresa.
- Al sincronizar el catálogo también se reintentan las filas ya importadas.
- Los nombres se comparan normalizados, no mediante coincidencia literal sensible a
  mayúsculas o espacios.
- La fila queda `vinculado`, conserva `producto_id` y aprende el código 1814.
- `productos_nuevos` baja a cero y `estado_validacion` vuelve a `ok` cuando no quedan
  pendientes.
- Auditoría utiliza la relación nueva sin exigir que se vuelva a subir el archivo.

Automatización: `tests/test_excel_oficial.py`.
