"""Self-contained red/green regressions for the read-only original C2 audit."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from c2_independent_inventory import NAMES, InvalidEvidence, audit, _json


class IndependentInventoryTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.fits = self.root / "fits"
        self.fits.mkdir()
        self.record = []
        for name in NAMES:
            p = self.fits / name
            p.mkdir()
            seed = int(name.split("-")[1][1:])
            lr = float(name.split("-")[2][2:])
            item = {"schema": "hcsn-c2-soft-wall-continuation-v1",
                    "arm": "hcsn", "seed": seed, "learning_rate": lr,
                    "production_execution": True, "confirmation_access": False,
                    "source_and_parent_inputs_unchanged": True,
                    "common_and_physical_weights_unchanged": True,
                    "source_before": {"code": "abc"}, "source_after": {"code": "abc"},
                    "status": "completed_development", "training_adequacy_established": True,
                    "cumulative_epochs_completed": 50}
            data = json.dumps(item).encode()
            (p / "result.json").write_bytes(data)
            self.record.append({"candidate": name, "file": "result.json",
                "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        self.manifest = self.root / "inventory.json"
        self.write_manifest()
        (self.root / "commands.jsonl").write_text('{"a":1}\n{"a":2}\n')

    def write_manifest(self):
        self.manifest.write_text(json.dumps({"schema": "hcsn-original-c2-fits-readonly-inventory-v1",
                                             "original_job_id": "original-not-restarted",
                                             "files": self.record}, sort_keys=True))
        # This fixture carries only six files; the real inventory has eight.
        # Fill two non-authoritative checkpoint reference slots.
        while len(self.record) < 8:
            self.record.append({"candidate": NAMES[len(self.record) - 6],
                                "file": "interrupted.pt", "size_bytes": 0,
                                "sha256": hashlib.sha256(b"").hexdigest()})
        self.manifest.write_text(json.dumps({"schema": "hcsn-original-c2-fits-readonly-inventory-v1",
                                             "original_job_id": "original-not-restarted",
                                             "files": self.record}, sort_keys=True))

    def test_six_pinned_producer_claims_never_pass_replay(self):
        result = audit(self.fits, self.root, self.manifest)
        self.assertEqual(result["pinned_producer_completed"], 6)
        self.assertFalse(result["all_six_independently_replayed"])
        self.assertEqual(result["scientific_admission"], "HOLD_NO_GO")
        self.assertFalse(result["controller_result_present"])

    def test_partial_and_torn_journal_denominator(self):
        (self.fits / NAMES[1] / "result.json").unlink()
        with (self.root / "commands.jsonl").open("ab") as stream:
            stream.write(b'{"incomplete":')
        result = audit(self.fits, self.root, self.manifest)
        self.assertEqual(result["pinned_producer_completed"], 5)
        self.assertEqual(result["producer_missing"], [NAMES[1]])
        self.assertEqual(result["controller_journal"]["complete_rows"], 2)
        self.assertTrue(result["controller_journal"]["torn"])

    def test_mutation_detected_against_original_hash(self):
        p = self.fits / NAMES[0] / "result.json"
        p.write_bytes(p.read_bytes() + b" ")
        result = audit(self.fits, self.root, self.manifest)
        self.assertEqual(result["checks"][0]["structural_status"], "CHANGED_RESULT")
        self.assertEqual(result["pinned_producer_completed"], 5)

    def test_duplicate_json_keys_and_nonfinite_rejected(self):
        with self.assertRaises(InvalidEvidence):
            _json(b'{"status":1,"status":2}')
        with self.assertRaises(InvalidEvidence):
            _json(b'{"n": NaN}')

    def test_result_symlink_rejected(self):
        p = self.fits / NAMES[0] / "result.json"
        p.unlink()
        p.symlink_to(self.fits / NAMES[1] / "result.json")
        with self.assertRaises(InvalidEvidence):
            audit(self.fits, self.root, self.manifest)

    def test_manifest_original_root_binding(self):
        import json
        m = json.loads(self.manifest.read_text())
        m["original_fits_root"] = "/not/the/observed/fits"
        self.manifest.write_text(json.dumps(m))
        with self.assertRaises(InvalidEvidence):
            audit(self.fits, self.root, self.manifest)

    def test_invalid_manifest_duplicates_rejected(self):
        self.record[0] = dict(self.record[1])
        self.write_manifest()
        with self.assertRaises(InvalidEvidence):
            audit(self.fits, self.root, self.manifest)


if __name__ == "__main__":
    unittest.main()

