# Conflicto simultáneo

Empleado A y Empleado B preparan el mismo producto sobre la versión inicial `0`. A guarda primero y crea la versión `1`. El intento de B queda obsoleto y es rechazado con conflicto.

También se captura la colisión de la restricción única si ambas inserciones llegan juntas a la base de datos, convirtiéndola en el mismo pop-up en lugar de un error del servidor.

Resultado: **Aprobado**.
