# Resumen Ejecutivo — Netward suite 1.3.1

## Descripción del sistema

Netward es un sistema web de gestión de inventario multi-tienda diseñado para cadenas de heladerías
Grido. Permite a empleados registrar el stock físico y a administradores analizar, procesar y
exportar datos de inventario para conciliación contable.

---

## Módulos funcionales

### 1. Empleado — Inventario
- Carga de productos por categoría (Impulsivo, Por Kilos, Extras)
- Soporte de UME mixtas para el mismo producto:
  - **Unidad**: cantidad directa
  - **Caja**: se multiplica por `Unid. x Caja` configurado por admin → guarda unidades individuales
  - **Bulto**: se multiplica por `Cajas x Bulto × Unid. x Caja` → guarda unidades individuales
- El sistema muestra la conversión en tiempo real antes de confirmar
- Múltiples entradas del mismo producto con distinto UME se suman al guardar

### 2. Empleado — Delivery
- Registro de ventas de delivery por producto
- Vista de ventas del día y total diario por tienda

### 3. Admin — Inventario
- Vista consolidada por tienda y categoría
- Semáforo de stock (crítico / medio / suficiente) por producto
- Exportación a Excel del inventario completo

### 4. Admin — Historial
- Registro completo de todos los movimientos (modo, cantidad, UME original, detalles de conversión)
- Filtros por tienda, empleado, tipo y rango de fechas
- Exportación a Excel

### 5. Admin — Configuración
- Gestión de tiendas (crear, activar/desactivar, establecer default)
- Catálogo de productos: agregar, eliminar, renombrar
- Precio unitario en Gs. (con formato 4.500 Gs.) por producto
- **Unid. x Caja**: unidades individuales por caja
- **Cajas x Bulto**: cajas que contiene un bulto
- Sincronización de nombres entre sistema y Excel del POS

### 6. Admin — Desc. (Descarga / Procesamiento Quincenal)
- Carga de archivo `.xls/.xlsx` exportado del POS
- Filtrado automático de grupos irrelevantes
- Regla de continuidad quincenal: SF anterior → SI nuevo
- Reemplazo de stock inicial y ventas reales con datos del sistema
- Recálculo de venta teórica y diferencia
- Exportación del resultado como `.xlsx` con colores indicadores
- Historial de snapshots para auditoría de continuidad

---

## Estadísticas del catálogo

| Categoría  | Cantidad |
|------------|----------|
| Impulsivo  | 38 productos |
| Por Kilos  | 35 productos |
| Extras     | 26 productos |
| **Total**  | **99 productos** |

Tiendas: 2 (Seminario, Mcal Lopez)
Usuarios: 6 (4 empleados, 2 administradores)

---

## Tecnologías

| Componente   | Tecnología                    |
|--------------|-------------------------------|
| Backend      | Python 3.14 + Flask 3.x       |
| Base de datos| SQLite vía SQLAlchemy 2.x     |
| Frontend     | Jinja2 + CSS propio + JS vanilla |
| Excel I/O    | openpyxl (write) + xlrd (read xls) |
| Entorno      | uv + virtualenv               |

---

## Changelog (sesión actual)

- Migración completa de Streamlit → Flask
- Arquitectura de paquete `core/` (models, seed_data, inventario)
- Sistema de conversión UME: Unidad / Caja / Bulto con factores configurables por admin
- Carrito multi-UME: permite cargar el mismo producto con distintas UMEs
- Módulo Desc. con regla de continuidad quincenal y snapshots
- Sincronización de nombres de productos con archivo Excel del POS
- Buscador de productos con `position: fixed` para evitar corte por CSS Grid
- Renombrado de 43 productos del sistema para coincidir con el POS

