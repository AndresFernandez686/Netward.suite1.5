# Notificación del inventario

## Objetivo

Mostrar el resultado de agregar, eliminar o modificar un producto inmediatamente
encima de la sección `Productos cargados`.

## Resultado

**APROBADO.** El bloque de mensajes se renderiza después de los formularios de
categorías y antes de `#sec-carrito`. Solo existe un consumidor de mensajes flash
en la página, por lo que no se pierden ni se duplican notificaciones.

Prueba: `test_notificacion_aparece_inmediatamente_antes_de_productos_cargados`.

La pantalla no muestra una tarjeta separada de `Carga compartida del período`.
Las cargas de otros empleados de la misma tienda aparecen dentro de la tabla
normal `Productos cargados`, identificadas por usuario y sin botón de eliminar.
Las comprobaciones de conflicto y sobreescritura permanecen activas en el
servidor. Pruebas: `test_empleado_no_ve_panel_de_cargas_compartidas` y
`test_11_otro_empleado_ve_cargas_en_la_misma_tabla_sin_poder_eliminarlas`.
