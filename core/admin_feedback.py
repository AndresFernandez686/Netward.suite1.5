"""Utilidades de avisos locales para vistas admin.

Permiten mostrar notificaciones en la misma sección de trabajo
sin depender del flash global del encabezado.
"""


def set_view_notice(sess, key, message, category="info", **extra):
    """Guarda un aviso local en sesión para una vista admin."""
    payload = {
        "message": message,
        "category": category,
    }
    payload.update(extra)
    sess[key] = payload
    sess.modified = True


def pop_view_notice(sess, key):
    """Consume y devuelve un aviso local previamente guardado."""
    return sess.pop(key, None)
