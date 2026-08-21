# Módulo: Motor de Auditoría

## Tablas involucradas
| Tabla | Descripción |
|---|---|
| `auditoria_resultados` | Un registro por producto por período con diagnóstico completo |
| `justificaciones` | Justificaciones manuales del administrador por resultado |
| `productos_relacionados` | Relaciones de consumo entre productos (alertas) |

## Relaciones
```
auditoria_resultados.periodo_id   → inventario_periodos.id
auditoria_resultados (1) ──< justificaciones  (FK: resultado_id)
Lee: conteo_detalle, ajustes_inventario, excel_detalles, registros_averiados, registros_vencimiento
```

## Fórmulas principales
```
Conteo Final    = conteo_empleado + ajuste_admin
Stock Inicial   = stock_final del período anterior  ← regla de continuidad
Stock Esperado  = stock_inicial + compras + otros_ingresos - ventas - otras_salidas - mermas - vencidos
Diferencia      = conteo_final - stock_esperado
Impacto         = |diferencia| × costo_unitario
```

## Causas sugeridas (prioridad)
| # | Causa | Evidencia típica |
|---|---|---|
| 1 | Inconsistencia de continuidad | stock_final anterior ≠ stock_inicial Excel |
| 2 | Compra mal cargada | compras > 3× promedio histórico |
| 3 | Compensación entre períodos | diferencia actual = −diferencia anterior del mismo producto |
| 4 | Error de conteo | compensación parcial con la diferencia anterior |
| 5 | Producto vencido | registros en `registros_vencimiento` |
| 6 | Merma o averiado | registros en `registros_averiados` |
| 7 | Producto relacionado incoherente | ratio consumo fuera de tolerancia |
| 8 | Canje no registrado | solo por justificación manual (requiere observación) |
| 9 | Pendiente de revisión | sin evidencia encontrada |

## Niveles de confianza
- **Alto**: evidencia fuerte y directa
- **Medio**: indicios parciales
- **Bajo**: sin evidencia clara

## Severidad
```
|diferencia| = 0          → Correcto
|diferencia| <= 5         → Observación
|diferencia| <= 20        → Revisar
|diferencia| > 20         → Crítico
```

## Rutas principales
| Método | Ruta | Acción |
|---|---|---|
| POST | `/admin/periodos/<id>/auditoria/ejecutar` | Corre motor completo, regenera todos los `auditoria_resultados` |
| GET | `/admin/periodos/<id>/auditoria` | Vista con filtros: todos / faltante / sobrante / compensado / crítico / pendiente |
| POST | `/admin/periodos/<id>/justificar/<resultado_id>` | Crea `justificacion`, cambia `estado_auditoria = 'Justificado'` |
| GET | `/admin/periodos/<id>/exportar` | Descarga Excel con todas las columnas de auditoría |

## Módulo backend
- `core/auditoria.py` — `ejecutar_auditoria(periodo)`, `build_reporte_gerencial(periodo)`

## Campos clave de `auditoria_resultados`
| Campo | Valores posibles | Quién lo asigna |
|---|---|---|
| `tipo_diferencia` | `faltante` / `sobrante` / `correcto` / `compensado` | Motor automático |
| `estado_auditoria` | `Pendiente` / `Sugerido` / `Justificado` / `Revisado` / `Sin diferencia` / `Sin diferencia real` | Motor + admin |
| `fuente_costo` | `Excel oficial` / `Precio interno` / `Sin costo` | Motor automático |
| `causa_sugerida` | ver tabla de causas | Motor automático |
| `nivel_confianza` | `Alto` / `Medio` / `Bajo` | Motor automático |
| `severidad` | `Correcto` / `Observación` / `Revisar` / `Crítico` | Motor automático |

**Transiciones de `estado_auditoria`:**
```
Motor corre:
  diferencia = 0           → Sin diferencia
  diferencia = -anterior   → Sin diferencia real (compensación exacta)
  causa != Pendiente       → Sugerido   (motor encontró evidencia)
  causa = Pendiente        → Pendiente  (sin evidencia)

Admin actua:
  POST /justificar         → Justificado
  POST /revisar            → Revisado   (vio pero no justifica formalmente)
```

**`fuente_costo`** indica por qué el impacto económico puede variar entre períodos:
- `Precio interno` → usa exclusivamente `producto_precios.precio`
- `Sin costo` → el impacto aparece como 0 / no calculable
