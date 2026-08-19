# Importación Excel fallida sin datos parciales

## Escenario

Se inició una importación de tres productos y se inyectó una excepción al agregar la segunda fila del detalle.

## Validaciones

- Se revirtieron todos los `excel_detalles` creados parcialmente.
- Se revirtieron los códigos de artículo vinculados durante el intento.
- El período permaneció `Abierto`; no avanzó a `Excel Importado`.
- Quedó una sola cabecera en `excel_importados`.
- La cabecera conservó el nombre del archivo y `estado_validacion = fallido`.

## Resultado

**APROBADO**: no quedaron datos parciales. Después del rollback se guardó únicamente la evidencia del intento fallido.

Prueba: `test_error_intermedio_excel_deja_solo_cabecera_fallida`.
