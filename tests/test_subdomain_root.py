"""Root-scoped PWA and independent domain assets do not touch /transport/."""
import json
import tempfile
import unittest
from pathlib import Path
from deploy.subdomain.build_root import prepare, shell
from build_horarios import HTML

class SubdomainTests(unittest.TestCase):
    def test_root_scope_and_offline_install_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"live.json"
            output=Path(tmp)/"app"
            source.write_text(json.dumps({
                "data":{x:[] for x in ("puerto-cadiz","puerto-jerez",
                                      "cadiz-puerto","cadiz-jerez",
                                      "jerez-puerto","jerez-cadiz")},
                "meta":{"checked_at":"2026-10-29T10:00:00+01:00"}
            }),encoding="utf-8")
            prepare(source,output)
            manifest=json.loads((output/"manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["id"],"/")
            self.assertEqual(manifest["scope"],"/")
            self.assertEqual(manifest["start_url"],"/")
            self.assertTrue(all(x["src"].startswith("/") and
                                not x["src"].startswith("/transport/")
                                for x in manifest["icons"]))
            sw=(output/"sw.js").read_text(encoding="utf-8")
            self.assertIn('ROOT="/"',sw)
            self.assertIn('transport-bahia-root-v3',sw)
            html=(output/"index.html").read_text(encoding="utf-8")
            self.assertNotIn('"/transport/',html)
            self.assertIn('rel="manifest" href="/manifest.json?v=4"',html)
            self.assertIn('navigator.serviceWorker.register("/sw.js", {scope:"/"})',html)
            self.assertTrue((output/"icon-512-maskable.png").is_file())
            # Larger RGB artwork is deliberately used for Android maskable icon.
            self.assertEqual((output/"icon-512-maskable-large-v2.png").read_bytes(),
                             (output/"icon-512-rgb.png").read_bytes())
            self.assertEqual([x["src"] for x in manifest["icons"]],
                             ["/icon-192-rgb-v2.png", "/icon-512-rgb-v2.png",
                              "/icon-512-maskable-large-v2.png"])
            for item in manifest["icons"]:
                self.assertTrue((output/item["src"].lstrip("/")).is_file())
                self.assertIn('ROOT+"'+item["src"].lstrip("/")+'"',sw)

    def test_original_path_scoped_pwa_is_not_changed(self):
        self.assertIn('href="/transport/manifest.json?v=2"',HTML)
        transformed=shell({},{"checked_at":"2026-10-29T10:00:00+01:00"})
        self.assertNotIn("/transport/",transformed)
        self.assertIn('id="officialAlerts"',transformed)

if __name__=="__main__":
    unittest.main()
