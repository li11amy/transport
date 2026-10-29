"""Adaptive launcher: existing larger RGB artwork fills more of Android mask."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "deploy" / "publish-larger-maskable.py"
spec = importlib.util.spec_from_file_location("maskable_upgrade", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MaskableUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.icon = (ROOT / "icon-512-rgb.png").read_bytes()
        self.manifest = {"icons": [
            {"src": "/icon-512-rgb.png", "purpose": "any"},
            {"src": "/icon-512-maskable.png", "purpose": "maskable"},
        ]}
        self.worker = 'const CACHE="transport-bahia-root-v1", ROOT="/";'
        self.html = '<link rel="manifest" href="/manifest.json?v=2">'

    def test_bump_cache_and_manifest_with_larger_icon(self):
        result = module.new_contents(self.icon, self.manifest, self.worker, self.html)
        self.assertEqual(result["icon-512-maskable.png"], self.icon)
        self.assertIn(b"transport-bahia-root-v2", result["sw.js"])
        self.assertIn(b"manifest.json?v=3", result["index.html"])
        self.assertNotIn(b"v1", result["sw.js"])

    def test_idempotence(self):
        self.assertIsNone(module.new_contents(
            self.icon, self.manifest,
            self.worker.replace("root-v1", "root-v2"),
            self.html.replace("v=2", "v=3")))

    def test_wrong_manifest_refused_without_change(self):
        bad = {"icons": [{"src": "/elsewhere.png", "purpose": "maskable"}]}
        with self.assertRaises(ValueError):
            module.new_contents(self.icon, bad, self.worker, self.html)

    def test_unexpected_worker_refused(self):
        with self.assertRaises(ValueError):
            module.new_contents(self.icon, self.manifest, "unknown-cache", self.html)

    def test_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as dirname:
            path = Path(dirname) / "asset.png"
            path.write_bytes(b"original")
            module.atomic_replace(path, self.icon)
            self.assertEqual(path.read_bytes(), self.icon)


if __name__ == "__main__":
    unittest.main()
