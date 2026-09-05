# Integración local de Nexa con Ollama (pospuesta)

## Estado

La integración con Ollama fue retirada del código activo de Netward. Este documento
conserva el diseño evaluado para una posible implementación futura, pero no describe
una funcionalidad disponible ni variables de entorno aceptadas actualmente.

La decisión permite desplegar Netward en un VPS pequeño sin reservar memoria y CPU
para un modelo de lenguaje local. Nexa continúa utilizando los proveedores remotos
habilitados y, cuando se configura expresamente, el respaldo determinista basado en
reglas de Netward. Ese respaldo local no usa Ollama ni otro modelo de lenguaje.

## Diseño que se había previsto

La propuesta consistía en incorporar Ollama como un proveedor adicional del adaptador
de `core/ai_assistant.py`:

- conexión exclusiva desde el servidor a `POST /api/chat`;
- URL local predeterminada `http://127.0.0.1:11434`;
- modelo, URL, timeout, temperatura y límite de salida configurables;
- solicitudes sin streaming para conservar el contrato actual de la ruta Flask;
- envío de las mismas instrucciones de sistema, contexto estructurado e historial que
  reciben los demás proveedores;
- contexto del modelo (`num_ctx`) y permanencia en memoria (`keep_alive`) configurables;
- sin exponer el servicio de Ollama directamente a Internet ni al navegador;
- mantenimiento de Nexa como herramienta de solo lectura, sin SQL generado ni acciones
  capaces de modificar inventario, auditoría o configuración.

El prototipo contemplaba valores iniciales de 8.192 tokens de contexto y 10 minutos de
permanencia del modelo en memoria. Esos valores deberían volver a medirse con el modelo
y el hardware finalmente seleccionados.

## Condiciones antes de retomarlo

Antes de reintroducir esta integración se debería:

1. Elegir y evaluar un modelo en español con datos sintéticos de auditoría.
2. Dimensionar RAM, CPU y disco a partir del tamaño real del modelo; el VPS básico de
   2 GB considerado para la aplicación web no debe alojar también el modelo.
3. Ejecutar Ollama en un servidor separado o ampliar claramente la infraestructura.
4. Proteger el puerto de Ollama para que solo Netward pueda alcanzarlo.
5. Definir límites de concurrencia, timeout y tamaño de contexto.
6. Agregar pruebas del adaptador, errores, timeouts y respuestas vacías.
7. Medir latencia, memoria máxima y comportamiento simultáneo con Excel y OCR.
8. Documentar instalación, actualizaciones del modelo, monitoreo y procedimiento de
   desactivación antes de habilitarlo en producción.

## Alcance de una implementación futura

Si se retoma, debe desarrollarse como una integración nueva y revisada. No se deben
suponer vigentes nombres de variables, valores del prototipo ni compatibilidad con el
código actual basándose solamente en este documento.
