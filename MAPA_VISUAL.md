# Mapa Visual del Sistema — Netward suite 1.3.1

## Flujo de roles

```
        LOGIN
          |
    ------+------
    |            |
EMPLEADO    ADMINISTRADOR
    |            |
    +-- Inventario        +-- Inventario (vista admin)
    +-- Historial         +-- Historial + exportar Excel
    +-- Delivery          +-- Delivery (catálogo + ventas)
                          +-- Configuración (tiendas + catálogo)
                          +-- Desc. (procesamiento Excel quincenal)
```

## Flujo de inventario del empleado

```
Empleado abre Inventario
      |
Selecciona categoría (Impulsivo / Por Kilos / Extras)
      |
Busca producto → elige UME
      |
      +-- Unidad  → cantidad directa
      +-- Caja    → cantidad × unid_por_caja  = unidades individuales
      +-- Bulto   → cantidad × cajas_por_bulto × unid_por_caja = unid. individuales
      |
Agrega al carrito (múltiples UMEs del mismo producto conviven)
      |
Carrito muestra subtotal en unidades individuales por producto
      |
"Actualizar inventario" → guarda suma total en InventarioItem
```

## Flujo del módulo Desc. (quincenal)

```
Admin sube .xls del POS
      |
Sistema lee archivo con xlrd
      |
Filtra grupos irrelevantes (Canjes, Promociones, Frizzio, etc.)
      |
¿Existe snapshot del mismo mes/tienda?
      |
    SÍ → usa SF anterior como SI (continuidad quincenal)
    NO  → usa InventarioItem del sistema como SI
      |
Reemplaza ventareal con DeliveryVenta del período
      |
Recalcula: VT = SI + Compras + OtrosIngresos − SF − OtrasSalidas
           Dif = VT − VR
      |
Guarda nuevo snapshot (SF actual → SI del próximo inventario)
      |
Descarga .xlsx coloreado
```

## Arquitectura de datos

```
Tienda (1) ──── (N) InventarioItem
                       producto (str)
                       cantidad (float) ← siempre en unidades individuales
                       ume = "Unidad"

Tienda (1) ──── (N) HistorialMovimiento
                       modo = UME original (Unidad/Caja/Bulto)
                       detalle = fórmula de conversión

Producto (N) ─ ProductoPrecio (1)
                       precio (float Gs.)
                       unidades_por_caja (float)
                       unidades_por_bulto = cajas_por_bulto (float)

Tienda+Mes (1) ─ InventarioDescSnapshot (N)
                       stock_final_json = {nombre_lower: float}
```

## Configuración de UME (admin)

```
Almendrado x unidad
  unidades_por_caja  = 8   → 1 Caja  = 8 unidades
  unidades_por_bulto = 6   → 1 Bulto = 6 cajas = 48 unidades

Empleado carga 2 Bulto + 4 Caja + 5 Unidad:
  2 × 6 × 8 = 96
  4 × 8     = 32
  5 × 1     =  5
  ─────────────
  Total     = 133 unidades  ← guardado en InventarioItem
```

