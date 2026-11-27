import copy
import gzip
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from verify_frozen_gzip import read_original
from verify_source_custody_container import identity

COLLECTION = (
    SCRIPTS.parent / "library-recovery/documentation-source-preservation-20261103"
)
spec = importlib.util.spec_from_file_location(
    "documentation_projection", COLLECTION / "verify_projection.py"
)
projection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projection)


class FrozenGzipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "projection"
        shutil.copytree(COLLECTION, self.root)
        self.index = json.loads((self.root / "GZIP_MANIFEST.json").read_bytes())
        self.entry = copy.deepcopy(self.index["members"][0])
        self.carrier = self.root / self.entry["carrier"]["path"]
        self.compressed = self.carrier.read_bytes()
        self.original = gzip.decompress(self.compressed)

    def replace_carrier(self, raw):
        self.carrier.write_bytes(raw)
        self.entry["carrier"].update(identity(raw))

    def test_complete_real_projection_preserves_original_manifest_contract(self):
        expected = {
            "candidate_count": 6,
            "notice_count": 0,
            "all_bytes_match_manifest": True,
            "archived_source_executed": False,
            "research_or_runtime_qualification": False,
        }
        self.assertEqual(projection.verify(self.root), expected)
        before = sorted(path.relative_to(self.root) for path in self.root.rglob("*"))
        for entry in self.index["members"]:
            raw = read_original(self.root, entry)
            self.assertEqual(identity(raw), entry["original"])
        self.assertEqual(
            sorted(path.relative_to(self.root) for path in self.root.rglob("*")), before
        )
        completed = subprocess.run(
            [sys.executable, "-B", str(COLLECTION / "verify_projection.py")],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(json.loads(completed.stdout), expected)

    def test_changed_carrier_is_rejected_by_current_consumer(self):
        self.carrier.write_bytes(
            self.compressed[:-1] + bytes([self.compressed[-1] ^ 1])
        )
        with self.assertRaisesRegex(ValueError, "carrier identity"):
            projection.verify(self.root)

    def test_changed_original_inventory_is_rejected(self):
        path = self.root / "SOURCE_MANIFEST.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "original manifest drift"):
            projection.verify(self.root)

    def test_replacement_carrier_inventory_cannot_rebind_originals(self):
        self.index["members"][0]["original"]["sha256"] = "0" * 64
        (self.root / "GZIP_MANIFEST.json").write_text(json.dumps(self.index))
        with self.assertRaisesRegex(ValueError, "carrier manifest drift"):
            projection.verify(self.root)

    def test_truncation_concatenation_and_trailing_bytes_are_rejected(self):
        # Refresh only the test carrier identity to exercise the gzip decoder's
        # independent checks after the transport integrity check has passed.
        for raw in (
            self.compressed[:-1],
            self.compressed[:-8],
            self.compressed + gzip.compress(b"", mtime=0),
            self.compressed + b"\0",
        ):
            with self.subTest(bytes=len(raw)):
                self.replace_carrier(raw)
                with self.assertRaisesRegex(
                    ValueError, "truncated, oversized or concatenated"
                ):
                    read_original(self.root, self.entry)

    def test_valid_gzip_with_wrong_original_bytes_is_rejected(self):
        altered = bytes([self.original[0] ^ 1]) + self.original[1:]
        self.replace_carrier(gzip.compress(altered, mtime=0))
        with self.assertRaisesRegex(ValueError, "original gzip payload identity"):
            read_original(self.root, self.entry)

    def test_decompression_cannot_exceed_original_bound(self):
        self.replace_carrier(gzip.compress(self.original + b"\n", mtime=0))
        with self.assertRaisesRegex(ValueError, "truncated, oversized or concatenated"):
            read_original(self.root, self.entry)

    def test_bad_gzip_crc_is_rejected_after_carrier_verification(self):
        raw = bytearray(self.compressed)
        raw[-8] ^= 1
        self.replace_carrier(bytes(raw))
        with self.assertRaises(zlib.error):
            read_original(self.root, self.entry)

    def test_symbolic_link_carrier_is_rejected(self):
        target = self.root / "outside.gz"
        self.carrier.rename(target)
        try:
            self.carrier.symlink_to(target)
        except OSError as error:
            self.skipTest(f"symbolic links unavailable: {error}")
        with self.assertRaisesRegex(ValueError, "regular single-link"):
            read_original(self.root, self.entry)

    def test_noncanonical_carrier_path_is_rejected(self):
        self.entry["carrier"]["path"] = "../outside.gz"
        with self.assertRaisesRegex(ValueError, "unsafe or noncanonical"):
            read_original(self.root, self.entry)

    def test_optimized_current_verifier_is_rejected(self):
        completed = subprocess.run(
            [sys.executable, "-B", "-O", str(COLLECTION / "verify_projection.py")],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("optimized Python is refused", completed.stderr)


if __name__ == "__main__":
    unittest.main()
