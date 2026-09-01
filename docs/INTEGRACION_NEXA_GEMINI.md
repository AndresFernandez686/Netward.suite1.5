# Integracion de Nexa con Google Gemini

## Configuracion activa

Nexa utiliza el adaptador `gemini` sin cambiar las rutas ni la interfaz del
chatbot. La configuracion se mantiene exclusivamente en `.env`:

```dotenv
AI_ENABLED=true
AI_PROVIDER=gemini
AI_MODEL=gemini-3.6-flash
AI_API_KEY=tu-clave-de-Google
AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
AI_TIMEOUT_SECONDS=60
AI_MAX_OUTPUT_TOKENS=2048
AI_TEMPERATURE=0.2
AI_LOCAL_FALLBACK_ENABLED=true
```

La clave se envia en el encabezado `x-goog-api-key`. No se incorpora en la URL,
el HTML, las preguntas, las respuestas ni el historial persistente.

## Comportamiento conservado

- Nexa sigue siendo de solo lectura y no modifica inventario ni auditoria.
- La conversacion activa permanece al cambiar de apartado.
- El administrador puede recuperar sus ultimas tres conversaciones.
- Se envian a Gemini hasta seis intercambios anteriores para mantener contexto.
- Las consultas generales y las consultas de periodos comparten el mismo sistema
  de historial, aislado por empresa y usuario.
- Si Gemini no esta disponible, el respaldo local puede dar una orientacion
  basica sin detener el resto de Netward.

## Cambio futuro de proveedor

El modulo continua admitiendo otros proveedores. Para probar otra IA basta con
cambiar `AI_PROVIDER`, `AI_MODEL`, `AI_API_KEY` y, cuando corresponda,
`AI_BASE_URL`. No hay que volver a implementar el chatbot ni su historial.

Despues de modificar `.env`, es necesario reiniciar Flask o Gunicorn para que el
proceso vuelva a cargar las variables.

## Validacion realizada

El 31 de agosto de 2026 se comprobo lo siguiente:

- la clave pudo consultar el catalogo de Google con respuesta HTTP 200;
- el catalogo confirmo que `gemini-3.6-flash` admite `generateContent`;
- una solicitud sintetica real respondio `GEMINI_OK`;
- la clave viajo en el encabezado y no dentro de la URL ni del contenido;
- las pruebas automatizadas del asistente, navegacion e historial finalizaron
  correctamente.
