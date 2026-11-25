import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fonts", ROOT / "tools/prepare-fonts.py")
fonts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fonts)


class FontPreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.value, self.identity = fonts.manifest()
        self.payload = b"bounded-font-fixture"
        self.small = json.loads(json.dumps(self.value))
        for entry in self.small["assets"]:
            entry.update(bytes=len(self.payload), sha256=fonts.sha(self.payload))

    def prepare(self, **kwargs):
        with patch.object(fonts, "manifest", return_value=(self.small, self.identity)):
            return fonts.prepare(self.root / "cache", **kwargs)

    def test_missing_offline_fails_without_network(self):
        with patch.object(fonts, "download", side_effect=AssertionError("network")):
            with self.assertRaisesRegex(ValueError, "missing offline"):
                self.prepare(offline=True)

    def test_exact_download_reuses_offline_and_installs_identical_bytes(self):
        with patch.object(fonts, "download", return_value=self.payload) as fetch:
            result = self.prepare()
            self.assertEqual(fetch.call_count, 2)
        with patch.object(fonts, "download", side_effect=AssertionError("network")):
            reused = self.prepare(offline=True, install=self.root / "installed")
        self.assertEqual(result, reused)
        for entry in result["assets"]:
            self.assertEqual((self.root / "installed" / entry["file"]).read_bytes(), self.payload)

    def test_corrupt_cache_fails_without_silent_redownload(self):
        with patch.object(fonts, "download", return_value=self.payload):
            result = self.prepare()
        Path(result["assets"][0]["inputPath"]).write_bytes(b"X" * len(self.payload))
        with patch.object(fonts, "download", side_effect=AssertionError("network")):
            for offline in (False, True):
                with self.assertRaisesRegex(ValueError, "bytes mismatch"):
                    self.prepare(offline=offline)

    def test_invalid_download_never_publishes_cache_entry(self):
        with patch.object(fonts, "download", return_value=self.payload + b"oversize"):
            with self.assertRaisesRegex(ValueError, "bytes mismatch"):
                self.prepare()
        self.assertFalse(list(self.root.rglob("*.otf")))

    def test_atomic_failure_removes_temporary_file(self):
        with patch.object(fonts.os, "replace", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                fonts.atomic_write(self.root / "font.otf", self.payload)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_symlink_cache_is_rejected(self):
        with patch.object(fonts, "download", return_value=self.payload):
            result = self.prepare()
        path = Path(result["assets"][0]["inputPath"])
        path.unlink()
        path.symlink_to(self.root / "outside")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.prepare(offline=True)

    def test_native_and_web_catalogs_bind_identical_resources(self):
        native = json.loads((ROOT.parent / "hepta-native/resources/NATIVE-ASSETS.json").read_text())
        actual = [a for a in native["assets"] if a["license_group"] == "noto-sans-cjk-ofl-1.1"]
        expected = [{k: a[k] for k in ("logical", "bytes", "sha256", "license_group")} for a in self.value["assets"]]
        self.assertEqual(actual, expected)
        self.assertEqual(sum(a["bytes"] for a in actual), 16_874_504)
        self.assertLessEqual(sum(a["bytes"] for a in actual), 17_000_000)
        self.assertEqual(len(native["assets"]), 29)
        styles = (ROOT / "rust/robrix-ui/src/robrix/styles.rs").read_text()
        for weight in ("Regular", "Bold"):
            self.assertIn("resources/fonts/NotoSansSC-" + weight + ".otf", styles)
            self.assertIn("resources/LXGWWenKai" + weight + ".ttf", styles)
        self.assertEqual((ROOT.parent / "hepta-native/resources/notices/Noto-Sans-CJK-2.004-OFL.txt").read_bytes(),
                         (fonts.MANIFEST.parent / "OFL.txt").read_bytes())


class DesktopStagingTests(unittest.TestCase):
    def test_concurrent_stages_are_distinct_and_cleanup_only_their_own_tree(self):
        spec = importlib.util.spec_from_file_location("desktop", ROOT / "tools/run-desktop.py")
        desktop = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(desktop)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            for name in ("core", "web", "robrix-ui"):
                (source / name).mkdir()
                (source / name / "Cargo.toml").write_text(name)
            for name in ("Cargo.toml", "Cargo.lock"):
                (source / name).write_text("fixture")
            def prepare(*, offline, install):
                self.assertTrue(offline)
                install.mkdir(parents=True)
                (install / "font.otf").write_bytes(b"verified fixture")
            with desktop.staged_workspace(source, prepare) as first:
                original = first / "robrix-ui/resources/fonts/font.otf"
                with desktop.staged_workspace(source, prepare) as second:
                    self.assertNotEqual(first, second)
                    self.assertEqual(original.read_bytes(), b"verified fixture")
                    self.assertTrue((second / "robrix-ui/resources/fonts/font.otf").exists())
                self.assertFalse(second.exists())
                self.assertEqual(original.read_bytes(), b"verified fixture")
            self.assertFalse(first.exists())
            self.assertEqual((source / "core/Cargo.toml").read_text(), "core")

    def test_failed_staging_does_not_remove_an_existing_preview(self):
        spec = importlib.util.spec_from_file_location("desktop", ROOT / "tools/run-desktop.py")
        desktop = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(desktop)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            survivor = source / "target/existing-preview/font.otf"
            survivor.parent.mkdir(parents=True)
            survivor.write_bytes(b"active")
            with self.assertRaises(FileNotFoundError):
                with desktop.staged_workspace(source, lambda **kw: None):
                    self.fail("incomplete source must not become a preview")
            self.assertEqual(survivor.read_bytes(), b"active")


if __name__ == "__main__":
    unittest.main()
