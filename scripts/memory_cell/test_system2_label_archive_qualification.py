"""No-network, model-free archive qualification and fail-closed tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile

from system2_label_archive_qualification import (
    EXPECTED_RAW_SHA256,
    LABEL_COMMIT,
    LABEL_ZIP_SHA256,
    PARENT_ZIP_SHA256,
    archive_receipt,
    run,
    strict_json,
    verified_zip,
)


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.parent = os.environ.get("HEPTA_SYSTEM2_CARDINALITY_ARCHIVE")
        self.label = os.environ.get("HEPTA_SYSTEM2_COMPLETED_LABEL_ARCHIVE")

    def archives(self):
        if not self.parent or not self.label:
            self.skipTest("pinned completed archives not staged")
        return self.parent, self.label

    @staticmethod
    def semantic_approval(_source, _parent, *, generating_commit):
        if generating_commit != LABEL_COMMIT:
            raise ValueError("generating identity drift")
        return dict(
            planned_model_calls=140,
            source_pairs=60,
            source_commit=LABEL_COMMIT,
            original_seal=EXPECTED_RAW_SHA256,
            candidate_disposition="reader_answer_only_not_qualified",
            production_accepted=False,
        )

    def test_both_real_complete_archives_and_all_member_hashes(self):
        parent, label = self.archives()
        a = verified_zip(parent, PARENT_ZIP_SHA256)
        b = verified_zip(label, LABEL_ZIP_SHA256)
        self.assertEqual((len(a) - 1, len(b) - 1), (25, 25))
        self.assertEqual(len(archive_receipt(b)), 140)

    def test_real_full_provenance_census(self):
        _parent, label = self.archives()
        rows = archive_receipt(verified_zip(label, LABEL_ZIP_SHA256))
        self.assertEqual(len({r["qid"] for r in rows}), 20)
        self.assertEqual(
            sum(
                r["reader"]["generated_tokens"] == 64
                for r in rows
                if r["presentation"] == "unlabeled" and r["arm"] != "no_evidence"
            ),
            60,
        )

    def test_model_free_structural_report_exact_known_counts(self):
        parent, label = self.archives()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "receipt.json"
            receipt = run(parent, label, out, audit_fn=self.semantic_approval)
            self.assertTrue(out.is_file())
            self.assertEqual(receipt["new_model_calls"], 0)
            self.assertEqual(receipt["original_model_calls"], 140)
            self.assertEqual(
                receipt["conditions"]["single_fact:labeled"]["decoder_at_64"], 8
            )
            self.assertEqual(
                receipt["conditions"]["single_fact:unlabeled"]["decoder_at_64"], 20
            )
            self.assertEqual(
                receipt["conditions"]["target_decoy_two_first:unlabeled"][
                    "decoder_at_64"
                ],
                20,
            )
            self.assertEqual(
                receipt["conditions"]["decoy_one:unlabeled"]["decoder_at_64"], 20
            )
            self.assertEqual(
                receipt["labeled_minus_unlabeled_input_token_diff"]["single_fact"],
                [5] * 20,
            )
            self.assertEqual(
                receipt["labeled_minus_unlabeled_input_token_diff"][
                    "target_decoy_two_first"
                ],
                [10] * 20,
            )
            self.assertEqual(
                receipt["labeled_minus_unlabeled_input_token_diff"]["decoy_one"],
                [5] * 20,
            )
            self.assertFalse(receipt["causal_label_effect_established"])

    def test_incorrect_parent_external_digest_fails(self):
        p, label = self.archives()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "bad-parent.zip"
            out.write_bytes(Path(p).read_bytes() + b"forged")
            with self.assertRaisesRegex(ValueError, "ZIP SHA256"):
                run(out, label, Path(d) / "score.json", audit_fn=self.semantic_approval)
            self.assertFalse((Path(d) / "score.json").exists())

    def test_incorrect_completed_external_digest_fails(self):
        p, label = self.archives()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "bad-label.zip"
            out.write_bytes(Path(label).read_bytes() + b"forged")
            with self.assertRaisesRegex(ValueError, "ZIP SHA256"):
                run(p, out, Path(d) / "score.json", audit_fn=self.semantic_approval)

    def test_resealed_wrong_origins_refused(self):
        _p, label = self.archives()
        entries = verified_zip(label, LABEL_ZIP_SHA256)
        for field in ["tested-tree.txt", "source/system2_onehop_label_ablation.py"]:
            changed = dict(entries)
            changed[field] = b"wrong"
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, "generating"),
            ):
                archive_receipt(changed)

    def test_resealed_fake_answers_refused(self):
        _p, label = self.archives()
        entries = verified_zip(label, LABEL_ZIP_SHA256)
        changed = dict(entries)
        raw = changed["trial/raw-answers.jsonl"].replace(b'"succeeded"', b'"failed"', 1)
        changed["trial/raw-answers.jsonl"] = raw
        changed["trial/raw-seal.json"] = json.dumps(
            dict(
                rows=140, scoring_started=False, sha256=hashlib.sha256(raw).hexdigest()
            )
        ).encode()
        with self.assertRaisesRegex(ValueError, "answer SHA256 seal"):
            archive_receipt(changed)

    def test_planned_denominator_refuses_missing_record(self):
        _p, label = self.archives()
        entries = verified_zip(label, LABEL_ZIP_SHA256)
        changed = dict(entries)
        raw = b"\n".join(changed["trial/raw-answers.jsonl"].splitlines()[:-1]) + b"\n"
        changed["trial/raw-answers.jsonl"] = raw
        # Even a malicious attempt to re-sign the raw answer seal cannot change
        # the externally fixed original raw answer digest.
        changed["trial/raw-seal.json"] = json.dumps(
            dict(
                rows=139, scoring_started=False, sha256=hashlib.sha256(raw).hexdigest()
            )
        ).encode()
        with self.assertRaises(ValueError):
            archive_receipt(changed)

    def test_renamed_production_status_is_rejected(self):
        _p, label = self.archives()
        changed = dict(verified_zip(label, LABEL_ZIP_SHA256))
        summary = strict_json(changed["trial/summary.json"])
        summary["candidate_disposition"] = "independent_reader_confirmation_required"
        changed["trial/summary.json"] = json.dumps(summary).encode()
        with self.assertRaisesRegex(ValueError, "plan/claim"):
            archive_receipt(changed)

    def test_semantic_audit_cannot_silently_qualify_failed_reader(self):
        p, label = self.archives()
        with tempfile.TemporaryDirectory() as d:

            def fake(_source, _parent, *, generating_commit):
                return self.semantic_approval(
                    _source, _parent, generating_commit=generating_commit
                ) | dict(
                    candidate_disposition="independent_reader_confirmation_required"
                )

            path = Path(d) / "receipt.json"
            with self.assertRaisesRegex(ValueError, "semantic/source"):
                run(p, label, path, audit_fn=fake)
            self.assertFalse(path.exists())

    def test_semantic_exception_prevents_receipt(self):
        p, label = self.archives()
        with tempfile.TemporaryDirectory() as d:

            def fail(*_args, **_kwargs):
                raise RuntimeError("injected semantic scorer rejection")

            path = Path(d) / "receipt.json"
            with self.assertRaises(RuntimeError):
                run(p, label, path, audit_fn=fail)
            self.assertFalse(path.exists())

    def test_strict_json_rejects_duplicate_and_nan(self):
        for value in (b'{"score":1,"score":2}', b'{"score":NaN}'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                strict_json(value)

    def test_duplicate_zip_path_and_missing_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "duplicate.zip"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(p, "w") as z:
                    z.writestr("a", b"a")
                    z.writestr("a", b"b")
                    z.writestr("SHA256SUMS", b"")
            with self.assertRaisesRegex(ValueError, "unsafe or duplicate"):
                verified_zip(p, hashlib.sha256(p.read_bytes()).hexdigest())
            p = Path(d) / "without_manifest.zip"
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("a", b"a")
            with self.assertRaisesRegex(ValueError, "missing member manifest"):
                verified_zip(p, hashlib.sha256(p.read_bytes()).hexdigest())

    def test_archive_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "attack.zip"
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("../leak", b"bad")
                z.writestr("SHA256SUMS", b"")
            with self.assertRaisesRegex(ValueError, "unsafe"):
                verified_zip(p, hashlib.sha256(p.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
