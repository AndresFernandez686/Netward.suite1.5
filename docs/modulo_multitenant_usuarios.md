# Módulo: Multi-tenant y Usuarios

## Tablas involucradas
| Tabla | Descripción |
|---|---|
| `clientes` | Empresa/tenant raíz: `id` (C001), `nombre`, `plan`, `estado` |
| `tiendas` | Sucursal: `id` (T001), `cliente_id`, `nombre`, `activa`, `es_default` |
| `usuarios` | Login: `username`, `password_hash` (bcrypt), `rol`, `tienda_id` |

## Jerarquía
```
Cliente (C001)
  ├─ Tienda T001
  ├─ Tienda T002
  └─ Usuario admin (tienda_id = 'ALL')
       Usuario empleado (tienda_id = 'T001')
```

## Roles
| Rol | Acceso | tienda_id |
|---|---|---|
| `administrador` | Todas las rutas `/admin/*` | `ALL` |
| `empleado` | Solo rutas `/empleado/*` | ID de tienda específica |

## Seguridad
- Contraseñas hasheadas con Werkzeug (`generate_password_hash` / `check_password_hash`)
- Sesión con duración de 8 horas (`PERMANENT_SESSION_LIFETIME`)
- `SESSION_COOKIE_HTTPONLY = True`, `SESSION_COOKIE_SAMESITE = 'Lax'`
- `@login_required(rol=...)` en todas las rutas protegidas

## Filtro global de tienda (admin)
El admin selecciona tienda en el topbar. Persiste en `session['admin_tienda_id']`.  
Valor `'ALL'` = ver todas las tiendas consolidadas.

## Rutas principales
| Método | Ruta | Acción |
|---|---|---|
| GET/POST | `/login` | Autenticación |
| GET | `/logout` | Limpia sesión |
| GET/POST | `/admin/usuarios` | CRUD usuarios |
| GET/POST | `/admin/configuracion` | CRUD tiendas |

## `cliente_id` en tablas operativas
Todas las tablas operativas tienen `cliente_id` para aislar datos por tenant.  
El helper `get_cliente_filtro()` en `app.py` devuelve el `cliente_id` de la sesión activa (default `'C001'`).

## Módulo backend
- `app.py` — `login_required()`, `get_cliente_filtro()`, `get_tienda_filtro()`
- `core/seed_data.py` — datos iniciales de clientes, tiendas, usuarios
