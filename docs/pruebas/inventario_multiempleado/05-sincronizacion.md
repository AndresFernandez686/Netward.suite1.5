# Sincronización multi-empleado

Empleado A y Empleado B guardan productos diferentes. A sincroniza primero y solamente envía su carga; la carga de B permanece pendiente. B sincroniza después.

Al finalizar existen dos `inventario_items` sincronizados y dos registros únicos y válidos en `conteo_detalle`, con sus respectivos usuarios.

Resultado: **Aprobado**.
