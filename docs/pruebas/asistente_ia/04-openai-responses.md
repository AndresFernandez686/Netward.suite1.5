# Contrato OpenAI Responses

**Prueba:** simular una respuesta de `POST /responses`.

**Esperado:** se envían `model`, `instructions`, `input`, límite de salida y `store=false`; la clave viaja solo en la cabecera y nunca en el contexto.
