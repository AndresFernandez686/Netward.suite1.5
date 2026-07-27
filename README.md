# Netward — Sistema de Gestión de Inventario Multi-Tienda



Aplicación web desarrollada en **Flask + SQLAlchemy + SQLite** para la gestión de inventario,

delivery y análisis de stock en cadenas de heladerías Grido.



> **Versión:** suite 1.3.1 · **Stack:** Python 3.14 · Flask 3.x · SQLite · openpyxl · xlrd



---



## Características principales



### Panel de Empleados

- Carga de inventario por categorías: **Impulsivo**, **Por Kilos**, **Extras**

- Buscador inteligente con filtro por nombre y por inicio de palabra

- Soporte de múltiples UME por producto en el mismo inventario:

  - **Unidad** — cantidad individual

  - **Caja** → convierte automáticamente usando `Unid. x Caja` configurado por el admin

  - **Bulto** → convierte usando `Cajas x Bulto × Unid. x Caja`

- El carrito muestra cada UME como fila separada con subtotal en unidades individuales

- Registro de delivery por tienda



### Panel de Administradores

- Vista consolidada de inventario por tienda y categoría

- Historial de movimientos con exportación a Excel

- Catálogo de delivery con gestión de precios y promociones

- **Configuración de catálogo**: agregar/eliminar productos, asignar precio unitario en Gs.,

  unidades por caja y cajas por bulto

- **Módulo Desc.**: procesamiento quincenal de archivos Excel de inventario

  - Limpieza automática de columnas irrelevantes

  - Filtrado de grupos no relevantes (Canjes, Promociones, etc.)

  - Reemplazo del stock inicial con datos del sistema

  - Regla de continuidad quincenal: SF del período anterior → SI del nuevo

  - Recálculo de venta teórica y diferencia

  - Descarga del resultado como `.xlsx` coloreado

  - Sincronización de nombres de productos entre sistema y Excel



---



## Estructura del proyecto



```

Netward.suite1.3.1/

├── app.py                  # Aplicación principal Flask (rutas, lógica)

├── requirements.txt        # Dependencias Python

├── core/

│   ├── __init__.py

│   ├── models.py           # Modelos SQLAlchemy (10 tablas)

│   ├── seed_data.py        # Datos iniciales y catálogo base

│   └── inventario.py      # Blueprint Desc. (procesamiento Excel quincenal)

├── static/

│   ├── css/styles.css      # Estilos (paleta slate + brand azul)

│   └── js/main.js

├── templates/

│   ├── base.html           # Layout base con sidebar

│   ├── login.html

│   ├── empleado_inventario.html

│   ├── empleado_historial.html

│   ├── empleado_delivery.html

│   ├── admin_inventario.html

│   ├── admin_historial.html

│   ├── admin_delivery.html

│   ├── admin_configuracion.html

│   ├── admin_desc.html

│   └── admin_sincronizar.html

└── instance/

    └── netward_empleado.db  # Base de datos SQLite

```



---



## Instalación y ejecución local



```bash

# 1. Clonar

git clone https://github.com/AndresFernandez686/Netward.suite1.3.1.git

cd Netward.suite1.3.1



# 2. Crear entorno virtual (recomendado: uv)

uv venv

uv pip install -r requirements.txt



# 3. Ejecutar

.venv/Scripts/python app.py       # Windows

# o

.venv/bin/python app.py           # Linux/Mac

```



La app queda disponible en `http://127.0.0.1:5000`



---



## Usuarios por defecto (Modo Beta)



| Usuario    | Rol           | Tienda     |

|------------|---------------|------------|

| `empleado` | Empleado      | Seminario  |

| `empleado1`| Empleado      | Seminario  |

| `empleado2`| Empleado      | Mcal Lopez |

| `admin`    | Administrador | Todas      |

| `admin1`   | Administrador | Todas      |



> En Modo Beta **cualquier contraseña es válida**.



---



## Catálogo de productos



| Categoría   | Productos | UME disponibles          |

|-------------|-----------|--------------------------|

| Impulsivo   | 38        | Unidad · Caja · Bulto    |

| Por Kilos   | 35        | Kilos / Baldes           |

| Extras      | 26        | Unidad · Caja · Tira     |



---



## Módulo Desc. — Inventario quincenal



El módulo procesa archivos `.xls/.xlsx` exportados del sistema POS:



1. El admin sube el archivo y selecciona tienda + rango de fechas

2. El sistema filtra grupos irrelevantes y aplica la regla de continuidad quincenal

3. Reemplaza `stockinicial` con datos del empleado (InventarioItem) y `ventareal` con DeliveryVentas

4. Recalcula: `Venta Teórica = SI + Compras + Otros Ingresos − SF − Otras Salidas`

5. Descarga el resultado como `.xlsx` con colores indicadores

6. Guarda un snapshot del SF para el próximo inventario del mes



---



## Dependencias



```

Flask>=3.0.0

Flask-SQLAlchemy>=3.1.0

SQLAlchemy>=2.0.0

openpyxl>=3.1.0

xlrd>=2.0.1

python-dateutil>=2.8.0

python-dotenv>=1.0.0

Werkzeug>=3.0.0

```



