# Aislamiento de empresas

Para impedir que un administrador de una empresa consulte o relacione documentos
de otra, Netward debe ejecutarse como una instancia dedicada por empresa.

## Componentes que no deben compartirse

Cada instancia necesita recursos independientes:

- proceso o servicio web;
- `SECRET_KEY`;
- base de datos indicada por `DATABASE_URL`, `DATABASE_URL_EMPLEADO` y
  `DATABASE_URL_ADMIN`;
- copias de seguridad y registros de aplicación;
- recurso, endpoint y clave de Azure Document Intelligence;
- dominio o subdominio, si la aplicación se publica en Internet.

Los PDF se guardan en `facturas_compra.archivo_pdf`. Por eso, usar bases de datos
separadas también separa el almacenamiento de los documentos y sus análisis.

## Configuración de cada instancia

```dotenv
TENANT_ISOLATION_MODE=true
ISOLATED_TENANT_ID=C001

DATABASE_URL=postgresql+psycopg2://usuario_privado:clave@host/base_empresa
DATABASE_URL_EMPLEADO=postgresql+psycopg2://usuario_privado:clave@host/base_empresa
DATABASE_URL_ADMIN=postgresql+psycopg2://usuario_privado:clave@host/base_empresa

AI_ENABLED=true
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://recurso-exclusivo.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=clave-exclusiva-de-la-instancia
```

`C001` es deliberadamente igual en todas las instalaciones: solo es una clave
técnica local y no identifica a la empresa fuera de su base. El modo dedicado
filtra el inicio de sesión y todas las consultas por ese valor y rechaza sesiones
creadas por otra instancia.

No se deben copiar archivos `.env`, bases, respaldos ni registros entre empresas.
Las claves reales nunca deben guardarse en `.env.example` ni en Git.

## Límite de la protección

Este aislamiento protege frente al administrador general de la aplicación. Un
operador con acceso total al servidor, a las bases o a las suscripciones de Azure
todavía puede acceder a esos recursos. Para impedirlo, cada empresa debe controlar
su propia infraestructura y su propia suscripción o grupo de recursos de Azure.
