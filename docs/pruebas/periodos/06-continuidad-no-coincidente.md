# Períodos 06: continuidad no coincidente

## Objetivo

Comprobar que una diferencia entre el cierre de N y el stock inicial oficial de N+1 active la alerta de continuidad.

## Preparación y pasos

1. Crear el período N cerrado con conteo final 10.
2. Crear el período N+1 con stock inicial de Excel igual a 7.
3. Ejecutar el motor de auditoría para N+1.

## Resultado esperado

- El motor detecta la diferencia 10 frente a 7.
- `alerta_continuidad=True`.

## Resultado obtenido

**APROBADO.** La inconsistencia fue detectada y marcada.

Prueba: `test_continuidad_distinta_genera_alerta`.
