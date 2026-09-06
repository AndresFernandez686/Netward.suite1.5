# Nexa: analista IA de auditoría

## Objetivo

Nexa es el agente inteligente de Netward. Ayuda al administrador a comprender
diferencias de inventario, resumir hallazgos y decidir qué evidencias revisar
primero.

Nexa es de solo lectura: no cambia cálculos, inventarios, períodos, causas,
severidades, justificaciones ni reportes. El motor de auditoría continúa siendo la
fuente oficial.

## Dónde se utiliza

En Auditoría existen dos accesos:

- **Nexa**, en la barra superior, analiza el período completo.
- **Explicar con IA**, dentro del detalle de un producto, analiza ese resultado.

Ambos abren el panel lateral sin abandonar la auditoría. La consulta puede tener
hasta 1.000 caracteres.

## Funcionamiento actual: bot local temporal

OpenAI está desactivado temporalmente y Nexa responde mediante el motor local de
reglas. Este modo no realiza solicitudes externas. La integración con OpenAI se
conserva lista para volver a habilitarse mediante las variables del entorno.

El endpoint interno de Netward es:

```text
POST /admin/periodos/<periodo_id>/asistente/consultar
```

Ejemplo:

```json
{
  "pregunta": "¿Qué debería verificar primero?",
  "resultado_id": 125
}
```

`resultado_id` puede ser `null` para analizar todo el período.

## Configuración

Configura el servidor en `.env`:

```dotenv
AI_ENABLED=false
AI_PROVIDER=openai
AI_MODEL=gpt-5.4-mini
AI_API_KEY=tu-clave-secreta
AI_BASE_URL=https://api.openai.com/v1
AI_TIMEOUT_SECONDS=30
AI_MAX_OUTPUT_TOKENS=4096
AI_TEMPERATURE=0.2
AI_LOCAL_FALLBACK_ENABLED=true
AI_CUSTOM_HEADERS_JSON={}
```

Después de cambiar `.env`, reinicia Flask. La suscripción de ChatGPT y la cuota de
la API son servicios separados: la clave necesita acceso y cuota disponibles en
la plataforma API.

Nunca copies la clave real a HTML, JavaScript, documentación, capturas o al
repositorio. Si fue expuesta, revócala y crea una nueva antes de asignarle saldo.

### Volver a habilitar OpenAI

Cuando la cuenta tenga cuota disponible, cambia únicamente:

```dotenv
AI_ENABLED=true
AI_LOCAL_FALLBACK_ENABLED=false
```

Al reiniciar Flask, Nexa volverá a consultar `POST /v1/responses`. Si OpenAI falla,
devolverá un mensaje controlado y no activará el bot local de forma automática.

## Datos que recibe Nexa

Para un producto puede recibir:

- período, tienda y producto;
- stock inicial, compras, ingresos, ventas, delivery y salidas;
- mermas, vencimientos, stock final físico y venta teórica;
- diferencia, precio interno, impacto y fuente del precio;
- causa, confianza, severidad, continuidad y diferencia anterior;
- usuario del conteo y justificaciones recientes.

Para el período se envía un resumen y un máximo de 15 resultados principales. No
se envían claves, contraseñas ni acceso directo a la base de datos.

## Reglas de explicación

- Una fila **Sin datos** no se presenta como diferencia real confirmada.
- La diferencia se explica siempre como venta real menos venta teórica, equivalente a stock físico menos stock esperado.
- Una diferencia positiva es sobrante y una negativa es faltante.
- El impacto económico se explica usando exclusivamente el precio interno del
  sistema.
- Un producto **Sin costo** se presenta con impacto no calculable, no como pérdida
  cero confirmada.
- La respuesta es explicativa y nunca sustituye el resultado oficial.

## Seguridad y trazabilidad

- Solo un administrador autenticado puede consultar el endpoint.
- Período y resultado se validan contra la empresa de la sesión.
- La IA no ejecuta SQL, herramientas ni acciones sugeridas en los datos.
- La interfaz muestra texto, no interpreta HTML generado.
- La respuesta externa se limita a 2 MB y el texto registrado a 20.000 caracteres.
- Cada consulta se registra en `asistente_ia_consultas` con usuario, período,
  proveedor, modelo, estado y error, sin guardar la clave.

Para PostgreSQL existente:

```powershell
psql -U usuario -d netward -f migracion/07_asistente_ia.sql
```

## Diagnóstico

### HTTP 401

La clave es inválida, fue revocada o no pertenece al proyecto esperado.

### HTTP 429 `insufficient_quota`

La conexión con OpenAI funciona, pero el proyecto no tiene cuota disponible.
Habilita facturación o créditos de API, comprueba los límites del proyecto y vuelve
a intentar.

### Timeout o proveedor inaccesible

Revisa red, proxy, firewall y DNS. `AI_TIMEOUT_SECONDS` admite hasta 120 segundos.

### La explicación no coincide con el cálculo

Revisa el detalle de Auditoría y vuelve a ejecutar el motor si cambiaron los datos.
Nexa interpreta la información disponible; no recalcula ni modifica el resultado.

## Archivos relacionados

- Lógica y conexión: `core/ai_assistant.py`.
- Endpoint: `app.py` (`admin_asistente_consultar`).
- Interfaz: `templates/admin_auditoria.html`.
- Modelo: `core/models.py` (`AsistenteIAConsulta`).
- Migración: `migracion/07_asistente_ia.sql`.
- Variables de ejemplo: `.env.example`.
- Pruebas: `tests/test_asistente_ia.py`.

## Verificación

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_asistente_ia -v
```

Las pruebas cubren configuración, aislamiento, contrato de Responses API, errores
del proveedor, trazabilidad y activación explícita del bot local.
