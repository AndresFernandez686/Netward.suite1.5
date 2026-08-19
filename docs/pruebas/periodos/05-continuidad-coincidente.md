# Períodos 05: continuidad coincidente

## Objetivo

Verificar que el stock final del período N pueda utilizarse como stock anterior de N+1 sin generar alerta cuando coincide con el stock inicial oficial.

## Preparación y pasos

1. Crear el período N cerrado con conteo final 10.
2. Crear el período N+1 con stock inicial de Excel igual a 10.
3. Ejecutar el motor de auditoría para N+1.

## Resultado esperado

- `stock_inicial_anterior=10`.
- `stock_inicial_excel=10`.
- `alerta_continuidad=False`.

## Resultado obtenido

**APROBADO.** Los valores coinciden y no se generó alerta.

Prueba: `test_continuidad_coincidente_no_genera_alerta`.
