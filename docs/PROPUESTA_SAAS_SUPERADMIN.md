# Propuesta SaaS y módulo Superadmin para Netward

## 1. Objetivo

Convertir Netward en un servicio por suscripción mensual, capaz de atender a
varias empresas sin mezclar sus inventarios, usuarios, tiendas, documentos ni
auditorías.

La propuesta incorpora un módulo **Superadmin dentro del sistema**, disponible
en una ruta independiente como `/superadmin`. Aunque forme parte de la misma
aplicación, tendrá autenticación, permisos y datos de control separados de los
módulos Administrador y Empleado.

## 2. Respuesta corta

Sí, conviene crear el rol Superadmin, pero no debe confundirse con el dueño de
una empresa cliente.

- El **Superadmin de plataforma** administra Netward como servicio.
- El **Dueño o administrador de empresa** administra únicamente su empresa.
- El **Empleado** trabaja solamente con las tiendas que tenga asignadas.

Crear una tienda no debe crear tablas nuevas. La tienda se registra dentro de
la base de su empresa y los datos se separan mediante `cliente_id`, `tienda_id`
y las relaciones correspondientes.

## 3. Roles propuestos

### Superadmin de plataforma

Es un usuario interno de Netward. Puede:

- crear y activar empresas clientes;
- asignar planes y límites;
- asignar más de una tienda a un mismo usuario;
- consultar el estado de las suscripciones;
- suspender o reactivar una empresa;
- crear al primer usuario dueño de cada empresa;
- revisar uso, errores, respaldos y estado de migraciones;
- ayudar a un cliente mediante acceso de soporte controlado y auditado;
- consultar métricas generales sin entrar automáticamente a sus datos de
  inventario.

No debe poder modificar inventarios silenciosamente ni utilizar una sesión de
Superadmin como si fuera un empleado.

### Dueño de empresa

Es el responsable de una empresa cliente. Puede:

- crear y administrar sus tiendas;
- crear administradores y empleados;
- asignar usuarios a tiendas;
- consultar información consolidada de su empresa;
- administrar la configuración operativa;
- consultar su plan, consumo y facturación;
- solicitar cambio o cancelación del plan.

### Administrador de tienda o empresa

Puede administrar inventario, períodos, documentos y auditorías dentro del
alcance que le otorgue el dueño. No puede cambiar la suscripción ni entrar a
otra empresa.

### Empleado

Puede cargar inventario, averiados, vencimientos y sincronizaciones únicamente
en las tiendas asignadas.

## 4. Arquitectura recomendada

### Base de control de la plataforma

Se propone una base PostgreSQL separada llamada, por ejemplo,
`netward_control`. Guardaría solamente información comercial y operativa de la
plataforma:

- empresas contratantes;
- planes;
- suscripciones;
- límites contratados;
- estado de pago;
- dominios o instancias asignadas;
- usuarios Superadmin;
- eventos de aprovisionamiento;
- auditoría de accesos de soporte;
- estado de respaldos y migraciones.

Esta base no debe almacenar productos, conteos, facturas PDF ni resultados de
auditoría de los clientes.

### Base operativa por empresa

La arquitectura actual de Netward ya está orientada a una base aislada por
empresa. Se recomienda conservar inicialmente este modelo:

```text
netward_control
├── empresa Helacor  → base netward_cliente_0001
├── empresa Cliente B → base netward_cliente_0002
└── empresa Cliente C → base netward_cliente_0003
```

Dentro de la base de cada empresa existirán las mismas tablas que ya utiliza
Netward. Todas las tiendas de esa empresa compartirán esas tablas y se
separarán por `tienda_id`.

Ventajas:

- mayor aislamiento entre clientes;
- respaldo y restauración individual por empresa;
- una falla o consulta incorrecta tiene menor posibilidad de afectar a otros;
- facilita entregar o eliminar los datos de un cliente específico;
- aprovecha el diseño actual y reduce el riesgo de la conversión a SaaS.

Desventajas:

- las migraciones deben ejecutarse en todas las bases;
- se necesita automatizar creación, respaldo y monitoreo;
- muchas empresas implicarán más conexiones y trabajo operativo.

### Alternativa futura: base compartida

Cuando el número de clientes sea muy grande, podría evaluarse una única base
con `tenant_id` en todas las tablas y políticas Row-Level Security de
PostgreSQL. No se recomienda como primer paso porque exige revisar todas las
consultas y claves foráneas para garantizar que ninguna operación pueda cruzar
empresas.

PostgreSQL permite restringir filas con políticas RLS y aplica denegación por
defecto cuando RLS está habilitado sin una política aplicable. Sin embargo, los
superusuarios, los roles con `BYPASSRLS` y normalmente el propietario de la
tabla pueden omitir esas políticas. Por eso una arquitectura compartida debe
usar un rol de aplicación sin esos privilegios y, cuando corresponda,
`FORCE ROW LEVEL SECURITY`.

Referencia: [Row Security Policies de PostgreSQL](https://www.postgresql.org/docs/17/ddl-rowsecurity.html).

## 5. Módulo Superadmin dentro de Netward

El módulo debe utilizar el mismo diseño visual de Netward, pero con navegación
y sesión independientes.

Rutas sugeridas:

```text
/superadmin/login
/superadmin/resumen
/superadmin/empresas
/superadmin/empresas/<id>
/superadmin/planes
/superadmin/suscripciones
/superadmin/aprovisionamiento
/superadmin/respaldos
/superadmin/auditoria-accesos
```

Pantallas principales:

### Resumen de plataforma

- empresas activas, en prueba, atrasadas y suspendidas;
- ingreso mensual recurrente;
- tiendas y usuarios contratados;
- respaldos pendientes o fallidos;
- bases con migraciones pendientes;
- errores recientes del servicio.

### Empresas

- razón social y datos de contacto;
- identificador interno no predecible;
- plan contratado;
- estado comercial y operativo;
- base de datos asignada;
- cantidad de tiendas y usuarios;
- fecha de alta, renovación y cancelación;
- acciones de activar, suspender o iniciar soporte.

### Planes

Ejemplo inicial:

| Característica | Básico | Profesional | Empresa |
| --- | ---: | ---: | ---: |
| Tiendas | 1 | 5 | Personalizado |
| Usuarios | 5 | 25 | Personalizado |
| Facturas PDF por mes | 100 | 1.000 | Personalizado |
| Auditorías | Incluidas | Incluidas | Incluidas |
| Soporte | Normal | Prioritario | Dedicado |

Los límites deben almacenarse como capacidades del plan y no repartirse como
condiciones dispersas dentro del código.

## 6. Flujo de alta de un cliente

1. El Superadmin crea la empresa o recibe una contratación desde la página de
   ventas.
2. El sistema crea un identificador único de empresa.
3. Se registra la suscripción y el plan.
4. Un proceso de aprovisionamiento crea la base PostgreSQL de la empresa.
5. Alembic aplica el esquema vigente.
6. Se crea el usuario dueño de la empresa.
7. El dueño recibe un enlace temporal para definir su contraseña y activar
   autenticación reforzada.
8. El dueño entra y crea sus tiendas y usuarios.
9. Cada acción queda registrada en una bitácora de plataforma.

Si una etapa falla, el aprovisionamiento debe quedar como `fallido` o
`pendiente_reintento`; nunca debe marcarse la empresa como activa a medias.

## 7. Creación de tiendas y usuarios

Cuando el dueño crea una tienda:

- se inserta una fila en `tiendas` dentro de la base de su empresa;
- no se crean tablas nuevas;
- se asigna un `tienda_id` único dentro de la empresa;
- los períodos, conteos, documentos, movimientos y auditorías posteriores se
  vinculan a esa tienda;
- se valida que el plan permita otra tienda antes de guardarla.

Cuando se crea un usuario:

- se vincula al `cliente_id` de la empresa;
- se asigna uno o varios roles permitidos;
- se asignan las tiendas a las que puede acceder;
- se valida el límite de usuarios del plan;
- se registra quién lo creó y cuándo.

Para permitir varias tiendas por usuario conviene incorporar una tabla de
relación como:

```text
usuario_tiendas
├── usuario_id
├── tienda_id
├── rol_en_tienda
├── activo
├── creado_por
└── creado
```

## 8. Suscripciones y pagos mensuales

Estados recomendados:

- `prueba`;
- `activa`;
- `pago_pendiente`;
- `periodo_gracia`;
- `suspendida`;
- `cancelada`.

El pago debe actualizarse mediante eventos del proveedor de cobros. Los
eventos deben validarse, almacenarse con un identificador único y procesarse de
forma idempotente para evitar aplicar dos veces la misma notificación.

Reglas sugeridas:

- un pago atrasado no elimina datos;
- durante el período de gracia se muestran avisos al dueño;
- una suspensión puede dejar la cuenta en modo de solo lectura;
- solo una política de retención explícita permite eliminar datos cancelados;
- antes de eliminar debe generarse un respaldo y registrarse la autorización;
- el estado visible de la suscripción debe provenir del evento confirmado del
  proveedor, no solamente del navegador del cliente.

## 9. Seguridad obligatoria

### Separación de sesiones

La sesión Superadmin debe estar separada de las sesiones de empresa. No se debe
aceptar cambiar de rol modificando una URL, cookie o campo de formulario.

### Privilegio mínimo

Cada rol recibe únicamente los permisos necesarios. Toda ruta debe validar en
el servidor tanto el rol como la empresa y tienda solicitadas. La recomendación
general es denegar por defecto y validar autorización en cada solicitud.

Referencia: [Authorization Cheat Sheet de OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html).

### Protección del Superadmin

- autenticación multifactor obligatoria;
- contraseñas fuertes y recuperación segura;
- límite de intentos y alertas de accesos sospechosos;
- sesiones cortas con renovación explícita;
- registro de IP, dispositivo, fecha y acción;
- prohibición de compartir cuentas;
- permisos separados para soporte, cobros e infraestructura.

### Acceso de soporte

Si un Superadmin necesita entrar al contexto de un cliente:

- debe indicar el motivo;
- debe tener autorización específica;
- la sesión debe mostrar un aviso visible de “modo soporte”;
- debe expirar rápidamente;
- cada lectura y modificación sensible debe quedar auditada;
- el dueño debe poder consultar el historial de accesos de soporte.

## 10. Tablas sugeridas para `netward_control`

```text
platform_users
platform_roles
platform_user_roles
tenants
tenant_databases
plans
plan_features
subscriptions
billing_events
provisioning_jobs
platform_audit_log
support_sessions
backup_status
migration_status
```

Campos importantes de `tenants`:

```text
id
slug
nombre
estado
plan_id
owner_email
database_id
fecha_alta
fecha_suspension
fecha_cancelacion
```

Las credenciales de las bases no deben almacenarse directamente en esa tabla.
Deben guardarse en variables seguras o en un administrador de secretos; la
tabla conserva únicamente una referencia opaca.

## 11. Cambios necesarios en el sistema actual

1. Crear la base de control y sus migraciones Alembic.
2. Incorporar roles `superadmin`, `owner`, `administrador` y `empleado` sin
   reutilizar permisos implícitos.
3. Separar el inicio de sesión de plataforma del inicio de sesión de clientes.
4. Crear el módulo `/superadmin`.
5. Automatizar la creación de bases de clientes y la ejecución de Alembic.
6. Implementar asignación de varios usuarios a varias tiendas.
7. Incorporar planes, límites y capacidades.
8. Integrar el proveedor de cobros mediante eventos verificables.
9. Automatizar respaldos y pruebas de restauración por empresa.
10. Añadir bitácoras inmutables de plataforma, soporte y cambios de permisos.
11. Crear pruebas de aislamiento que intenten cruzar empresas y tiendas.
12. Añadir monitoreo, alertas y política de retención de datos.

## 12. Plan de implementación recomendado

### Fase 1 — Identidad y aislamiento

- base `netward_control`;
- roles nuevos;
- autenticación Superadmin separada;
- empresas y bases registradas;
- pruebas automáticas de aislamiento.

### Fase 2 — Aprovisionamiento

- alta automática de empresa;
- creación de base PostgreSQL;
- aplicación automática de Alembic;
- creación segura del usuario dueño;
- estados y reintentos de aprovisionamiento.

### Fase 3 — Planes y cobros

- catálogo de planes;
- límites por capacidad;
- suscripciones y eventos de pago;
- gracia, suspensión y reactivación;
- historial comercial.

### Fase 4 — Operación SaaS

- respaldos automáticos;
- restauración probada;
- monitoreo de bases;
- actualizaciones masivas de esquema;
- panel de métricas y soporte auditado.

### Fase 5 — Escalabilidad

- colas de trabajos;
- almacenamiento externo de PDF;
- caché y límites de uso;
- evaluación de base compartida con RLS si el volumen lo exige.

## 13. Recomendación final

Para la primera versión comercial se recomienda:

- mantener una base PostgreSQL por empresa;
- mantener todas las tiendas de esa empresa en la misma base;
- crear una base central `netward_control`;
- incorporar el Superadmin dentro de Netward mediante un módulo aislado;
- establecer al dueño de empresa como un rol diferente del Superadmin;
- automatizar altas, migraciones, respaldos y verificaciones antes de aceptar
  clientes reales;
- comenzar con planes y límites simples que puedan ampliarse sin cambiar el
  esquema operativo.

Esta opción aprovecha el aislamiento ya implementado, reduce el riesgo de
mezclar información entre clientes y permite convertir Netward en SaaS de
forma gradual sin rehacer inmediatamente todo el motor de inventario.
