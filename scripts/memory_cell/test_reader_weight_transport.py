"""Pure transport-mechanics tests with synthetic bytes, not a model run."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from reader_weight_transport import MODEL_FILES, _digest_inventory, verify_reader_transport


class ReaderTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in sorted(MODEL_FILES):
            (self.root / name).write_bytes(("synthetic-" + name).encode())
        self.identity = self.identity_of_current()
        self.manifest()

    def identity_of_current(self):
        inv = {name: {"sha256": hashlib.sha256((self.root / name).read_bytes()).hexdigest(),
                      "bytes": (self.root / name).stat().st_size}
               for name in sorted(MODEL_FILES)}
        return _digest_inventory(inv)

    def manifest(self, *, legacy=False):
        lines = [hashlib.sha256((self.root / name).read_bytes()).hexdigest()
                 + "  ./" + name for name in sorted(MODEL_FILES)]
        if legacy:
            lines.append("0" * 64 + "  ./SHA256SUMS")
        (self.root / "SHA256SUMS").write_text("\n".join(lines) + "\n")

    def verify(self, **kw):
        return verify_reader_transport(self.root, expected_identity=self.identity, **kw)

    def test_valid_complete_manifest_with_no_self_reference(self):
        receipt = self.verify()
        self.assertEqual(receipt["verified_files"], 8)
        self.assertFalse(receipt["legacy_self_entry_not_model_data"])
        self.assertFalse(receipt["production_accepted"])

    def test_legacy_self_checksum_is_not_accepted_by_default(self):
        self.manifest(legacy=True)
        with self.assertRaisesRegex(ValueError, "self-referential"):
            self.verify()

    def test_legacy_self_checksum_needs_explicit_policy_and_checks_all_real_bytes(self):
        self.manifest(legacy=True)
        self.assertTrue(self.verify(allow_legacy_self_entry=True)[
            "legacy_self_entry_not_model_data"])
        (self.root / "config.json").write_text("forged")
        with self.assertRaisesRegex(ValueError, "transport manifest"):
            self.verify(allow_legacy_self_entry=True)

    def test_refuse_extra_file(self):
        (self.root / "secret.json").write_text("x")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.verify()

    def test_refuse_missing_file(self):
        (self.root / "vocab.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            self.verify()

    def test_refuse_symlink_even_if_same_contents(self):
        (self.root / "vocab.json").unlink()
        (self.root / "vocab.json").symlink_to("config.json")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.verify()

    def test_missing_model_checksum_denied(self):
        data = (self.root / "SHA256SUMS").read_text().splitlines()
        (self.root / "SHA256SUMS").write_text("\n".join(data[:-1]) + "\n")
        with self.assertRaisesRegex(ValueError, "every model file"):
            self.verify()

    def test_duplicate_checksum_denied(self):
        path = self.root / "SHA256SUMS"
        path.write_text(path.read_text() + path.read_text().splitlines()[0] + "\n")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.verify()

    def test_file_digest_drift_denied(self):
        (self.root / "model.safetensors").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "differs from transport"):
            self.verify()

    def test_manifest_compatible_but_registered_identity_changed(self):
        (self.root / "model.safetensors").write_bytes(b"new approved-looking bytes")
        self.manifest()
        with self.assertRaisesRegex(ValueError, "registered snapshot"):
            self.verify()

    def test_disallow_extra_checksum_entry_even_in_legacy_mode(self):
        self.manifest(legacy=True)
        path = self.root / "SHA256SUMS"
        path.write_text(path.read_text() + "1" * 64 + "  ./unlisted.bin\n")
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            self.verify(allow_legacy_self_entry=True)

    def test_model_metadata_cannot_be_read_from_self_checksum(self):
        self.manifest(legacy=True)
        path = self.root / "SHA256SUMS"
        path.write_text(path.read_text() + "1" * 64 + "  ./SHA256SUMS\n")
        with self.assertRaisesRegex(ValueError, "self-referential"):
            self.verify(allow_legacy_self_entry=True)

    def test_manifest_nonascii_rejected(self):
        (self.root / "SHA256SUMS").write_bytes(b"\xff")
        with self.assertRaisesRegex(ValueError, "ASCII"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
