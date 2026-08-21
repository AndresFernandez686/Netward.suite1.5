# Documentación Oficial

## Objetivo

Este módulo reúne las fuentes utilizadas por Auditoría:

- inventario oficial XLS/XLSX;
- facturas PDF de compras;
- datos extraídos y modificaciones trazables.

La columna `compras` del inventario deja de depender de una carga manual cuando el
administrador aplica las compras detectadas en las facturas.

## Proveedores admitidos

- **Helacor**: productos de Impulsivo y Por Kilos.
- **Fane**: productos de Extras.

Se pueden seleccionar hasta 20 facturas en una carga. Cada PDF tiene un límite de
15 MB y el lote completo de 60 MB. El hash SHA-256 impide cargar dos veces el mismo
documento, incluso si fue renombrado.

## Lectura y OCR

1. El sistema intenta leer el texto digital del PDF.
2. Si el documento es una imagen, renderiza sus páginas y usa Tesseract OCR.
3. Detecta proveedor, número, fecha, total y líneas de productos.
4. Calcula las unidades compradas como `cantidad facturada × factor UME`.
5. Vincula únicamente coincidencias confiables; las dudosas requieren confirmación.

Para PDF escaneados instala Tesseract con el idioma español. Si no está disponible
en `PATH`, configura:

```dotenv
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

Los PDF digitales, como los ejemplos Helacor y Fane, no necesitan Tesseract.

## Aplicación de compras

Las facturas se pueden revisar sin modificar el inventario. El botón **Aplicar
compras detectadas** suma las líneas válidas por producto y reemplaza `compras` en
el último inventario oficial del mismo período.

- Las facturas fuera del rango del período no se aplican.
- Las líneas pendientes o de categoría incompatible no se aplican.
- Si un producto no está en el XLS/XLSX, queda informado y no se crea una fila
  artificial.
- Cada cambio queda registrado en `excel_detalle_ediciones` con origen
  `facturas_pdf`.
- La operación es transaccional: ante un error se revierte completamente.

Auditoría utiliza los nuevos valores la próxima vez que se ejecuta.

## Persistencia

- `facturas_compra`: cabecera, PDF original, hash, proveedor, fecha y método de
  extracción.
- `facturas_compra_detalles`: producto detectado, cantidad, factor, compra
  calculada, vínculo y confianza.

Para PostgreSQL existente ejecuta:

```powershell
psql -U usuario -d netward -f migracion/12_documentacion_oficial_facturas.sql
```
