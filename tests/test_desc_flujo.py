import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PruebasFlujoDesc(unittest.TestCase):
    def test_procesar_almacena_y_redirige_sin_descarga_automatica(self):
        codigo = (ROOT / "core" / "inventario.py").read_text(encoding="utf-8")
        inicio = codigo.index("def admin_desc():")
        fin = codigo.index("def desc_snapshot_eliminar", inicio)
        ruta = codigo[inicio:fin]
        plantilla = (ROOT / "templates" / "admin_desc.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("send_file(", ruta)
        self.assertNotIn("_generar_xlsx(", ruta)
        self.assertIn("#datos-extraidos-card", ruta)
        self.assertNotIn("data-submit-delay", plantilla)
        self.assertIn("Importar y validar", plantilla)
        self.assertIn("Ver datos extraídos", plantilla)
        self.assertIn("Guardar modificaciones", plantilla)

    def test_auditoria_remite_al_unico_importador_y_datetime_es_compatible(self):
        detalle = (ROOT / "templates" / "admin_periodo_detalle.html").read_text(
            encoding="utf-8"
        )
        app = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertNotIn('name="archivo_excel"', detalle)
        self.assertIn("desc.admin_desc", detalle)
        self.assertIn("datetime.now(timezone.utc)", app)
        self.assertNotIn("datetime.utcnow().strftime", app)


if __name__ == "__main__":
    unittest.main()
