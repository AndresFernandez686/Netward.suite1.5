# Averiados y vencimientos 04: sincronización

## Preparación y pasos

1. Crear un averiado y un vencimiento en estado `pendiente`.
2. Ejecutar `procesar_sincronizacion()` con la acción `solo_enviar`.

## Resultado esperado

- `n_aver=1`, `n_venc=1` y `n_total=2`.
- Ambos registros cambian a `sinc_estado="sincronizado"`.

## Resultado obtenido

Los contadores y estados fueron correctos. **APROBADO**.

Prueba: `test_sincronizacion_cambia_ambos_estados`.
