# E2E 08: exportar Excel

Se generó el XLSX de auditoría mediante la misma función utilizada por la ruta de descarga y se volvió a abrir con `openpyxl`.

Resultado esperado y obtenido:

- Archivo XLSX válido con encabezado y una fila de datos.
- Producto correcto.
- Estado de auditoría `Justificado`.
- Justificación manual `Error de conteo` incluida.

**APROBADO**.

La generación fue extraída a `core/auditoria_export.py` para compartir exactamente la misma lógica entre la ruta y las pruebas.
