# Mapa del sistema — Netward Suite 1.4

## Módulos y archivos clave

| Módulo | Tablas | Backend | Rutas |
|---|---|---|---|
| Catálogo | `productos`, `producto_precios`, `stock_thresholds` | `core/catalogo.py` | `/admin/configuracion`, `/admin/precios` |
| Inventario empleado | `inventario_items`, `historial`, `inventario_snapshots` | `core/empleado.py` | `/empleado/inventario`, `/empleado/sincronizar` |
| Períodos / Auditoría | `inventario_periodos`, `conteo_detalle`, `ajustes_inventario` | `core/scheduler.py`, `core/sync_bridge.py` | `/admin/periodos/*` |
| Excel oficial | `excel_importados`, `excel_detalles` | `core/excel_importer.py` | `/admin/periodos/<id>/excel/importar` |
| Motor de auditoría | `auditoria_resultados`, `justificaciones`, `productos_relacionados` | `core/auditoria.py` | `/admin/periodos/<id>/auditoria` |
| Averiados / Vencimientos | `registros_averiados`, `registros_vencimiento` | `core/empleado.py`, `core/admin_vencimientos.py` | `/empleado/averiado`, `/admin/averiados` |
| Delivery | `delivery_productos`, `delivery_ventas` | `core/empleado.py` | `/empleado/delivery`, `/admin/delivery` |
| Multi-tenant / Usuarios | `clientes`, `tiendas`, `usuarios` | `app.py` | `/login`, `/admin/usuarios` |
| Configuración sistema | `configuracion_sistema` | `core/scheduler.py` | `/admin/periodos/config/autoclose` |

## Flujo completo de auditoría
```
[Admin]
Crea período (inventario_periodos, estado='Abierto')
   ↓ Al crear: retroalimentar_periodo_desde_items()
     jala cargas ya sincronizadas dentro del rango → conteo_detalle

[Empleado]
Carga productos desde celular (inventario_items, sinc_estado='pendiente')
   ↓ Sincroniza
sinc_estado='sincronizado'
sync_bridge.propagar_conteo_a_periodo() → upsert en conteo_detalle del período activo
período pasa a estado='Pendiente'

[Admin]
   ↓ Cierra período (manual o auto-cierre por scheduler)
estado='Cerrado'
   ↓ Importa Excel oficial
excel_importados + excel_detalles, estado='Conciliado'
   ↓ Ejecuta auditoría
auditoria_resultados (causa_sugerida + evidencia + nivel_confianza + impacto + severidad + estado_auditoria), estado='Auditado'
   ↓ Admin justifica diferencias
justificaciones, estado_auditoria='Justificado'
   ↓ Gerente ve reporte / Admin exporta Excel
```

## Orden correcto del flujo
1. **Admin crea el período** con rango de fechas → el sistema jala cargas previas
2. **Empleado carga** desde celular (si no había cargado aún)
3. **Empleado sincroniza** → sync_bridge actualiza conteo_detalle
4. **Auto-cierre** o cierre manual del admin
5. **Admin importa Excel oficial** del sistema externo
6. **Admin ejecuta auditoría** → motor genera diagnóstico completo
7. **Admin justifica** diferencias relevantes
8. **Gerente descarga reporte** / Admin exporta Excel de auditoría

## Relaciones FK principales
```
clientes ──< tiendas ──< inventario_items
         ──< usuarios

inventario_periodos ──< conteo_detalle
                    ──< ajustes_inventario
                    ──< excel_importados ──< excel_detalles
                    ──< auditoria_resultados ──< justificaciones
```

## Base de datos
- **Desarrollo**: SQLite (`instance/netward_empleado.db`)
- **Producción**: PostgreSQL — ver `docs/modulo_migracion_postgres.md`
- Variable de entorno: `DATABASE_URL`

## Documentación por módulo
- `docs/modulo_catalogo.md`
- `docs/modulo_inventario_empleado.md`
- `docs/modulo_periodos.md`
- `docs/modulo_excel_oficial.md`
- `docs/modulo_auditoria.md`
- `docs/modulo_averiados_vencimientos.md`
- `docs/modulo_delivery.md`
- `docs/modulo_multitenant_usuarios.md`
- `docs/modulo_migracion_postgres.md`
