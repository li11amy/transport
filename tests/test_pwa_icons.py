"""PWA WebAPK asset regressions: RGB PNGs and a distinct maskable icon."""
import json
import unittest
from pathlib import Path
from build_horarios import HTML

ROOT=Path(__file__).parent.parent

class PWAIconTests(unittest.TestCase):
    def test_manifest_and_html_use_truecolor_icons(self):
        manifest=json.loads((ROOT/"manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["start_url"],"/transport/")
        self.assertEqual(manifest["scope"],"/transport/")
        self.assertEqual(manifest["display"],"standalone")
        self.assertEqual([x["src"] for x in manifest["icons"]],[
            "/transport/icon-192-rgb.png",
            "/transport/icon-512-rgb.png",
            "/transport/icon-512-maskable.png"
        ])
        self.assertIn('rel="manifest" href="/transport/manifest.json?v=2"',HTML)
        self.assertIn('rel="icon" href="/transport/icon-192-rgb.png"',HTML)

    def test_png_assets_are_truecolor_with_expected_dimensions(self):
        specs={"icon-192-rgb.png":192,
               "icon-512-rgb.png":512,
               "icon-512-maskable.png":512}
        for filename,size in specs.items():
            with self.subTest(filename=filename):
                value=(ROOT/filename).read_bytes()
                self.assertEqual(value[:8],b"\x89PNG\r\n\x1a\n")
                self.assertEqual(int.from_bytes(value[16:20],"big"),size)
                self.assertEqual(int.from_bytes(value[20:24],"big"),size)
                self.assertEqual(value[25],2,"Expected PNG truecolor RGB, not indexed palette")
        self.assertNotEqual(
            (ROOT/"icon-512-rgb.png").read_bytes(),
            (ROOT/"icon-512-maskable.png").read_bytes())

    def test_service_worker_precaches_new_icons(self):
        worker=(ROOT/"sw.js").read_text(encoding="utf-8")
        self.assertIn('transport-bahia-v4',worker)
        for file in ("icon-192-rgb.png","icon-512-rgb.png","icon-512-maskable.png"):
            self.assertIn(file,worker)

if __name__=="__main__":
    unittest.main()
