# Asistente explicativo de auditoría

El asistente traduce los resultados ya calculados por Netward a explicaciones claras. Es de solo lectura: no puede modificar inventarios, períodos, resultados, causas, severidades ni justificaciones.

## Ubicación

- **Asistente de auditoría** en la barra superior: resume el período y prioriza revisiones.
- **Explicar con IA** dentro del detalle de cada producto: explica cálculo, evidencia, continuidad y próximos controles.
- Ambas opciones abren un panel lateral y conservan la pantalla de auditoría visible.

## Proveedores

`AI_PROVIDER` admite `openai`, `openai_compatible`, `anthropic`, `gemini`, `ollama` y `custom`. El adaptador `custom` envía un JSON neutral a un webhook propio, por lo que permite integrar APIs con un protocolo diferente sin acoplar la interfaz.

La configuración vive en `.env`; las claves nunca llegan al navegador. Si el proveedor está desactivado, incompleto o no responde, el sistema presenta una explicación local basada en reglas.

## Seguridad y trazabilidad

- Solo el rol `administrador` puede consultar el endpoint.
- El período y el resultado se validan contra el `cliente_id` de la sesión.
- Los textos de productos y evidencias se tratan como datos no confiables.
- La respuesta se muestra con `textContent`, sin ejecutar HTML.
- Cada consulta queda registrada en `asistente_ia_consultas`, sin almacenar la clave de API.
- El contexto se limita al resultado seleccionado o a los 15 hallazgos principales del período.

## Activación mínima

```dotenv
AI_ENABLED=true
AI_PROVIDER=openai
AI_MODEL=<modelo-habilitado-en-tu-cuenta>
AI_API_KEY=<clave-del-proveedor>
AI_BASE_URL=
```

Para PostgreSQL existente, ejecutar `migracion/07_asistente_ia.sql` antes de activar la función.
