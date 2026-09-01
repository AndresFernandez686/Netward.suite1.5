# Integración de Nexa con NVIDIA Kimi K3

Fecha de validación: 31 de agosto de 2026.

## Objetivo

Conectar el chatbot administrativo Nexa con el modelo `moonshotai/kimi-k3` mediante
NVIDIA API Catalog, manteniendo las reglas de negocio y los cálculos oficiales dentro
de Netward.

Nexa continúa siendo de solo lectura: el modelo recibe una pregunta y un contexto JSON
preparado por Netward, pero no ejecuta SQL ni modifica inventarios, auditorías, períodos
o configuraciones.

## Implementación

Se agregó el proveedor explícito `nvidia` al adaptador de IA de Netward. La solicitud usa:

- Endpoint: `POST https://integrate.api.nvidia.com/v1/chat/completions`
- Modelo: `moonshotai/kimi-k3`
- Respuesta JSON sin streaming, adecuada para la ruta Flask actual.
- Instrucciones de sistema propias de Nexa.
- `reasoning_effort`, `seed`, temperatura y límite de salida configurables.
- Autenticación exclusivamente desde `.env`; la clave no se envía al navegador ni se
  guarda en la trazabilidad de consultas.

La configuración de referencia es:

```dotenv
AI_ENABLED=true
AI_PROVIDER=nvidia
AI_MODEL=moonshotai/kimi-k3
AI_API_KEY=REEMPLAZAR_CON_UNA_CLAVE_NUEVA
AI_BASE_URL=https://integrate.api.nvidia.com/v1
AI_TIMEOUT_SECONDS=120
AI_MAX_OUTPUT_TOKENS=16384
AI_TEMPERATURE=1
AI_REASONING_EFFORT=max
AI_SEED=0
AI_LOCAL_FALLBACK_ENABLED=false
```

## Pruebas realizadas

### Pruebas automatizadas

Comando:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_asistente_ia
```

Resultado:

- 14 pruebas ejecutadas.
- 14 pruebas aprobadas.
- Sin errores ni fallos.
- Se verificó el endpoint exacto de NVIDIA.
- Se verificó `stream=false`.
- Se verificaron modelo, semilla, temperatura y nivel de razonamiento.
- Se verificó la extracción de `choices[0].message.content`.
- Se verificó que la clave no forme parte del cuerpo JSON enviado al modelo.
- Se conservaron las pruebas de fórmulas, trazabilidad, aislamiento y modo local.

### Prueba real de conectividad

Se realizó una llamada real con contenido sintético, sin información de tiendas,
usuarios, productos ni auditorías.

Resultado observado:

```text
configured: true
provider: nvidia
model: moonshotai/kimi-k3
ok: true
fallback: false
respuesta: CONEXION_NVIDIA_OK
```

La llamada tardó aproximadamente 17 segundos usando `reasoning_effort=max`.

No se enviaron datos reales de Netward durante esta validación externa. La explicación
de inventario se comprobó localmente mediante pruebas automatizadas y datos sintéticos.

## Consideraciones para producción

1. Revocar la clave utilizada durante la integración, porque fue compartida en una
   conversación, y generar una nueva antes de publicar el sistema.
2. Mantener `.env` fuera de Git y restringir su lectura en Ubuntu.
3. Probar `AI_REASONING_EFFORT=high` o `low` si 17 segundos resulta lento. `max` ofrece
   más razonamiento, pero aumenta latencia y consumo.
4. Reducir `AI_MAX_OUTPUT_TOKENS` después de medir respuestas reales; 16.384 conserva
   el valor del ejemplo de NVIDIA, aunque Nexa normalmente necesita mucho menos.
5. Informar a los clientes que el texto estructurado usado por Nexa se procesa en un
   proveedor externo. Evitar enviar datos personales o secretos innecesarios.
6. Mantener el motor de auditoría como única fuente de cálculos. La IA debe explicar
   resultados, nunca decidir ni sobrescribir diferencias.
7. Registrar métricas de latencia, errores HTTP y consumo sin almacenar claves ni
   razonamiento interno del modelo.

## Continuidad e historial de conversaciones

Nexa conserva conversaciones por empresa y administrador. El hilo activo permanece al
cambiar de apartado y el panel permite recuperar las tres conversaciones actualizadas
más recientemente o iniciar una nueva.

- La interfaz recupera hasta 20 intercambios del hilo seleccionado.
- El modelo recibe como continuidad únicamente los seis intercambios exitosos más
  recientes, evitando un crecimiento ilimitado del prompt.
- Las consultas generales también se guardan aunque no estén asociadas a un período.
- Errores y respuestas de respaldo permanecen trazables.
- Una conversación de otra empresa o de otro administrador nunca se puede seleccionar.

La revisión Alembic `20260831_05` crea la tabla de conversaciones, vincula las consultas
existentes y permite que una consulta general tenga `periodo_id` nulo.

## Fuentes técnicas

- NVIDIA Kimi K3 API: https://docs.api.nvidia.com/nim/reference/moonshotai-kimi-k3-infer
- Ficha oficial de Kimi K3: https://docs.api.nvidia.com/nim/re/reference/moonshotai-kimi-k3
- Catálogo de APIs LLM de NVIDIA: https://docs.api.nvidia.com/nim/reference/llm-apis
