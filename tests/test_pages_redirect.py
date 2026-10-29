"""GitHub Pages must redirect, never serve an old embedded schedule.

The VPS serves its own independent static shells and shared JSON. This
regression prevents reintroducing stale page data at the retired old URL.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = "https://transport.peluche-ebanache.com/"


class LegacyPagesRedirectTests(unittest.TestCase):
    def test_pages_index_is_an_immediate_redirect_not_timetable(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('window.location.replace("' + CANONICAL + '")', html)
        self.assertIn('content="0; url=' + CANONICAL + '"', html)
        self.assertIn('rel="canonical" href="' + CANONICAL + '"', html)
        self.assertIn('href="' + CANONICAL + '"', html)
        self.assertNotIn('SERVICE_META', html)
        self.assertNotIn('transport_data.json', html)
        self.assertNotIn('navigator.serviceWorker.register', html)
        self.assertNotIn('const trips=', html)

    def test_legacy_deep_links_redirect_too(self):
        html = (ROOT / "404.html").read_text(encoding="utf-8")
        self.assertIn('window.location.replace("' + CANONICAL + '")', html)
        self.assertIn('rel="canonical" href="' + CANONICAL + '"', html)

    def test_old_service_worker_discards_cached_timetables(self):
        script = (ROOT / "sw.js").read_text(encoding="utf-8")
        self.assertIn('startsWith("transport-bahia-")', script)
        self.assertIn('caches.delete(key)', script)
        self.assertIn('self.skipWaiting()', script)
        self.assertIn('self.clients.claim()', script)
        self.assertIn('RETIRED_PAGES = self.location.hostname === "li11amy.github.io"', script)
        self.assertIn('if(event.request.mode==="navigate")', script)
        self.assertIn('Response.redirect(NEW_HOME,302)', script)
        # Production copies of this same worker must retain offline/data logic.
        self.assertIn('const CACHE="transport-bahia-v4", ROOT="/transport/"', script)
        self.assertIn('cache.addAll(ASSETS)', script)
        self.assertIn('ROOT+"transport_data.json"', script)
        self.assertIn(CANONICAL, script)

    def test_readme_identifies_live_architecture(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        current = readme.split("## Historical deployment and migration notes")[0]
        self.assertIn(CANONICAL, current)
        self.assertIn("/srv/www/transport-pwa-root", current)
        self.assertIn("transport-update.timer", current)
        self.assertIn("--data-only", current)
        self.assertIn("Do not publish schedules from GitHub Pages", current)


if __name__ == "__main__":
    unittest.main()
