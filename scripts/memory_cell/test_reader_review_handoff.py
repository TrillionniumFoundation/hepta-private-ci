"""Hermetic tests for a BLANK independent-review handoff, not verdicts."""

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reader_originals_attestation import load_strict_json_file
from reader_review_handoff import prepare_cases, prepare_handoff
from test_reader_originals_attestation import example


def lines(path):
    return [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]


class BlindedReviewHandoffTests(unittest.TestCase):
    def setUp(self):
        self.cohort, self.binding, self.reviewed, self.originals = example()
        self.file_sha = "a" * 64

    def test_mechanical_ledger_has_no_fake_verdict_fields(self):
        cases, ledger = prepare_cases(self.originals)
        self.assertEqual(len(cases), 8)
        self.assertEqual(len(ledger), 8)
        for value in ledger.values():
            self.assertNotIn("grounded_and_cited", value)
            self.assertNotIn("exact_refusal", value)
            self.assertEqual(len(value["question_sha256"]), 64)

    def test_raw_label_echo_is_visible_to_reviewers_not_prejudged(self):
        # An actually observed E1 echo is NOT an exact refusal, but the blind
        # handoff must remain possible so humans can assess that failure.
        self.originals["items"][0]["raw_answer"] = "E1"
        cases, ledger = prepare_cases(self.originals)
        self.assertEqual(cases["q1", "no_evidence"]["raw_answer"], "E1")
        self.assertTrue(
            all(
                "exact_refusal" not in item and "grounded_and_cited" not in item
                for item in ledger.values()
            )
        )
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / "handoff"
            receipt = prepare_handoff(
                self.originals,
                source_file_sha256=self.file_sha,
                output=out,
                salt=b"\x09" * 32,
            )
            self.assertEqual(
                (receipt["positions"], receipt["independent_reviews"]), (8, 0)
            )
            views = lines(out / "review-questions.jsonl")
            forms = lines(out / "reviewer-blank-form.jsonl")
            self.assertTrue(any(v["raw_reader_answer"] == "E1" for v in views))
            self.assertTrue(
                all(
                    row["exact_refusal"] is None and row["grounded_and_cited"] is None
                    for row in forms
                )
            )

    def test_passing_handoff_cannot_substitute_for_signed_refusal_review(self):
        # Machine-derived internal validation data must never be admitted as
        # independently reviewed verdicts by the later Reader gate.
        from reader_originals_attestation import audit_originals

        _, ledger = prepare_cases(self.originals)
        self.assertEqual(
            audit_originals(
                self.cohort, self.binding, list(ledger.values()), self.originals
            ),
            "reviewed-exact-refusal-does-not-match-raw-reader-text",
        )

    def test_exact_complete_private_handoff_with_blank_human_forms(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / "handoff"
            receipt = prepare_handoff(
                self.originals,
                source_file_sha256=self.file_sha,
                output=out,
                salt=b"\x01" * 32,
            )
            self.assertEqual(
                receipt,
                dict(
                    positions=8,
                    independent_reviews=0,
                    neural_calls=0,
                    production_accepted=False,
                ),
            )
            self.assertEqual(out.stat().st_mode & 0o077, 0)
            cases = lines(out / "review-questions.jsonl")
            forms = lines(out / "reviewer-blank-form.jsonl")
            mappings = lines(out / "operator-private-map.jsonl")
            self.assertEqual(len(cases), len(forms))
            self.assertEqual(len(forms), len(mappings))
            self.assertEqual(len({v["ticket"] for v in cases}), 8)
            self.assertEqual(
                {v["ticket"] for v in cases}, {v["ticket"] for v in mappings}
            )
            self.assertEqual({v["ticket"] for v in cases}, {v["ticket"] for v in forms})
            self.assertTrue(
                all(
                    v["grounded_and_cited"] is None
                    and v["exact_refusal"] is None
                    and v["cited_semantically_supported"] is None
                    for v in forms
                )
            )
            self.assertTrue(
                all(
                    "condition" not in view and "raw_reader_answer" in view
                    for view in cases
                )
            )
            self.assertEqual(
                {row["condition"] for row in mappings},
                {
                    "no_evidence",
                    "ordinary_retrieval",
                    "human_sufficient",
                    "critical_premise_removed",
                },
            )
            for path in out.iterdir():
                self.assertEqual(path.stat().st_mode & 0o077, 0)
            info = json.loads((out / "handoff-receipt.json").read_text())
            self.assertFalse(info["production_accepted"])
            self.assertFalse(info["independent_human_adjudication_obtained"])
            self.assertEqual(info["reviewer_signatures"], 0)
            self.assertEqual(info["reviewer_verdicts_filled"], 0)
            for name, digest in info["written_file_sha256"].items():
                self.assertEqual(
                    hashlib.sha256((out / name).read_bytes()).hexdigest(), digest
                )

    def test_real_unicode_excerpt_is_valid_and_preserved_without_gold(self):
        record = self.originals["items"][2]["delivered_sources"][0]
        record["content"] = "前缀🙂事实"
        record["start"] = len("前缀".encode("utf-8"))
        record["end"] = len(record["content"].encode("utf-8"))
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / "pack"
            prepare_handoff(
                self.originals,
                source_file_sha256=self.file_sha,
                output=out,
                salt=b"\x02" * 32,
            )
            views = lines(out / "review-questions.jsonl")
            self.assertTrue(
                any(e["excerpt"] == "🙂事实" for v in views for e in v["evidence"])
            )

    def test_question_byte_drift_across_arms_is_not_blinded_away(self):
        bad = copy.deepcopy(self.originals)
        bad["items"][0]["question_record"]["content"] = "Different question"
        with self.assertRaisesRegex(ValueError, "question changed"):
            prepare_cases(bad)

    def test_unknown_citation_to_missing_source_rejected(self):
        bad = copy.deepcopy(self.originals)
        bad["items"][2]["raw_answer"] = "invented [E99]"
        with self.assertRaisesRegex(ValueError, "unknown Reader citation"):
            prepare_cases(bad)

    def test_no_evidence_can_never_include_hidden_sources(self):
        bad = copy.deepcopy(self.originals)
        bad["items"][0]["delivered_sources"] = copy.deepcopy(
            bad["items"][2]["delivered_sources"][:1]
        )
        with self.assertRaisesRegex(ValueError, "no-evidence condition not empty"):
            prepare_cases(bad)

    def test_removed_condition_cannot_keep_all_sufficient_sources(self):
        bad = copy.deepcopy(self.originals)
        bad["items"][3]["delivered_sources"] = copy.deepcopy(
            bad["items"][2]["delivered_sources"]
        )
        with self.assertRaisesRegex(ValueError, "not differentiated"):
            prepare_cases(bad)

    def test_removed_condition_cannot_replace_a_missing_source(self):
        # This formerly passed the weak "not full.issubset(removed)" test:
        # a necessary fact was removed but a NEW fact was smuggled in.
        bad = copy.deepcopy(self.originals)
        removed = next(
            r
            for r in bad["items"]
            if r["item_id"] == "q1" and r["condition"] == "critical_premise_removed"
        )
        injected = copy.deepcopy(removed["delivered_sources"][0])
        injected["identity"] = "q1-independent-replacement"
        injected["root"] = "root-q1-independent-replacement"
        injected["content"] = "Unregistered replacement premise."
        injected["start"] = 0
        injected["end"] = len(injected["content"].encode("utf-8"))
        removed["delivered_sources"].append(injected)
        with self.assertRaisesRegex(ValueError, "not differentiated"):
            prepare_cases(bad)

    def test_unaligned_utf8_and_future_source_fail_before_writing(self):
        for future in (False, True):
            bad = copy.deepcopy(self.originals)
            row = bad["items"][2]["delivered_sources"][0]
            if future:
                row["observed_at"] = "2030-01-01T00:00:00+00:00"
            else:
                row["content"] = "🙂data"
                row["start"] = 1
                row["end"] = len(row["content"].encode("utf-8"))
            with self.subTest(future=future), tempfile.TemporaryDirectory() as root:
                out = Path(root) / "not-written"
                with self.assertRaises(ValueError):
                    prepare_handoff(bad, source_file_sha256=self.file_sha, output=out)
                self.assertFalse(out.exists())

    def test_wrong_pinned_file_sha_rejected_before_packet_creation(self):
        with tempfile.TemporaryDirectory() as root:
            src = Path(root) / "source.json"
            raw = json.dumps(self.originals, ensure_ascii=False).encode("utf-8")
            src.write_bytes(raw)
            original_sha = hashlib.sha256(raw).hexdigest()
            loaded = load_strict_json_file(
                src, expected_file_sha256=original_sha, require_pin=True
            )
            self.assertEqual(loaded, self.originals)
            with self.assertRaisesRegex(ValueError, "raw-file SHA256 mismatch"):
                load_strict_json_file(
                    src, expected_file_sha256="0" * 64, require_pin=True
                )
            with self.assertRaisesRegex(ValueError, "original FILE SHA256"):
                prepare_handoff(
                    loaded,
                    source_file_sha256="wrong",
                    output=Path(root) / "not-created",
                )

    def test_no_output_overwrite_or_model_approval(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / "pack"
            prepare_handoff(
                self.originals,
                source_file_sha256=self.file_sha,
                output=out,
                salt=b"\x03" * 32,
            )
            original = (out / "review-questions.jsonl").read_bytes()
            with self.assertRaises(FileExistsError):
                prepare_handoff(
                    self.originals,
                    source_file_sha256=self.file_sha,
                    output=out,
                    salt=b"\x03" * 32,
                )
            self.assertEqual((out / "review-questions.jsonl").read_bytes(), original)
            self.assertFalse(
                any(
                    "signature_hex" in x
                    for x in (out / "handoff-receipt.json").read_text().splitlines()
                )
            )

    def test_handoff_rejects_symlinked_output_parent_before_writing(self):
        with tempfile.TemporaryDirectory() as root:
            original_parent = Path(root) / "real-parent"
            original_parent.mkdir()
            alias_parent = Path(root) / "linked-parent"
            alias_parent.symlink_to(original_parent, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink in private handoff"):
                prepare_handoff(
                    self.originals,
                    source_file_sha256=self.file_sha,
                    output=alias_parent / "handoff",
                    salt=b"\x05" * 32,
                )
            self.assertFalse((original_parent / "handoff").exists())

    def test_output_dir_swapped_after_creation_cannot_redirect_private_sources(self):
        # The path is swapped AFTER mkdir and FD open but BEFORE first write.
        # An FD-relative writer must continue writing to the original inode.
        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / "review-pack"
            relocated = Path(root) / "original-private-pack"
            decoy = Path(root) / "untrusted"
            decoy.mkdir()
            real_open, swapped = os.open, []

            def swap_path(name, flags, *args, **kwargs):
                if (
                    name == "review-questions.jsonl"
                    and "dir_fd" in kwargs
                    and not swapped
                ):
                    dest.rename(relocated)
                    dest.symlink_to(decoy, target_is_directory=True)
                    swapped.append(True)
                return real_open(name, flags, *args, **kwargs)

            with patch("reader_review_handoff.os.open", side_effect=swap_path):
                result = prepare_handoff(
                    self.originals,
                    source_file_sha256=self.file_sha,
                    output=dest,
                    salt=b"\x09" * 32,
                )
            self.assertEqual((swapped, result["positions"]), ([True], 8))
            self.assertFalse((decoy / "review-questions.jsonl").exists())
            for filename in (
                "review-questions.jsonl",
                "reviewer-blank-form.jsonl",
                "operator-private-map.jsonl",
                "handoff-receipt.json",
            ):
                self.assertTrue((relocated / filename).is_file())
                self.assertEqual((relocated / filename).stat().st_mode & 0o077, 0)

    def test_output_directory_symlink_swap_at_fd_open_fails_closed(self):
        # A symlink installed after mkdir cannot redirect output on open().
        with tempfile.TemporaryDirectory() as root:
            dest = Path(root) / "review-pack"
            relocated = Path(root) / "original-private-pack"
            decoy = Path(root) / "untrusted"
            decoy.mkdir()
            real_open, swapped = os.open, []

            def swap_before_open(name, flags, *args, **kwargs):
                if (
                    name == dest.name
                    and "dir_fd" in kwargs
                    and flags & os.O_DIRECTORY
                    and not swapped
                ):
                    dest.rename(relocated)
                    dest.symlink_to(decoy, target_is_directory=True)
                    swapped.append(True)
                return real_open(name, flags, *args, **kwargs)

            with patch("reader_review_handoff.os.open", side_effect=swap_before_open):
                with self.assertRaisesRegex(ValueError, "symlink"):
                    prepare_handoff(
                        self.originals,
                        source_file_sha256=self.file_sha,
                        output=dest,
                        salt=b"\x09" * 32,
                    )
            self.assertEqual(swapped, [True])
            self.assertFalse(list(decoy.iterdir()))
            self.assertFalse(list(relocated.iterdir()))


if __name__ == "__main__":
    unittest.main()
