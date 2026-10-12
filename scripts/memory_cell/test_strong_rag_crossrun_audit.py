"""Synthetic hardening tests; real archived-model replay is explicitly opt-in."""

import copy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from strong_rag_crossrun_audit import (
    _safe_member,
    compare,
    digest,
    generate,
    open_sealed,
    strict_json,
)


def example_archive(path, *, corrupt=False, name="input.json", symlink=False):
    payload = b'{"answer":"ok"}'
    expected = hashlib.sha256(payload).hexdigest()
    with zipfile.ZipFile(path, "w") as z:
        info = zipfile.ZipInfo(name)
        if symlink:
            info.create_system = 3
            info.external_attr = 0o120777 << 16
        z.writestr(info, b'{"answer":"tampered"}' if corrupt else payload)
        z.writestr("SHA256SUMS", (expected + "  " + name + "\n").encode())
    return digest(path.read_bytes())


def row(*, answer="site_11111111 [E1]", prompt="f" * 64):
    return {
        "question_id": "example",
        "arm": "k1",
        "selected": ["event1"],
        "candidate_digest": "same-pool",
        "answer": answer,
        "receipt": {
            "reader_identity": "model",
            "reader_profile": "profile",
            "input_ids_digest": prompt,
            "input_tokens": 100,
            "generated_ids_digest": digest(answer.encode()),
            "delivered_evidence": [{"original_id": "event1", "excerpt": "original"}],
        },
    }


def mock_run(a):
    return {
        "model_identity": "model",
        "calibration": {
            "raw": {("example", "k1"): a},
            "scored": {("example", "k1"): {"strict_task_success": True}},
        },
        "evaluation": {
            "raw": {("example", "k1"): a},
            "scored": {("example", "k1"): {"strict_task_success": True}},
        },
    }


class CrossRunAuditTests(unittest.TestCase):
    def test_strict_json_no_duplicate_or_nonfinite_numbers(self):
        for blob in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.assertRaises(ValueError):
                strict_json(blob)

    def test_manifest_checks_original_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.zip"
            pin = example_archive(p)
            self.assertEqual(len(open_sealed(p, pin, manifest=True)), 2)
            pin = example_archive(p, corrupt=True)
            with self.assertRaisesRegex(ValueError, "changed original archive member"):
                open_sealed(p, pin, manifest=True)

    def test_wrong_zip_hash_is_never_a_soft_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.zip"
            example_archive(p)
            with self.assertRaisesRegex(ValueError, "outer archive SHA256"):
                open_sealed(p, "0" * 64, manifest=True)

    def test_archive_name_path_traversal_and_symlinks_rejected(self):
        for name in ("../secret", "/absolute", "a//b", "./shadow", "a\\b"):
            with self.assertRaises(ValueError):
                _safe_member(name)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.zip"
            pin = example_archive(p, symlink=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                open_sealed(p, pin, manifest=True)

    def test_unexpected_zip_member_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.zip"
            pin = example_archive(p)
            with self.assertRaisesRegex(ValueError, "unexpected independent replay"):
                open_sealed(p, pin, manifest=False)

    def test_same_prompt_different_answers_are_visible_not_repaired(self):
        a, b = mock_run(row()), mock_run(row(answer="site_22222222 [E1]"))
        b["evaluation"]["scored"][("example", "k1")]["strict_task_success"] = False
        differences = compare(a, b)
        self.assertEqual(len(differences["calibration"]), 1)
        self.assertEqual(len(differences["evaluation"]), 1)
        self.assertFalse(differences["evaluation"][0]["strict_success_b"])

    def test_cross_run_source_prompt_or_model_change_is_fatal(self):
        a, b = mock_run(row()), mock_run(row())
        b["model_identity"] = "different"
        with self.assertRaisesRegex(ValueError, "different reader"):
            compare(a, b)
        b["model_identity"] = "model"
        for field, value in (("selected", ["fake"]), ("candidate_digest", "moved")):
            changed = copy.deepcopy(b)
            changed["calibration"]["raw"][("example", "k1")][field] = value
            with self.assertRaisesRegex(ValueError, "source/prompt mismatch"):
                compare(a, changed)
        changed = copy.deepcopy(b)
        changed["evaluation"]["raw"][("example", "k1")]["receipt"][
            "input_ids_digest"
        ] = "0" * 64
        with self.assertRaisesRegex(ValueError, "input_ids_digest"):
            compare(a, changed)

    def test_cross_run_attempt_census_must_match(self):
        a, b = mock_run(row()), mock_run(row())
        b["evaluation"]["raw"].clear()
        with self.assertRaisesRegex(ValueError, "different question/arm"):
            compare(a, b)

    @unittest.skipUnless(
        os.environ.get("HEPTA_MEMORY_CROSSRUN_ARCHIVES"),
        "original verified ZIPs not attached",
    )
    def test_real_completed_model_artifacts(self):
        base = Path(os.environ["HEPTA_MEMORY_CROSSRUN_ARCHIVES"])
        paths = {
            "A": (
                base / "strongrag-825069-full.zip",
                base / "strongrag-825069-replay.zip",
            ),
            "B": (
                base / "strongrag-eba9-full.zip",
                base / "strongrag-eba9-replay.zip",
            ),
            "C": (
                base / "strongrag-c24-full.zip",
                base / "strongrag-c24-replay.zip",
            ),
        }
        report = generate(paths)
        self.assertEqual(report["total_actual_model_generations"], 336)
        self.assertEqual(
            report["distinct_inputs_with_output_variability"],
            {"calibration": 4, "evaluation": 9},
        )
        self.assertEqual(
            report["organization_extra_task_success_over_entity_time"],
            {"A": 0, "B": 0, "C": 0},
        )
        self.assertFalse(report["production_accepted"])
        changes = report["unstable_original_prompt_cases"]["evaluation"]
        self.assertEqual(sum(x["strict_task_outcome_changed"] for x in changes), 2)


if __name__ == "__main__":
    unittest.main()
