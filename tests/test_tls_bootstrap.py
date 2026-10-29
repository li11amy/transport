"""Offline checks for isolated transport ACME HTTP-01 bootstrap."""
import importlib.util
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SRC=Path(__file__).resolve().parents[1]/"deploy"/"subdomain"


def load(name):
    spec=importlib.util.spec_from_file_location(name,SRC/(name+".py"))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CertificateBootstrapTests(unittest.TestCase):
    def test_owned_bootstrap_can_be_created_and_rolled_back(self):
        module=load("bootstrap_http")
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            available=root/"available"/"transport.peluche-ebanache.com"
            enabled=root/"enabled"/"transport.peluche-ebanache.com"
            www=root/"www"
            for target in (available.parent, enabled.parent, www):
                target.mkdir(parents=True)
            (www/"index.html").write_text("PWA",encoding="utf-8")
            with patch.object(module,"AVAILABLE",available), \
                 patch.object(module,"ENABLED",enabled), \
                 patch.object(module,"ROOT",www), \
                 patch.object(module,"run",return_value=types.SimpleNamespace(
                     returncode=0,stderr="",stdout="")):
                module.setup()
                self.assertTrue(module.owned())
                self.assertTrue(enabled.is_symlink())
                self.assertIn("location ^~ /.well-known/acme-challenge/",
                              available.read_text())
                module.rollback()
                self.assertFalse(available.exists())
                self.assertFalse(enabled.is_symlink())

    def test_existing_unowned_vhost_is_never_overwritten(self):
        module=load("bootstrap_http")
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            available=root/"available"; available.write_text("existing nginx vhost")
            enabled=root/"enabled"
            with patch.object(module,"AVAILABLE",available), \
                 patch.object(module,"ENABLED",enabled):
                with self.assertRaisesRegex(RuntimeError,"already exists"):
                    module.setup()
                self.assertEqual(available.read_text(),"existing nginx vhost")

    def test_challenge_remains_in_final_https_configuration(self):
        https=(SRC/"enable_https.py").read_text(encoding="utf-8")
        bootstrap=(SRC/"bootstrap_http.py").read_text(encoding="utf-8")
        shell=(SRC/"issue-and-enable-https.sh").read_text(encoding="utf-8")
        self.assertIn("PREFERRED_CERT",https)
        self.assertIn("OWNED_BOOTSTRAP",https)
        self.assertIn("previous=AVAILABLE.read_text",https)
        self.assertIn('try_files $uri =404;',https)
        self.assertIn('try_files $uri =404;',bootstrap)
        self.assertIn('sudo certbot certonly --webroot',shell)
        self.assertIn('--cert-name "$DOMAIN"',shell)
        self.assertIn('--deploy-hook "$reload_cmd"',shell)
        self.assertIn("curl -fsSL",shell)
        self.assertIn("trap cleanup EXIT",shell)


if __name__=="__main__":
    unittest.main()
