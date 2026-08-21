# Pruebas de Documentación Oficial y facturas PDF

## Lectura de formatos

- Factura Helacor: detecta proveedor, número, fecha, total y 16 líneas.
- Factura Fane: detecta proveedor, número, fecha, total y 13 líneas.
- PDF digital: utiliza el texto incrustado.
- PDF escaneado: intenta OCR mediante Tesseract.
- Proveedor desconocido o archivo que no sea PDF: se rechaza sin datos parciales.

## Carga múltiple

- Permite hasta 20 PDF en una misma selección.
- Conserva cada PDF y sus líneas en el período seleccionado.
- Un error revierte el lote completo.
- El hash SHA-256 rechaza una factura repetida aunque tenga otro nombre.

## Período y proveedor

- Una fecha fuera de `fecha_desde`/`fecha_hasta` queda `fuera_rango` y no se aplica.
- Helacor admite productos Impulsivo y Por Kilos.
- Fane admite productos Extras.
- Una categoría incompatible queda pendiente de revisión.

## Conversión y vinculación

- Guarda cantidad facturada, factor UME y compra calculada.
- Los códigos conocidos tienen prioridad.
- Los productos futuros pueden vincularse por una coincidencia única y compatible
  de descripción/presentación.
- Una coincidencia dudosa no se aplica automáticamente.
- El administrador puede corregir producto, cantidad y factor.

## Aplicación de Compras

- Suma las facturas válidas por producto.
- Reemplaza `excel_detalles.compras` únicamente para productos confirmados.
- Ignora filas pendientes y facturas fuera de rango.
- Registra antes/después con `origen = facturas_pdf`.
- Auditoría consume el valor nuevo en la próxima ejecución.

## Evidencia automatizada

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_facturas_ocr -v
```

Resultado esperado: cinco casos aprobados con los PDF reales de Helacor y Fane.
