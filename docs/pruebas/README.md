# Evidencias de pruebas del sistema

Fecha de ejecución: 2026-08-20.

Las pruebas se ejecutan con bases SQLite aisladas, en memoria o en archivos temporales; no modifican la base de datos real.

Comando:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Resultado general: **130 pruebas automatizadas disponibles**; la regresión de contexto de períodos fue validada correctamente.

## Flujo único del Excel oficial

La importación sin descarga automática y el consumo desde Auditoría están documentados en
[flujo definitivo de Excel oficial](excel_oficial/12-flujo-unico-desc.md).

## Notificación de carga de inventario

La ubicación del aviso inmediatamente antes de Productos cargados está documentada en
[notificación del inventario](notificacion_inventario.md).

## Navegación lateral

La persistencia del desplazamiento y la visibilidad de la opción activa están documentadas en
[persistencia del menú lateral](menu_lateral_scroll.md).

## Separación de configuración

La independencia visual entre Productos y Tiendas está documentada en
[separación de Productos y Tiendas](configuracion_secciones.md).

## Reinicio de períodos contables

La eliminación segura y recuperación mediante respaldo están documentadas en
[reinicio de períodos contables](reset_periodos_contables.md).

## Inventario administrativo por período

La selección del último período cargado por sucursal está documentada en
[inventario del último período](inventario_ultimo_periodo.md).

## Asistente explicativo de auditoría

Los siete escenarios de proveedores, fallback, aislamiento y trazabilidad están en el
[índice del asistente de IA](asistente_ia/README.md).

## Fallos parciales

1. [Red inestable y reintento](fallos_parciales/01-red-inestable.md)
2. [Delivery fuera de rango](fallos_parciales/02-delivery-fuera-rango.md)

## Permisos y seguridad

Los escenarios de roles, trazabilidad e inyección están documentados en el
[índice de permisos y seguridad](permisos_seguridad/README.md).

## Integridad transaccional

1. [Rollback total de sincronización](integridad_transaccional/01-rollback-sincronizacion.md)
2. [Importación Excel fallida](integridad_transaccional/02-importacion-excel-fallida.md)

## Casos límite

Los nueve escenarios defensivos están documentados en el
[índice de casos límite](casos_limite/README.md).

## Heavy: grandes volúmenes

1. [Inventario masivo](heavy_volumen/01-inventario-masivo.md)
2. [Historial extenso y períodos correlativos](heavy_volumen/02-historial-extenso.md)

## Heavy: concurrencia

1. [Múltiples empleados sobre el mismo producto](heavy_concurrencia/01-multiples-empleados.md)
2. [Importación Excel y auditoría en paralelo](heavy_concurrencia/02-excel-auditoria-paralelo.md)

## Inventario multi-empleado

1. [Continuidad entre empleados](inventario_multiempleado/01-continuidad-entre-empleados.md)
2. [Producto ya cargado](inventario_multiempleado/02-popup-producto-cargado.md)
3. [Sobreescritura confirmada](inventario_multiempleado/03-sobreescritura.md)
4. [Cancelación de sobreescritura](inventario_multiempleado/04-cancelacion.md)
5. [Sincronización multi-empleado](inventario_multiempleado/05-sincronizacion.md)
6. [Conflicto simultáneo](inventario_multiempleado/06-conflicto-simultaneo.md)
7. [Auditoría sin duplicación](inventario_multiempleado/07-auditoria-sin-duplicacion.md)
8. [Reporte gerencial trazable](inventario_multiempleado/08-reporte-gerencial.md)
9. [Borradores compartidos](inventario_multiempleado/09-borradores-compartidos.md)
10. [Aislamiento por empresa y tienda](inventario_multiempleado/10-aislamiento-empresa-tienda.md)

## Períodos

1. [Creación sin historial](periodos/01-creacion-sin-historial.md)
2. [Creación con historial](periodos/02-creacion-con-historial.md)
3. [Cierre con productos pendientes](periodos/03-cierre-con-pendientes.md)
4. [Cierre con todos los productos cargados](periodos/04-cierre-completo.md)
5. [Continuidad coincidente](periodos/05-continuidad-coincidente.md)
6. [Continuidad no coincidente](periodos/06-continuidad-no-coincidente.md)
7. [Selección persistente del período del empleado](periodos/07-seleccion-empleado.md)

## Excel oficial

1. [Importación de Excel válido](excel_oficial/01-importacion-valida.md)
2. [Importación con columnas faltantes](excel_oficial/02-columnas-faltantes.md)
3. [Importación con productos no vinculados](excel_oficial/03-productos-no-vinculados.md)
4. [Vinculación exacta](excel_oficial/04-vinculacion-exacta.md)
5. [Vinculación parcial](excel_oficial/05-vinculacion-parcial.md)
6. [Producto sin coincidencia](excel_oficial/06-sin-coincidencia.md)
7. [Cálculo de Venta Teórica](excel_oficial/07-venta-teorica.md)
8. [Venta Real con delivery](excel_oficial/08-venta-real-delivery.md)
9. [Venta Real sin delivery](excel_oficial/09-venta-real-excel.md)
10. [Cálculo de diferencia](excel_oficial/10-calculo-diferencia.md)
11. [Robustez de estructura y vinculación](excel_oficial/11-robustez-estructura-vinculacion.md)
12. [Flujo único desde Excel oficial](excel_oficial/12-flujo-unico-desc.md)
13. [Edición de datos extraídos](excel_oficial/13-editor-datos-extraidos.md)
14. [Presentaciones con cantidades incompatibles](excel_oficial/14-empaques-incompatibles.md)
15. [Revinculación después de actualizar el catálogo](excel_oficial/15-revinculacion-catalogo.md)

## Motor de auditoría

Los 25 escenarios funcionales y sus evidencias están enumerados en el
[índice del motor de auditoría](motor_auditoria/README.md).

## Averiados y vencimientos

Los cinco casos y sus evidencias están en el
[índice de averiados y vencimientos](averiados_vencimientos/README.md).

## Delivery

Los tres casos y sus evidencias están en el
[índice de delivery](delivery/README.md).

## Reporte gerencial

Los siete casos y sus evidencias están en el
[índice del reporte gerencial](reporte_gerencial/README.md).

## End-to-end

Las nueve etapas del flujo integral están documentadas en el
[índice end-to-end](end_to_end/README.md).

## Regresión

Los nueve puntos de regresión están documentados en el
[índice de regresión](regresion/README.md).

## Errores y bugs

Los cinco comportamientos de robustez están documentados en el
[índice de errores y bugs](errores_bugs/README.md).

## Auditoría correlativa

La compensación exacta entre períodos está documentada en el
[índice de auditoría correlativa](auditoria_correlativa/README.md).
