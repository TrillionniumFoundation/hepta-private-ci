import hashlib
import importlib.util
import io
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

PATH = Path(__file__).resolve().parents[1] / "tools/install-font-diagnostic-browser.py"
SPEC = importlib.util.spec_from_file_location("font_browser", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BrowserArchiveTests(unittest.TestCase):
    def archive(self, extra=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(MODULE.BINARY, b"fixture")
            if extra is not None:
                archive.writestr(extra, b"bad")
        stream.seek(0)
        return zipfile.ZipFile(stream)

    def test_rejects_traversal_absolute_and_symlink_members(self):
        for name in ["../outside", "/outside", "other/file", "chrome-headless-shell-linux64/../outside"]:
            with self.archive(name) as archive, self.assertRaises(ValueError):
                MODULE.checked_members(archive)
        link = zipfile.ZipInfo("chrome-headless-shell-linux64/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.archive(link) as archive, self.assertRaises(ValueError):
            MODULE.checked_members(archive)

    def test_normal_member_set_and_missing_executable(self):
        with self.archive("chrome-headless-shell-linux64/resources.pak") as archive:
            self.assertEqual(len(MODULE.checked_members(archive)), 2)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("chrome-headless-shell-linux64/other", b"x")
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive, self.assertRaises(ValueError):
            MODULE.checked_members(archive)

    def test_executable_hash_and_regular_file_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / MODULE.BINARY
            binary.parent.mkdir()
            binary.write_bytes(b"fixture")
            with self.assertRaises(ValueError):
                MODULE.verify(root)
            with patch.object(MODULE, "BINARY_SHA", hashlib.sha256(b"fixture").hexdigest()):
                self.assertEqual(MODULE.verify(root), binary)
                target = binary.with_name("actual")
                binary.rename(target)
                binary.symlink_to(target)
                with self.assertRaises(ValueError):
                    MODULE.verify(root)

    def test_existing_destination_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(MODULE.urllib.request, "urlopen") as network:
            with self.assertRaises(ValueError):
                MODULE.install(Path(temporary))
            network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
