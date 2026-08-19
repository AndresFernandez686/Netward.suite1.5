# Errores 02: `dif_anterior` inicializado

La auditoría se ejecutó sin período anterior y recorrió la búsqueda de compensaciones.

Esperado y obtenido:

- No se produjo `UnboundLocalError`.
- `diferencia_anterior_compensada=0`.

**APROBADO**.

Prueba: `test_dif_anterior_sin_periodo_previo_no_explota`.
