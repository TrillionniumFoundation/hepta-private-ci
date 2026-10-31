"""Preflight refuses occupied roots and scientific imports before any validator."""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from . import semantic_preflight as preflight


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.raw, self.cas = self.root / "raw", self.root / "raw_cas"
        self.raw.mkdir()
        self.cas.mkdir()
        self.config = {"raw_root": str(self.raw), "cas_root": str(self.cas)}

    def tearDown(self):
        self.temporary.cleanup()

    def test_occupied_raw_or_cas_cannot_enter_validators(self):
        for root in (self.raw, self.cas):
            with self.subTest(root=root.name):
                marker = root / "existing-fixture.bin"
                marker.write_bytes(b"preserve")
                with mock.patch.object(
                    preflight.importlib, "import_module"
                ) as imported:
                    with self.assertRaisesRegex(ValueError, "untouched fresh"):
                        preflight.validate_initial(self.config, {})
                    imported.assert_not_called()
                self.assertEqual(marker.read_bytes(), b"preserve")
                marker.unlink()

    def test_loaded_scientific_runtime_is_not_a_metadata_preflight(self):
        with (
            mock.patch.dict(
                sys.modules, {"torch": SimpleNamespace(synthetic_only=True)}
            ),
            mock.patch.object(preflight.importlib, "import_module") as imported,
        ):
            with self.assertRaisesRegex(ValueError, "already imported"):
                preflight.validate_initial(self.config, {})
            imported.assert_not_called()
        self.assertEqual(list(self.raw.iterdir()), [])
        self.assertEqual(list(self.cas.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
