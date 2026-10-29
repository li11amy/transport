"""Regression: Chrome 144+ requires changed icon URLs, not just PNG bytes."""
import importlib.util
import json
import unittest
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/"deploy"/"subdomain"/"publish-versioned-icons.py"
spec=importlib.util.spec_from_file_location("publish_versioned_icons",SCRIPT)
publisher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class LauncherIconRefreshTests(unittest.TestCase):
    def test_old_icon_urls_changed_without_changing_app_identity(self):
        manifest={
            "id":"/","scope":"/","start_url":"/","display":"standalone",
            "icons":[
                {"src":"/icon-192-rgb.png","purpose":"any"},
                {"src":"/icon-512-rgb.png","purpose":"any"},
                {"src":"/icon-512-maskable.png","purpose":"maskable"},
            ],
        }
        html='<link rel="manifest" href="/manifest.json?v=3">'
        worker='const CACHE="transport-bahia-root-v2", ROOT="/";\n'+(
            'const ASSETS=[ROOT,ROOT+"icon-512-maskable.png"];')
        m,h,w=publisher.prepare(json.dumps(manifest).encode(),html,worker)
        latest=json.loads(m)
        self.assertEqual(latest["id"],"/")
        self.assertEqual(
            [x["src"] for x in latest["icons"]],
            ["/icon-192-rgb-v2.png", "/icon-512-rgb-v2.png",
             "/icon-512-maskable-large-v2.png"],
        )
        self.assertIn(b"manifest.json?v=4",h)
        self.assertIn(b"transport-bahia-root-v3",w)
        for item in latest["icons"]:
            self.assertIn(('ROOT+"'+item["src"][1:]+'"').encode(),w)

    def test_replay_is_idempotent(self):
        initial={
            "id":"/","scope":"/","start_url":"/",
            "icons":[{"src":"/"+v,"purpose":"maskable" if "maskable" in v else "any"}
                     for v in publisher.ICON_MAP.values()],
        }
        html='<link rel="manifest" href="/manifest.json?v=4">'
        worker='const CACHE="transport-bahia-root-v3", ROOT="/";\n'+(
            'const ASSETS=[ROOT,ROOT+"icon-512-maskable.png",'+
            ','.join('ROOT+"'+v+'"' for v in publisher.ICON_MAP.values())+'];')
        m,h,w=publisher.prepare(json.dumps(initial).encode(),html,worker)
        self.assertEqual(json.loads(m)["icons"],initial["icons"])
        self.assertEqual(h.decode(),html)
        self.assertEqual(w.decode(),worker)

    def test_other_app_scopes_refused(self):
        manifest={
            "id":"/transport/","scope":"/transport/","start_url":"/transport/",
            "icons":[{"src":"/icon-512-maskable.png"}],
        }
        with self.assertRaisesRegex(RuntimeError,"Not the root"):
            publisher.prepare(json.dumps(manifest).encode(),
                              '<link href="manifest.json?v=3">','ROOT="/"')

if __name__=="__main__":
    unittest.main()
