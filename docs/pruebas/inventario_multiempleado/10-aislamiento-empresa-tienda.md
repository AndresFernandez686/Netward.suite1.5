# Aislamiento por empresa y tienda

Se crean simultáneamente tres borradores:

- Un empleado del cliente y tienda actuales.
- Un empleado del mismo cliente, pero de otra tienda.
- Un empleado de otra empresa, aunque use el mismo identificador de tienda y período.

La carga compartida devuelve únicamente al empleado cuya combinación coincide exactamente en `cliente_id`, `tienda_id` y `periodo_id`.

Resultado: **Aprobado**. No se muestran productos de otras tiendas ni empresas.
