# Asistente explicativo de auditoría

## Objetivo

El asistente ayuda al administrador a entender diferencias de inventario sin tener
que reconstruir manualmente todos los movimientos. Convierte los resultados ya
calculados por Netward en una explicación clara, señala la evidencia disponible y
sugiere qué verificar primero.

El asistente es de **solo lectura**. La IA no calcula ni modifica el resultado
oficial, el inventario, el período, la severidad, la causa sugerida, la
justificación ni el reporte gerencial. El motor de auditoría sigue siendo la fuente
oficial.

## Dónde se utiliza

En la pantalla de Auditoría existen dos accesos:

- **Asistente de auditoría**, en la barra superior: analiza el período completo y
  resume faltantes, sobrantes, compensaciones, críticos e impacto económico.
- **Explicar con IA**, dentro del detalle de un producto: analiza el cálculo, la
  evidencia, la continuidad, la diferencia anterior y las justificaciones de ese
  producto.

Ambos abren un panel lateral sin abandonar la auditoría. El administrador puede
usar preguntas sugeridas o escribir una consulta de hasta 1.000 caracteres.

## Flujo técnico

1. El navegador envía la pregunta y, opcionalmente, el identificador del resultado.
2. El backend valida el rol, la empresa, la tienda, el período y el resultado.
3. Netward construye un contexto JSON únicamente con datos oficiales permitidos.
4. Si hay una API configurada, el adaptador consulta al proveedor seleccionado.
5. Si la API está desactivada, mal configurada, fuera de servicio o excede el
   tiempo de espera, se genera automáticamente una explicación local basada en
   reglas.
6. La respuesta se presenta como texto y la consulta queda registrada para
   trazabilidad.

El endpoint utilizado es:

```text
POST /admin/periodos/<periodo_id>/asistente/consultar
```

Ejemplo del cuerpo interno:

```json
{
  "pregunta": "¿Qué debería verificar primero?",
  "resultado_id": 125
}
```

`resultado_id` puede ser `null` para consultar el resumen completo del período.

## Datos que puede recibir la IA

Para un producto se incluye, cuando existe:

- período y producto;
- stock inicial anterior y stock inicial del Excel;
- compras, otros ingresos, ventas, delivery y otras salidas;
- mermas y vencimientos;
- stock esperado, conteo del empleado, ajuste y conteo final;
- diferencia, costo, impacto y fuente del costo;
- tipo, causa, confianza, severidad, estado y alerta de continuidad;
- diferencia del período anterior;
- usuario del conteo y últimas justificaciones.

Para un período se envía un resumen y como máximo los 15 resultados principales
ordenados por impacto. No se envían claves de API ni acceso directo a la base de
datos.

## Configuración en `.env`

Configuración común:

```dotenv
AI_ENABLED=true
AI_PROVIDER=openai
AI_MODEL=modelo-habilitado-en-tu-cuenta
AI_API_KEY=tu-clave-secreta
AI_BASE_URL=
AI_TIMEOUT_SECONDS=30
AI_MAX_OUTPUT_TOKENS=1200
AI_TEMPERATURE=0.2
AI_CUSTOM_HEADERS_JSON={}
```

Después de modificar `.env`, reinicia Flask. Nunca escribas la clave en archivos
HTML, JavaScript, documentación, capturas ni repositorios.

### OpenAI

```dotenv
AI_ENABLED=true
AI_PROVIDER=openai
AI_MODEL=modelo-habilitado-en-tu-cuenta
AI_API_KEY=tu-clave-de-api
AI_BASE_URL=https://api.openai.com/v1
```

`AI_BASE_URL` también puede quedar vacío; Netward utilizará
`https://api.openai.com/v1`. La URL de ChatGPT y la página donde se crean las claves
no son endpoints de API.

### API compatible con OpenAI

```dotenv
AI_PROVIDER=openai_compatible
AI_MODEL=nombre-del-modelo
AI_API_KEY=clave-del-proveedor
AI_BASE_URL=https://servidor.example/v1
```

El proveedor debe aceptar `POST <AI_BASE_URL>/chat/completions`.

### Anthropic

```dotenv
AI_PROVIDER=anthropic
AI_MODEL=nombre-del-modelo
AI_API_KEY=clave-del-proveedor
AI_BASE_URL=
```

Vacío utiliza `https://api.anthropic.com/v1`.

### Gemini

```dotenv
AI_PROVIDER=gemini
AI_MODEL=nombre-del-modelo
AI_API_KEY=clave-del-proveedor
AI_BASE_URL=
```

Vacío utiliza `https://generativelanguage.googleapis.com/v1beta`.

### Ollama local

```dotenv
AI_PROVIDER=ollama
AI_MODEL=nombre-del-modelo-local
AI_API_KEY=
AI_BASE_URL=http://localhost:11434
```

### Webhook personalizado

```dotenv
AI_PROVIDER=custom
AI_MODEL=nombre-interno
AI_API_KEY=clave-opcional
AI_BASE_URL=https://servidor.example/asistente
AI_CUSTOM_HEADERS_JSON={"X-API-Key":"clave-opcional"}
```

El webhook recibe un JSON neutral con `model`, `system`, `question`, `context`,
`max_output_tokens` y `temperature`. Debe responder con texto en una de estas
propiedades: `answer`, `output_text` o `text`.

## Significado de las variables

| Variable | Función |
|---|---|
| `AI_ENABLED` | Activa o desactiva la consulta externa. |
| `AI_PROVIDER` | Selecciona `openai`, `openai_compatible`, `anthropic`, `gemini`, `ollama` o `custom`. |
| `AI_MODEL` | Nombre exacto del modelo habilitado por el proveedor. |
| `AI_API_KEY` | Credencial secreta; permanece en el servidor. |
| `AI_BASE_URL` | URL base del proveedor o URL completa del webhook personalizado. |
| `AI_TIMEOUT_SECONDS` | Espera máxima; se limita internamente entre 1 y 120 segundos. |
| `AI_MAX_OUTPUT_TOKENS` | Tamaño máximo solicitado; se limita entre 100 y 4.000. |
| `AI_TEMPERATURE` | Variación de la respuesta; se limita entre 0 y 2. |
| `AI_CUSTOM_HEADERS_JSON` | Encabezados adicionales usados únicamente por `custom`. |

## Modos visibles

- **IA conectada**: configuración completa y proveedor externo disponible.
- **Explicación local**: IA desactivada o configuración incompleta.
- **Modo local después de error**: hubo timeout, error HTTP, respuesta inválida o
  respuesta vacía; el administrador igualmente recibe una explicación básica.

El modo local no es un chatbot generativo. Resume los cálculos oficiales mediante
reglas deterministas.

## Seguridad y aislamiento

- Solo el rol `administrador` puede utilizar el endpoint.
- Cada período y resultado se valida contra el `cliente_id` de la sesión.
- No se ejecutan instrucciones, SQL, herramientas ni acciones sugeridas por la IA.
- Los nombres, observaciones y evidencias se consideran contenido no confiable para
  reducir ataques de inyección de instrucciones.
- La interfaz muestra la respuesta mediante `textContent`; no interpreta HTML.
- La respuesta externa está limitada a 2 MB y el texto almacenado a 20.000
  caracteres.
- La clave de API nunca se incorpora al contexto ni a la tabla de trazabilidad.

Si una clave real fue mostrada en una captura, consola, chat o archivo compartido,
debe revocarse y reemplazarse inmediatamente.

## Trazabilidad y PostgreSQL

Cada consulta se registra en `asistente_ia_consultas` con empresa, tienda, período,
resultado opcional, administrador, pregunta, respuesta, proveedor, modelo, contexto,
estado, error y fecha.

En una base PostgreSQL existente, ejecuta una vez:

```powershell
psql -U usuario -d netward -f migracion/07_asistente_ia.sql
```

La migración es idempotente y agrega claves foráneas e índices. Las instalaciones
nuevas que crean el esquema desde los modelos ya incluyen la tabla.

## Diagnóstico rápido

### Siempre aparece “Explicación local”

Comprueba `AI_ENABLED=true`, que `AI_MODEL` no esté vacío, que el proveedor tenga la
clave requerida y que `AI_BASE_URL` esté definido para `openai_compatible` o
`custom`. Luego reinicia la aplicación.

### Error HTTP del proveedor

Verifica la clave, el nombre exacto del modelo, permisos de la cuenta, saldo o cuota
y la URL base. Netward no expone el cuerpo remoto para evitar filtrar información
sensible; registra solamente el código HTTP.

### Timeout o proveedor inaccesible

Verifica red, proxy, firewall y DNS. Para Ollama confirma que el servicio local esté
activo. Puedes ajustar `AI_TIMEOUT_SECONDS` hasta un máximo de 120.

### La explicación no coincide con el cálculo

La explicación nunca reemplaza el resultado oficial. Revisa primero el detalle de
Auditoría, vuelve a ejecutar el motor si cambiaron los datos y utiliza el asistente
solo para interpretar la evidencia disponible.

## Archivos relacionados

- Backend y adaptadores: `core/ai_assistant.py`.
- Endpoint y trazabilidad: `app.py` (`admin_asistente_consultar`).
- Interfaz: `templates/admin_auditoria.html`.
- Modelo: `core/models.py` (`AsistenteIAConsulta`).
- Migración PostgreSQL: `migracion/07_asistente_ia.sql`.
- Configuración de ejemplo: `.env.example`.
- Pruebas automatizadas: `tests/test_asistente_ia.py`.
- Casos documentados: `docs/pruebas/asistente_ia/README.md`.

## Pruebas recomendadas

Ejecutar:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_asistente_ia -v
```

Se validan el fallback local, aislamiento entre empresas, resumen del período,
contrato OpenAI Responses, proveedores intercambiables, configuración inválida y
trazabilidad sin secretos.
