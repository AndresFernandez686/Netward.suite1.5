# Informe Completo — Netward suite 1.3.1

Fecha: 2026-07-06

---

## 1. Visión General

Netward es un sistema web de gestión de inventario desarrollado en Flask para heladerías Grido.
Permite el control de stock por tienda, con soporte de múltiples unidades de empaque (UME)
y procesamiento automático de archivos de inventario del sistema POS.

---

## 2. Módulos del sistema

### 2.1 Autenticación
- Sistema de sesiones Flask con rol (`empleado` / `administrador`)
- Modo Beta: cualquier contraseña es válida
- Cada empleado tiene asignada una tienda; los admins acceden a todas

### 2.2 Inventario (Empleado)
- Categorías: Impulsivo (38 prod.), Por Kilos (35 prod.), Extras (26 prod.)
- Buscador tipo combobox con búsqueda por substring y por inicio de palabra
- Dropdown de opciones con `position: fixed` (no se corta por CSS Grid ni por cards)
- UME por categoría:
  - Impulsivo / Por Kilos: Unidad · Caja · Bulto
  - Extras: Unidad · Caja · Tira
- Conversión automática al seleccionar Caja o Bulto:
  - `Caja`: cantidad × unidades_por_caja
  - `Bulto`: cantidad × cajas_por_bulto × unidades_por_caja
- Carrito multi-UME: el mismo producto puede tener entradas Unidad, Caja y Bulto simultáneas
- Al guardar: se suman todas las cantidades convertidas → un único InventarioItem en unidades individuales
- Historial de auditoría: cada entrada del carrito genera un HistorialMovimiento con UME original y fórmula

### 2.3 Historial (Empleado y Admin)
- Registro cronológico de todos los movimientos
- Filtros por fecha, tipo de inventario, empleado
- Admin: filtro por tienda, exportación a Excel

### 2.4 Delivery (Empleado y Admin)
- Empleado registra ventas de delivery por producto
- Admin gestiona catálogo (precios, promociones, activar/desactivar)

### 2.5 Configuración (Admin)
- Gestión de tiendas: crear, activar/desactivar, establecer tienda default
- Catálogo de productos:
  - Agregar productos nuevos por categoría
  - Eliminar productos (con cascada a ProductoPrecio)
  - El catálogo actualizado es visible inmediatamente para empleados
- Precios y empaques por producto (solo Impulsivo y Extras):
  - Precio unitario en Gs. con formato 4.500 Gs.
  - Unid. x Caja: unidades individuales por caja
  - Cajas x Bulto: cajas que contiene un bulto
- Sincronización de nombres con Excel del POS:
  - Route `/admin/desc/sincronizar` muestra plan de renombrado
  - Aplicación con cascada a InventarioItem, ProductoPrecio y Snapshots

### 2.6 Módulo Desc. (Admin)
Procesamiento de archivos Excel exportados del sistema POS para reconciliación contable quincenal.

**Flujo:**
1. Admin sube `.xls/.xlsx` + selecciona tienda y rango de fechas
2. Sistema filtra grupos: Canjes, Congelados, Frizzio, Lineas especiales, Otros, Otros ingred., Promociones
3. Continuidad quincenal:
   - Si existe snapshot del mismo mes/tienda → SF anterior = SI actual
   - Si no → usa InventarioItem del sistema
4. Reemplaza ventareal con DeliveryVenta del período
5. Recalcula: `VT = SI + Compras + OtrosIngresos − SF − OtrasSalidas`
6. Calcula: `Diferencia = VT − VR`
7. Agrega columnas: vacío | Unid. x Caja | Cajas x Bulto
8. Guarda snapshot del SF para continuidad futura
9. Descarga `.xlsx` con colores (azul=sistema, verde=calculado, rojo/verde=diferencia)

---

## 3. Modelos de Base de Datos

| Tabla                       | Descripción                                 |
|-----------------------------|---------------------------------------------|
| `tiendas`                   | Sucursales del negocio                      |
| `usuarios`                  | Empleados y administradores                 |
| `productos`                 | Catálogo base de productos                  |
| `producto_precios`          | Precio y empaque por producto               |
| `inventario_items`          | Stock actual por producto/tienda            |
| `historial`                 | Registro de movimientos de inventario       |
| `inventario_snapshots`      | Resumen de cargas por fecha/usuario         |
| `delivery_productos`        | Catálogo de productos de delivery           |
| `delivery_ventas`           | Ventas de delivery registradas              |
| `stock_thresholds`          | Umbrales del semáforo de stock              |
| `inventario_desc_snapshots` | SF quincenal para continuidad en Desc.      |

---

## 4. Estructura de archivos

```
app.py                    # Rutas Flask y lógica de negocio
core/
  __init__.py
  models.py               # 11 modelos SQLAlchemy
  seed_data.py            # Catálogo inicial y datos de referencia
  inventario.py           # Blueprint Desc. (350+ líneas)
static/
  css/styles.css          # 650+ líneas CSS custom
  js/main.js
templates/
  base.html               # Layout con sidebar responsive
  login.html
  empleado_inventario.html   # Formulario con combobox + carrito multi-UME
  empleado_historial.html
  empleado_delivery.html
  admin_inventario.html
  admin_historial.html
  admin_delivery.html
  admin_configuracion.html   # Tabs Impulsivo/Extras/Por Kilos con precios
  admin_desc.html            # Upload Excel + leyenda + snapshots
  admin_sincronizar.html     # Vista previa de renombrado de catálogo
  icons/ (6 SVG)
instance/
  netward_empleado.db     # Base de datos SQLite
```

---

## 5. Dependencias

```
Flask 3.1.3
Flask-SQLAlchemy 3.1.1
SQLAlchemy 2.0.51
openpyxl 3.1.5
xlrd 2.0.2
python-dotenv 1.2.2
Werkzeug 3.1.8
python-dateutil 2.9.0
```

---

## 6. Decisiones de diseño destacadas

- **Conversión UME en `carrito_agregar`**: la conversión se realiza al agregar al carrito, no al guardar.
  El empleado ve la conversión antes de confirmar, evitando errores.

- **`position: fixed` para el dropdown**: el combo usa posicionamiento fijo relativo al viewport,
  calculando coordenadas con `getBoundingClientRect()`. Esto evita que el CSS Grid del formulario
  corte el dropdown cuando abre debajo de la tarjeta.

- **Regla de continuidad como snapshots**: el SF del inventario se guarda en
  `inventario_desc_snapshots` como JSON por tienda/mes. Esto permite múltiples inventarios del
  mismo mes sin colisiones y es eliminable individualmente desde la UI.

- **Nombres sincronizados con POS**: el catálogo usa los mismos nombres que el archivo `.xls` del
  POS para maximizar el matching automático en el módulo Desc.

