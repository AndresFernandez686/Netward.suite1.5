# Excel oficial 12: flujo único desde Excel oficial

## Función del módulo

El menú antes llamado `Desc.` es ahora `Excel oficial`. Su responsabilidad es:

1. Recibir el archivo `.xls` o `.xlsx` del sistema externo.
2. Validar encabezados y valores.
3. Vincular productos por código, nombre o alias seguro.
4. Registrar `excel_importados` y `excel_detalles` dentro del período elegido.
5. Preparar el snapshot de continuidad.
6. Dejar el período listo para que Auditoría calcule sus resultados.

## Cambio de comportamiento

`Importar y validar` ya no responde con una descarga. Confirma la transacción y
redirige a la misma página con el resumen del procesamiento. Esto permite que la
interfaz quite correctamente el estado de carga.

La pantalla de detalle de Auditoría ya no contiene un segundo selector de
archivo: muestra el archivo asociado y enlaza al importador único para cargarlo o
reemplazarlo.

## Advertencia de fecha

La generación de la versión de recursos usa un `datetime` UTC con zona horaria,
compatible con las versiones nuevas de Python. La recarga del watchdog al detectar
archivos modificados es comportamiento normal del servidor de desarrollo y no es
un bloqueo de procesamiento.
