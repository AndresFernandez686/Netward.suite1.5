# Heavy 02: importación Excel y auditoría en paralelo

## Escenario

Mientras se importa `periodo-a-v2.xlsx`, otro hilo ejecuta la auditoría del mismo período. Un segundo período mantiene su propio Excel y resultados como control de aislamiento.

El Excel anterior contiene stocks `(10, 10)` y el nuevo `(20, 30)` para dos productos cuyo conteo es `(10, 10)`.

## Resultado esperado y obtenido

- La auditoría observa completamente el archivo anterior: diferencias `(0, 0)`; o completamente el nuevo: `(-10, -20)`.
- Nunca aparece una combinación mezclada como `(0, -20)` o `(-10, 0)`.
- Los dos archivos del período conservan exactamente dos detalles cada uno.
- El segundo período mantiene un solo archivo y sus resultados no cambian.
- No hay bloqueos ni corrupción de filas.

Resultado: **Aprobado en 5/5 ejecuciones**. Sin mezcla de períodos ni archivos.
