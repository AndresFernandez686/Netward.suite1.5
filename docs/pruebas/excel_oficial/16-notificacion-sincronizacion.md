# Notificación de sincronización pendiente

## Objetivo

Avisar al administrador cuando el catálogo y los datos extraídos del Excel requieren
revisión, sin aplicar cambios automáticamente.

## Casos validados

1. Una importación contiene un producto que no existe: queda `sin_producto`, se
   descarta automáticamente y no genera una alerta falsa.
2. Se crea después un producto coincidente: la fila se muestra como lista para
   vincular y se habilita **Aplicar cambios**.
3. Se modifica el código o la descripción de un producto en **Datos extraídos**: la
   relación anterior se invalida y la alerta se actualiza inmediatamente, sin
   recargar la página.
4. Hay un renombre definido entre el catálogo y el Excel: se contabiliza como cambio
   aplicable.
5. Se aplican todos los cambios: desaparecen la alerta y los contadores.
6. Una fila sigue sin producto coincidente: se informa como descartada y **Aplicar
   cambios** permanece desactivado porque no existe ningún cambio aplicable.
7. Se crean uno o varios productos nuevos: todos aparecen con estado **Nuevo
   producto**, habilitan **Aplicar cambios** y solo entonces quedan publicados para
   los empleados.
8. Después de la publicación, cada empleado recibe **Sincronización pendiente** y no
   ve los productos nuevos todavía. **Solo Enviar** conserva el pendiente; **Enviar y
   Recibir** actualiza su versión personal y recién entonces muestra los productos.
9. Una fila inicialmente excluida por grupo, como `Pizza frizzio mozzarella`, puede
   ser recuperada cuando el administrador crea y publica explícitamente un producto
   coincidente. La sincronización elimina la exclusión y conserva su trazabilidad.

Los cambios numéricos, como compras o stock, no requieren sincronización de catálogo:
se guardan directamente y Auditoría utiliza el valor editado.

Automatización: `tests/test_excel_editor.py`, `tests/test_excel_oficial.py` y
`tests/test_desc_flujo.py`.
