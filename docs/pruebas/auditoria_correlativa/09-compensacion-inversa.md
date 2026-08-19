# Compensación correlativa inversa

## Objetivo

Validar que el motor reconozca la compensación inversa del mismo producto entre dos períodos consecutivos: un sobrante anterior de 20 unidades y un faltante actual de 20 unidades.

## Datos

Producto: `Alfajor Almendrado`.

Período 2:

- Stock esperado: `23`.
- Conteo final: `43`.
- Diferencia: `43 - 23 = +20` (`sobrante`).

Período 3:

- Stock inicial: `43`, igual al conteo final anterior.
- Otras salidas: `20`.
- Stock esperado: `43 - 20 = 23`.
- Conteo final: `3`.
- Diferencia: `3 - 23 = -20` (`faltante`).

## Resultado esperado y obtenido

- `diferencia_anterior_compensada = 20`.
- `tipo_diferencia = compensado`.
- `severidad = Correcto`.
- `impacto = 0`.
- `causa_sugerida = Compensación entre períodos`.
- `nivel_confianza = Alto`.
- `estado_auditoria = Sin diferencia real`.

Resultado: **Aprobado**.

Prueba automatizada: `test_sobrante_anterior_y_faltante_actual_quedan_compensados` en `tests/test_auditoria_correlativa.py`.
