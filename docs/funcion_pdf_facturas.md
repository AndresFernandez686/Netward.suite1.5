# Función PDF para facturas de compras

## Objetivo

La función PDF de **Documentación Oficial** permite cargar facturas de compras y
extraer automáticamente la información necesaria para completar la columna
`Compras` del inventario oficial.

Su finalidad es reducir errores humanos y mantener evidencia verificable de las
compras utilizadas por el motor de Auditoría.

## Proveedores admitidos

Actualmente se reconocen dos formatos:

- **Helacor**: productos de las categorías Impulsivo y Por Kilos.
- **Fane**: productos de la categoría Extras.

Si el proveedor no puede identificarse, el PDF se rechaza sin modificar los datos
del período.

## Carga de archivos

Desde **Documentación Oficial → Facturas de compras** el administrador puede:

1. Seleccionar el período contable.
2. Elegir una o varias facturas PDF.
3. Pulsar **Leer facturas y detectar compras**.
4. Revisar los resultados extraídos.
5. Corregir vínculos o conversiones dudosas.
6. Pulsar **Aplicar compras detectadas**.

Límites actuales:

- hasta 20 facturas por operación;
- máximo 15 MB por PDF;
- máximo 60 MB para el lote completo.

## Información extraída

Por cada factura se almacena:

- proveedor;
- número de factura;
- fecha de emisión;
- importe total;
- nombre del archivo;
- método de extracción;
- PDF original;
- usuario que realizó la importación;
- fecha de carga.

Por cada producto se extrae:

- código del proveedor;
- descripción original;
- cantidad facturada;
- precio unitario;
- importe de la línea;
- factor de conversión UME;
- compra calculada;
- producto relacionado en Netward;
- estado y nivel de confianza.

## Lectura del PDF y OCR

El sistema utiliza dos métodos:

### PDF digital

Primero intenta leer el texto incorporado en el documento. Este método es más
rápido y preciso y se utiliza con las facturas electrónicas de ejemplo.

### PDF escaneado

Si el archivo no contiene texto suficiente, sus páginas se convierten en imágenes
y se procesan mediante Tesseract OCR.

Para habilitar OCR en Windows, instala Tesseract con el idioma español. Si el
ejecutable no está disponible en `PATH`, agrega en `.env`:

```dotenv
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

Los PDF digitales pueden procesarse aunque Tesseract no esté instalado.

## Conversión a la unidad del inventario

Las facturas pueden registrar cajas o packs mientras que el inventario cuenta
unidades. Por eso se conserva un factor de conversión:

```text
Compra calculada = Cantidad facturada × Factor UME
```

Ejemplo:

```text
Cantidad facturada: 2 cajas
Factor UME: 48 unidades por caja
Compra calculada: 96 unidades
```

El factor se detecta a partir del código y la descripción de la presentación. El
administrador puede corregirlo antes de aplicar la compra.

## Vinculación de productos

El sistema intenta relacionar cada línea en este orden:

1. código conocido del proveedor;
2. descripción del producto;
3. alias utilizado por el inventario oficial;
4. coincidencia única de nombre y presentación.

No se acepta automáticamente una relación si:

- hay varias coincidencias posibles;
- la presentación es incompatible, por ejemplo `x54` frente a `x78`;
- el producto no existe en el catálogo;
- la categoría no corresponde al proveedor;
- el factor UME necesita confirmación.

Estas líneas quedan pendientes para revisión manual.

## Estados

### Estado de la factura

- `procesada`: leída correctamente y dentro del período.
- `fuera_rango`: la fecha no corresponde al período seleccionado.
- `aplicada`: todas sus compras válidas fueron aplicadas.
- `aplicada_parcial`: se aplicaron líneas válidas, pero quedan pendientes.
- `fallida`: no pudo procesarse correctamente.

### Estado de una línea

- `vinculado`: producto y conversión listos.
- `pendiente`: no existe una coincidencia segura.
- `pendiente_conversion`: debe confirmarse el factor UME.
- `categoria_invalida`: el proveedor no corresponde a la categoría.
- `fuera_rango`: pertenece a una factura fuera del período.
- `aplicado`: el valor fue trasladado a Compras.

## Validación del período

La fecha de emisión debe estar comprendida entre `fecha_desde` y `fecha_hasta` del
período contable.

Una factura fuera de rango se conserva como evidencia, pero no modifica Compras ni
se mezcla con otro período.

## Aplicación en Compras

La lectura del PDF no cambia inmediatamente el inventario. El administrador debe
pulsar **Aplicar compras detectadas** después de revisar la tabla.

Al aplicar:

1. se toman únicamente facturas dentro del período;
2. se ignoran líneas pendientes o incompatibles;
3. se suman las compras confirmadas por producto;
4. se busca el producto correspondiente en el último inventario XLS/XLSX;
5. se reemplaza el valor de `excel_detalles.compras`;
6. se registra el valor anterior y el nuevo;
7. Auditoría utilizará el resultado en su próxima ejecución.

Si ocurre un error, la transacción se revierte completamente.

## Prevención de duplicados

Cada PDF se identifica mediante un hash SHA-256. El mismo documento no puede
cargarse dos veces para una empresa, aunque se cambie el nombre del archivo.

## Seguridad y trazabilidad

- Solo los administradores pueden usar las rutas de facturas.
- Las consultas se aíslan por empresa y período.
- Se valida que el contenido comience como un PDF real.
- El PDF almacenado se entrega con restricciones de contenido.
- Cada modificación de Compras se registra en `excel_detalle_ediciones` con origen
  `facturas_pdf`.
- El PDF original permanece disponible como evidencia.

## Tablas de base de datos

### `facturas_compra`

Almacena la cabecera, el documento original, el hash, la fecha, el proveedor y el
estado general.

### `facturas_compra_detalles`

Almacena las líneas extraídas, conversiones, productos vinculados y estados.

Para una instalación PostgreSQL existente ejecuta:

```powershell
psql -U usuario -d netward -f migracion/12_documentacion_oficial_facturas.sql
```

## Dependencias

Las dependencias están declaradas en `requirements.txt`:

- `pdfplumber`;
- `pypdf`;
- `pypdfium2`;
- `pytesseract`;
- `Pillow`.

Instalación:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Archivos relacionados

- Lector y reglas: `core/factura_ocr.py`.
- Rutas: `core/inventario.py`.
- Modelos: `core/models.py`.
- Interfaz: `templates/admin_desc.html`.
- Estilos responsive: `static/css/admin.css`.
- Migración PostgreSQL: `migracion/12_documentacion_oficial_facturas.sql`.
- Pruebas: `tests/test_facturas_ocr.py`.

## Pruebas automatizadas

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_facturas_ocr -v
```

Las pruebas verifican ambos proveedores, las líneas extraídas, fechas fuera del
período, conversiones, aplicación de Compras, trazabilidad, duplicados y permisos.
