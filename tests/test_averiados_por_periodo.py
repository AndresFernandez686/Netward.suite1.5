import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PruebasInterfazAveriadosPorPeriodo(unittest.TestCase):
    def test_empleado_exige_y_conserva_periodo(self):
        plantilla = (ROOT / "templates" / "empleado_averiado.html").read_text(encoding="utf-8")
        self.assertIn("Período contable del averiado", plantilla)
        self.assertIn('name="periodo_id" value="{{ periodo_activo.id }}"', plantilla)
        self.assertIn('min="{{ periodo_activo.fecha_desde }}"', plantilla)
        self.assertIn('max="{{ periodo_activo.fecha_hasta }}"', plantilla)

    def test_admin_filtra_por_periodo_y_no_por_fechas_sueltas(self):
        plantilla = (ROOT / "templates" / "admin_averiados.html").read_text(encoding="utf-8")
        self.assertIn('name="periodo_id"', plantilla)
        self.assertNotIn('name="desde"', plantilla)
        self.assertNotIn('name="hasta"', plantilla)

    def test_motor_usa_clave_de_periodo(self):
        auditoria = (ROOT / "core" / "auditoria.py").read_text(encoding="utf-8")
        inicio = auditoria.index("def _mermas_vencidos")
        fin = auditoria.index("def _compensacion_conteo", inicio)
        funcion = auditoria[inicio:fin]
        self.assertIn("periodo_id=periodo.id", funcion)
        self.assertNotIn("RegistroAveriado.fecha >=", funcion)

    def test_post_no_puede_caer_silenciosamente_en_otro_periodo(self):
        codigo = (ROOT / "app.py").read_text(encoding="utf-8")
        inicio = codigo.index("def empleado_averiado():")
        fin = codigo.index("def averiado_eliminar", inicio)
        ruta = codigo[inicio:fin]
        self.assertIn('periodo_post_id = request.form.get("periodo_id", type=int)', ruta)
        self.assertIn("periodo_activo.id != periodo_post_id", ruta)
        self.assertIn("periodo_id=periodo_post_id", ruta)


if __name__ == "__main__":
    unittest.main()
