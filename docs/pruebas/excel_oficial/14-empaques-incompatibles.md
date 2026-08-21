# Presentaciones con cantidades incompatibles

## Caso

- Catálogo interno: `Cucurucho Nacional x54`.
- Excel oficial: `Cucuruchón nacional x 78 u`.
- El código 138 pudo haber quedado asociado por una importación anterior.

## Resultado esperado

- No se vinculan automáticamente porque 54 y 78 son cantidades distintas.
- La fila queda pendiente de vinculación y Auditoría no usa los valores bajo el
  producto x54.
- Si el código fue aprendido por la relación incorrecta, se libera.
- Las importaciones antiguas se corrigen al abrir sus datos extraídos.
- El administrador debe confirmar si se trata de un producto nuevo o actualizar el
  catálogo y volver a importar.

Automatización: `tests/test_excel_oficial.py`.
