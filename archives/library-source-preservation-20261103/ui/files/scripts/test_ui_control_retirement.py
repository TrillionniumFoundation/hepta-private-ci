import hashlib
import io
import json
from pathlib import Path
import runpy
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
MODULE = runpy.run_path(str(ROOT / "scripts/ui-control-oracle.py"))


class RetirementTests(unittest.TestCase):
    def test_exact_oracle_is_complete_and_not_a_product(self):
        manifest, members = MODULE["verified_members"]()
        self.assertEqual(manifest["sourceCommit"], "5c0bbe30e4a5d408c430e8ab1fcc25638042d82a")
        self.assertFalse(manifest["activeProductEntrypoint"])
        self.assertIn("apps/hepta-control-ui/src/runtime-client.js", members)
        self.assertIn("apps/hepta-control-ui/web/main.js", members)
        self.assertEqual(len(members), 128)

    def test_ui_product_has_no_javascript_entrypoint(self):
        package = json.loads((ROOT / "apps/hepta-control-ui/package.json").read_text())
        self.assertEqual(package["exports"], {})
        self.assertNotIn("build", package["scripts"])
        self.assertFalse(list((ROOT / "apps/hepta-control-ui/src").glob("*.js")))
        self.assertFalse((ROOT / "apps/hepta-control-ui/web/main.js").exists())
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            text = path.read_text()
            self.assertNotIn("node --test apps/hepta-control-ui/test/", text)
            self.assertNotIn("apps/hepta-control-ui/dist/", text)

    def test_archive_tamper_path_escape_and_nonregular_members_fail_closed(self):
        for name, kind in [("../outside", "file"), ("..\\outside", "file"), ("C:outside", "file"), ("safe", "link")]:
            with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                    member = tarfile.TarInfo(name)
                    if kind == "link":
                        member.type = tarfile.SYMTYPE
                        member.linkname = "../outside"
                        archive.addfile(member)
                    else:
                        member.size = 1
                        archive.addfile(member, io.BytesIO(b"x"))
                payload = stream.getvalue()
                (root / "test.tar.gz").write_bytes(payload)
                manifest = {"activeProductEntrypoint": False, "archive": "test.tar.gz",
                            "archiveBytes": len(payload), "archiveSha256": hashlib.sha256(payload).hexdigest(),
                            "files": [{"pathComponents": name.split("/"), "bytes": 1, "sha256": hashlib.sha256(b"x").hexdigest()}]}
                (root / "MANIFEST.json").write_text(json.dumps(manifest))
                function = MODULE["verified_members"]
                with patch.dict(function.__globals__, {"ORACLE": root}), self.assertRaises(ValueError):
                    function()
