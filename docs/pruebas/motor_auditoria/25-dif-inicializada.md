# Auditoría 25: inicialización segura de `dif_anterior`

Se ejecutó la rama `Sin diferencia`, que anteriormente podía llegar al guardado sin asignar `dif_anterior`.

Esperado: sin `UnboundLocalError` y `diferencia_anterior_compensada=0`.

Resultado: la variable estuvo inicializada. **APROBADO**.

Prueba: `test_dif_anterior_inicializado_en_rama_sin_diferencia`.
