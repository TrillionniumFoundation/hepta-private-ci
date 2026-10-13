"""Fixture-only adversarial checks of exact-source cross-run archival audit."""

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
import memory_cell_crossrun_audit as audit


def answer():
    return {
        "question_id": "q", "arm": "k1", "kind": "new_fact",
        "answer": "site_11111111 [E1]", "selected": ["s1"],
        "status": "succeeded", "candidate_digest": "pool",
        "strict_task_success": True,
        "receipt": {
            "reader_identity": audit.MODEL_ID,
            "reader_profile": "profile",
            "token_limit": 2048,
            "input_ids_digest": "prompt",
            "generated_ids_digest": "output",
            "input_tokens": 80,
            "generated_tokens": 6,
            "delivered_evidence": [dict(label="E1", excerpt="original")],
            "seconds": 5.0,
        },
    }


class CrossRunSourceTests(unittest.TestCase):
    def test_same_real_task_and_model_surface_is_comparable(self):
        row = answer()
        other = deepcopy(row)
        other["receipt"]["seconds"] = 200
        self.assertEqual(audit.comparable_pairs({("q", "k1"): row}, {("q", "k1"): other}), 1)

    def test_output_rewrite_rejected(self):
        for field, value in (("answer", "site_22222222 [E1]"), ("selected", ["s2"]), ("strict_task_success", False)):
            left = answer()
            right = deepcopy(left)
            right[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit.comparable_pairs({("q", "k1"): left}, {("q", "k1"): right})

    def test_input_or_generated_ids_rewrite_rejected(self):
        for field in audit.RECEIPT_FIELDS:
            left = answer()
            right = deepcopy(left)
            right["receipt"][field] = "tampered"
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit.comparable_pairs({("q", "k1"): left}, {("q", "k1"): right})

    def test_missing_or_added_model_call_rejected(self):
        a = {("q", "k1"): answer()}
        with self.assertRaises(ValueError):
            audit.comparable_pairs(a, {})

    def test_json_duplicate_fields_and_nonfinite_rejected(self):
        for bad in (b'{"x": 1, "x": 2}', b'{"x": NaN}', b'{"x": Infinity}'):
            with self.subTest(raw=bad), self.assertRaises(ValueError):
                audit.strict_json(bad)

    def test_manifest_hash_and_census_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.zip"
            sample = b"original-model-answer"
            hashed = hashlib.sha256(sample).hexdigest()
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("raw.txt", sample)
                z.writestr("SHA256SUMS", f"{hashed}  raw.txt\n")
            pinned = hashlib.sha256(path.read_bytes()).hexdigest()
            data = audit.verified_zip(path, pinned, 1)
            self.assertEqual(data["raw.txt"], sample)
            with self.assertRaises(ValueError):
                audit.verified_zip(path, "0" * 64, 1)
            with self.assertRaises(ValueError):
                audit.verified_zip(path, pinned, 2)
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("raw.txt", b"replaced")
                z.writestr("SHA256SUMS", f"{hashed}  raw.txt\n")
            changed = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                audit.verified_zip(path, changed, 1)

    def test_unlisted_or_unsafe_archive_member_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.zip"
            for name in ("../escape.txt", "extra.txt"):
                with zipfile.ZipFile(path, "w") as z:
                    z.writestr(name, b"x")
                    z.writestr("SHA256SUMS", "")
                pinned = hashlib.sha256(path.read_bytes()).hexdigest()
                with self.subTest(name=name), self.assertRaises(ValueError):
                    audit.verified_zip(path, pinned, 1)

    def test_complete_real_archives_when_explicitly_supplied(self):
        folder = Path(os.environ.get("MEMORY_CELL_CROSSRUN_ARTIFACT_DIR", "/unmounted-archives"))
        args = [folder / name for name in (
            "event-inputs-20261010.zip",
            "strong-rag-prior-success-reader-38224780900.zip",
            "strong-rag-prior-success-replay-38224780900.zip",
            "memory-strong-rag-calibrated-reader-success-38389920977.zip",
            "memory-strong-rag-readonly-replay-success-38389920977.zip",
        )]
        if not all(p.is_file() for p in args):
            self.skipTest("Externally pinned GitHub Action ZIPs not bundled in source repository")
        result = audit.audit(*args)
        self.assertEqual(result["matched_calibration_original_answers"], 40)
        self.assertEqual(result["matched_evaluation_original_answers"], 72)
        self.assertEqual(result["full_organizer_vs_full_path_task_gain"], 0)
        self.assertFalse(result["production_accepted"])


if __name__ == "__main__":
    unittest.main()
