"""
Datos iniciales del sistema Netward.
Catalogo de productos, usuarios, tiendas y umbrales de stock.
"""

CLIENTES_DEFAULT = [
    {"id": "C001", "nombre": "Cliente Demo", "plan": "pro", "estado": "activo"},
]

# Estructura completa de productos por categoria (migrada de ui_empleado.py)
PRODUCTOS_BASE = {
    "Impulsivo": [
        "Alfajor Almendrado", "Alfajor Bombon Crocante", "Alfajor Bombon Escoces",
        "Alfajor Bombon Suizo", "Alfajor Bombon Cookies and Crema", "Alfajor Bombon Vainilla",
        "Alfajor Casatta", "Crocantino", "Delicia", "Pizza", "Familiar 1", "Familiar 2",
        "Familiar 3", "Familiar 4", "Palito Bombon", "Palito Crema Americana",
        "Palito Crema Frutilla", "Palito Frutal Frutilla", "Palito Frutal Limon",
        "Palito Frutal Naranja", "Tentacion Chocolate", "Tentacion Chocolate con Almendra",
        "Tentacion Cookies", "Tentacion Crema Americana", "Tentacion Dulce de Leche Granizado",
        "Tentacion Dulce de Leche", "Tentacion Frutilla", "Tentacion Granizado",
        "Tentacion Menta Granizada", "Tentacion Mascarpone", "Tentacion Vainilla",
        "Tentacion Limon", "Tentacion Toddy", "Yogurt Helado Frutilla sin Tacc",
        "Yogurt Helado Mango Maracuya", "Yogurt Helado Frutos del Bosque sin Tacc",
        "Helado sin Azucar Frutilla a la Crema", "Helado sin Azucar Durazno a la Crema",
        "Helado sin Azucar chocolate sin Tacc", "Torta Grido Rellena", "Torta Milka",
        "Torta Helada Cookies Mousse",
    ],
    "Por Kilos": [
        "Vainilla", "Chocolate", "Fresa", "Anana a la crema", "Banana con Dulce de leche",
        "Capuccino Granizado", "Cereza", "Chocolate Blanco", "Chocolate con Almendra",
        "Chocolate Mani Crunch", "Chocolate Suizo", "Crema Americana", "Crema Cookie",
        "Crema Rusa", "Dulce de Leche", "Dulce de Leche con Brownie", "Dulce de Leche con Nuez",
        "Dulce de Leche Especial", "Dulce de Leche Granizado", "Durazno a la Crema", "Flan",
        "Frutos Rojos al Agua", "Granizado", "Kinotos al Whisky", "Limon al Agua", "Maracuya",
        "Marroc Grido", "Mascarpone con Frutos del Bosque", "Menta Granizada",
        "Naranja Helado al Agua", "Pistacho", "Super Gridito", "Tiramisu", "Tramontana", "Candy",
    ],
    "Fanee": [
        "Cinta Grido", "Cobertura Chocolate", "Bolsa 40x50", "Cobertura Frutilla",
        "Cobertura Dulce de Leche", "Leche", "Cuchara Sunday", "Cucharita Grido",
        "Cucurucho Biscoito Dulce x300", "Cucurucho Cascao x120", "Cucurucho Nacional x54",
        "Garrafita de Gas", "Isopor 1 kilo", "Isopor 1/2 kilo", "Isopor 1/4", "Mani tostado",
        "Pajita con Funda", "Servilleta Grido", "Tapa Burbuja Capuccino", "Tapa Burbuja Batido",
        "Vaso capuccino", "Vaso Batido", "Vasito de una Bocha", "Vaso Termico 240gr",
        "Vaso Sundae", "Rollo Termico",
    ],
}

CATEGORIA_FANEE = "Fanee"
CATEGORIAS_FANEE_COMPATIBLES = {CATEGORIA_FANEE, "Extras"}
CATEGORIAS = ["Impulsivo", "Por Kilos", CATEGORIA_FANEE]
TIPOS_INVENTARIO = ["Diario", "Semanal"]
OPCIONES_UME = ["Unidad", "Caja", "Tira"]
# El kilogramo es la unidad base de la categoría "Por Kilos". Un balde
# completo no requiere pesaje; los baldes parciales sí se cargan por su peso
# real. Se conserva la constante en un único lugar para que interfaz, reglas y
# pruebas utilicen exactamente la misma conversión.
PESO_BALDE_LLENO_KG = 7.8
ESTADOS_BALDE = ["Lleno", "Medio lleno"]

# Tiendas iniciales
TIENDAS_DEFAULT = [
    {"id": "T001", "cliente_id": "C001", "nombre": "Seminario", "es_default": True},
    {"id": "T002", "cliente_id": "C001", "nombre": "Mcal Lopez", "es_default": False},
]

# Usuarios con contrasenas (modo beta: contrasenas simples y visibles en pantalla)
USUARIOS_DEFAULT = [
    {"username": "empleado1", "password": "emp123", "cliente_id": "C001", "rol": "empleado", "tienda_id": "T001"},
    {"username": "empleado2", "password": "emp123", "cliente_id": "C001", "rol": "empleado", "tienda_id": "T002"},
    {"username": "empleado3", "password": "emp123", "cliente_id": "C001", "rol": "empleado", "tienda_id": "T001"},
    {"username": "admin1",   "password": "admin123", "cliente_id": "C001", "rol": "administrador", "tienda_id": "ALL"},
    {"username": "admin",    "password": "admin123", "cliente_id": "C001", "rol": "administrador", "tienda_id": "ALL"},
    {"username": "empleado", "password": "emp123", "cliente_id": "C001", "rol": "empleado", "tienda_id": "T001"},
]

# Umbrales del semaforo de stock (migrados de stock_alerts.py)
STOCK_THRESHOLDS_DEFAULT = {
    "Vainilla": {"critico": 5.0, "medio": 15.0},
    "Chocolate": {"critico": 10.0, "medio": 25.0},
    "Fresa": {"critico": 8.0, "medio": 20.0},
    "Dulce de Leche": {"critico": 12.0, "medio": 30.0},
    "Crema Americana": {"critico": 10.0, "medio": 25.0},
    "Granizado": {"critico": 8.0, "medio": 20.0},
    "Tentacion Chocolate": {"critico": 15, "medio": 40},
    "Tentacion Dulce de Leche": {"critico": 20, "medio": 50},
    "Crocantino": {"critico": 25, "medio": 60},
    "Delicia": {"critico": 20, "medio": 50},
    "Pizza": {"critico": 10, "medio": 30},
    "Cucurucho Nacional x54": {"critico": 50, "medio": 200},
    "Cucurucho Biscoito Dulce x300": {"critico": 300, "medio": 800},
    "Vaso capuccino": {"critico": 100, "medio": 500},
    "Cucharita Grido": {"critico": 200, "medio": 800},
    "Servilleta Grido": {"critico": 500, "medio": 2000},
    "Cobertura Chocolate": {"critico": 2, "medio": 8},
    "Cobertura Frutilla": {"critico": 2, "medio": 8},
    "Cobertura Dulce de Leche": {"critico": 3, "medio": 10},
}

# Catalogo de delivery de ejemplo
DELIVERY_DEFAULT = [
    {"nombre": "Promo 2x1 Chocolate", "precio": 12000, "es_promocion": True, "activo": True},
    {"nombre": "Cuarto Kilo Surtido", "precio": 9000, "es_promocion": False, "activo": True},
    {"nombre": "Medio Kilo Surtido", "precio": 16000, "es_promocion": False, "activo": True},
    {"nombre": "Kilo Familiar", "precio": 28000, "es_promocion": False, "activo": True},
]


def stock_status(producto, cantidad, thresholds):
    """
    Devuelve (nivel, etiqueta) del semaforo de stock.
    nivel: critical | warning | success
    """
    try:
        cantidad = float(cantidad)
    except (TypeError, ValueError):
        cantidad = 0

    th = thresholds.get(producto)
    if not th:
        if cantidad <= 0:
            return "critical", "Sin stock"
        elif cantidad <= 5:
            return "warning", "Stock bajo"
        return "success", "Stock OK"

    critico = th.get("critico", 0)
    medio = th.get("medio", critico * 2)
    if cantidad <= critico:
        return "critical", "Critico"
    elif cantidad <= medio:
        return "warning", "Medio"
    return "success", "Suficiente"
