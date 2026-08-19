# Datos maliciosos y caracteres especiales

## Escenario

Se usaron nombres y observaciones con comillas, apóstrofes, punto y coma, Unicode, fragmentos SQL, etiquetas `<script>` y prefijos interpretables como fórmulas de Excel.

## Validaciones

- SQLAlchemy trata el nombre como dato y no ejecuta el fragmento SQL.
- La tabla de productos permanece disponible.
- El reporte gerencial conserva el producto y no se rompe.
- Jinja escapa las etiquetas HTML potencialmente peligrosas.
- La exportación convierte prefijos `=`, `+`, `-` y `@` en texto, evitando fórmulas inyectadas.

## Resultado

**APROBADO**: sin inyección SQL, XSS renderizado, fórmula activa ni ruptura del reporte.

Prueba: `test_datos_maliciosos_no_inyectan_sql_html_ni_formulas_excel`.
