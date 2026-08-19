# Pruebas Heavy de grandes volúmenes

Fecha: 2026-08-19. Resultado: **2/2 pruebas aprobadas**.

Cada escenario se ejecutó dos veces, una de forma aislada y otra dentro de la regresión completa: **4/4 ejecuciones aprobadas**.

Los escenarios usan una base SQLite temporal aislada, modo WAL y medición con `tracemalloc`. Los límites automáticos son **menos de 60 segundos** por escenario y **menos de 300 MiB** de memoria pico atribuida.

1. [Inventario masivo](01-inventario-masivo.md)
2. [Historial extenso y períodos correlativos](02-historial-extenso.md)

Suite: `tests/test_heavy_volumen.py`.
