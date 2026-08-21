# Persistencia del menú lateral

Fecha: 2026-08-20.

## Caso 1: conservar la posición

- Desplazar el menú lateral hacia una opción inferior.
- Seleccionar la opción y esperar la navegación.
- Resultado esperado: el nuevo contenido se muestra sin reiniciar el menú al inicio.
- Validación automatizada: el sistema guarda y restaura `scrollTop` sobre `.sidebar__nav`, que es el contenedor desplazable real.

## Caso 2: mantener visible la opción activa

- Abrir directamente una sección ubicada en la parte inferior del menú.
- Resultado esperado: la opción activa queda dentro del área visible de la barra lateral.
- Validación automatizada: después de restaurar la posición, el sistema ajusta únicamente el menú cuando `.nav__link.is-active` queda fuera de sus límites visibles.

## Evidencia

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_sidebar_scroll -v
```

Resultado: **2 pruebas correctas**.
