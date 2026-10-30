"""Static HTML changes must remain limited to Renfe's public source link."""
import tempfile
import unittest
from pathlib import Path

from build_horarios import HTML
import importlib.util

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "patch-public-rail-source.py"
spec = importlib.util.spec_from_file_location("patch_public_rail_source", SCRIPT)
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)
patch_html, patch_file, source_block = patcher.patch_html, patcher.patch_file, patcher.source_block


class PassengerSourcePatchTests(unittest.TestCase):
    def test_replace_legacy_link_with_human_source(self):
        new = source_block(HTML)
        self.assertIn("technicalRenfe", new)
        old = """      if(t.fuente_cambio) {
        const source=document.createElement("a");
        source.href=t.fuente_cambio;
        source.target="_blank";
        source.rel="noopener noreferrer";
        source.textContent="Fuente";
        details.appendChild(source);
      }
"""
        fake = "head\n" + old + "      extra.appendChild(details);\nfoot"
        result = patch_html(fake, HTML)
        self.assertEqual(result, "head\n" + new + "      extra.appendChild(details);\nfoot")
        self.assertEqual(patch_html(result, HTML), result)

    def test_remove_meaningless_md_source_from_already_patched_public_html(self):
        current = source_block(HTML).replace(
            '        } else if(technicalRenfe){\n'
            '          // MD realtime JSON is not a passenger page: omit empty attribution.\n',
            '        } else if(technicalRenfe){\n'
            '          const source=document.createElement("span");\n'
            '          source.textContent="Fuente: Renfe (datos oficiales en tiempo real)";\n'
            '          details.appendChild(source);\n')
        self.assertIn("datos oficiales en tiempo real",current)
        old_page="header\n"+current+"      extra.appendChild(details);\nfooter"
        patched=patch_html(old_page,HTML)
        self.assertNotIn("datos oficiales en tiempo real",patched)
        self.assertEqual(patch_html(patched,HTML),patched)

    def test_refuse_unrecognized_public_html(self):
        with self.assertRaises((ValueError, IndexError)):
            patch_html("other completely different content", HTML)

    def test_dry_run_never_modifies_published_file(self):
        new = source_block(HTML)
        old = """      if(t.fuente_cambio) {
        const source=document.createElement("a");
        source.href=t.fuente_cambio;
        source.target="_blank";
        source.rel="noopener noreferrer";
        source.textContent="Fuente";
        details.appendChild(source);
      }
"""
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"index.html"
            content=old+"      extra.appendChild(details);"
            path.write_text(content,encoding="utf-8")
            self.assertTrue(patch_file(path,HTML,write=False))
            self.assertEqual(path.read_text(encoding="utf-8"),content)
            self.assertTrue(patch_file(path,HTML,write=True))
            self.assertEqual(path.read_text(encoding="utf-8"),new+"      extra.appendChild(details);")


if __name__=="__main__":
    unittest.main()
