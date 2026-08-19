# Reporte gerencial 01: total de pérdida

## Datos

Faltantes con impactos 100, 300 y 200. También se creó un sobrante con impacto 999 para comprobar que no se incluya.

## Resultado esperado

`100 + 300 + 200 = 600`.

## Resultado obtenido

`total_perdida=600`; el sobrante fue excluido. **APROBADO**.

Prueba: `test_total_perdida_suma_solo_impactos_faltantes`.
