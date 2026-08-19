# Pruebas Heavy de concurrencia

Fecha: 2026-08-19. Resultado: **2/2 pruebas aprobadas**.

Las pruebas usan una base SQLite temporal compartida, conexiones independientes por hilo, modo WAL, una barrera de inicio simultáneo y límites de tiempo para detectar bloqueos.

Cada escenario se ejecutó cinco veces consecutivas: **10/10 ejecuciones concurrentes aprobadas**.

1. [Múltiples empleados](01-multiples-empleados.md)
2. [Excel y auditoría en paralelo](02-excel-auditoria-paralelo.md)

Suite: `tests/test_heavy_concurrencia.py`.
