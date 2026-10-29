"""Static HTML changes must remain limited to Renfe's public source link."""
import tempfile
import unittest
from pathlib import Path

from build_horarios import HTML
from deploy.patch_public_rail_source import patch_html, patch_file, source_block


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
