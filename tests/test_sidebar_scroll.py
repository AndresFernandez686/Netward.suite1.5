import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PruebasScrollMenuLateral(unittest.TestCase):
    def test_scroll_se_guarda_sobre_nav_y_no_sobre_aside(self):
        codigo = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
        self.assertIn("sidebar.querySelector('.sidebar__nav')", codigo)
        self.assertIn("saveSidebarScroll(sidebarScroll)", codigo)
        self.assertIn("restoreSidebarScroll(sidebarScroll)", codigo)
        self.assertIn("sidebarScroll.scrollTop", codigo)

    def test_opcion_activa_se_mantiene_visible_y_cache_se_actualiza(self):
        codigo = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
        self.assertIn(".nav__link.is-active", codigo)
        self.assertIn("ensureActiveVisible", codigo)
        for template in ("admin_base.html", "base.html"):
            contenido = (ROOT / "templates" / template).read_text(encoding="utf-8")
            self.assertIn("sidebar-scroll-fix-1", contenido)


if __name__ == "__main__":
    unittest.main()
