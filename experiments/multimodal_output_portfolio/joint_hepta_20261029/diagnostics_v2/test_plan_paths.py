"""Historical source identities survive a byte-preserving protocol relocation."""

from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import summarize


class ProtocolPathTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        files = {}
        for name in (*summarize.PLAN_FILES, "research_gate_v2.py", "controller_v2_protocol.json"):
            relative = summarize.PLAN_PATHS.get(name, name)
            data = (summarize.HERE / relative).read_bytes()
            destination = self.sources / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            files[summarize.PACKAGE + name] = hashlib.sha256(data).hexdigest()
        snapshot = {
            "commit": summarize.REGISTRATION,
            "files": files,
            "sha256": self.snapshot_digest(files),
        }
        self.receipt = {"before": snapshot, "after": deepcopy(snapshot), "source_bytes_unchanged": True}

    @staticmethod
    def snapshot_digest(files):
        data = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(data).hexdigest()

    def preserved_receipt(self, receipt):
        data = json.dumps(receipt).encode()
        destination = self.root / "SOURCE_RECEIPT.json.gz"
        destination.write_bytes(gzip.compress(data, mtime=0))
        return {"preserved_originals": [{
            "source_path": "SOURCE_RECEIPT.json",
            "stored_path": destination.name,
            "encoding": "gzip_original_bytes",
            "source_bytes": len(data),
            "source_sha256": hashlib.sha256(data).hexdigest(),
        }]}

    def test_original_receipt_binds_relocated_bytes_without_old_paths(self):
        self.assertTrue((self.sources / "protocols/controller_v2_development.json").is_file())
        self.assertTrue((self.sources / "protocols/controller_v2_distillation_development.json").is_file())
        for name in summarize.PLAN_FILES:
            self.assertFalse((self.sources / name).exists())
        manifest = self.preserved_receipt(self.receipt)
        with patch.object(summarize, "HERE", self.sources):
            self.assertEqual(summarize.source_binding(self.root, manifest), self.receipt)

    def test_relabeling_historical_receipt_keys_is_rejected(self):
        receipt = deepcopy(self.receipt)
        for snapshot in (receipt["before"], receipt["after"]):
            for name in summarize.PLAN_FILES:
                digest = snapshot["files"].pop(summarize.PACKAGE + name)
                snapshot["files"][summarize.PACKAGE + summarize.PLAN_PATHS[name]] = digest
            snapshot["sha256"] = self.snapshot_digest(snapshot["files"])
        manifest = self.preserved_receipt(receipt)
        with patch.object(summarize, "HERE", self.sources):
            with self.assertRaisesRegex(ValueError, "differs from the registered source"):
                summarize.source_binding(self.root, manifest)

    def test_changed_protocol_bytes_are_rejected(self):
        manifest = self.preserved_receipt(self.receipt)
        path = self.sources / "protocols/controller_v2_development.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with patch.object(summarize, "HERE", self.sources):
            with self.assertRaisesRegex(ValueError, "differs from the registered source"):
                summarize.source_binding(self.root, manifest)

    def test_new_summary_retains_original_plan_identifiers(self):
        inputs = self.root / "inputs"
        inputs.mkdir()
        result = summarize.run(inputs, self.root / "analysis")
        self.assertEqual(result["plan_sha256"], {
            "development_plan_v2.json": "622661ff7b8b2b38d866a96e25b42553d12479579309b6f5fec0e837f2c37653",
            "development_plan_distillation_v2.json": "d69b201890c11e0c44e3f7ab4ef345be86a1559ec3abacc7feda2258f110abdd",
        })
        self.assertFalse(result["research_qualified"])


if __name__ == "__main__":
    unittest.main()
