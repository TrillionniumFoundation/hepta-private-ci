"""Hermetic tests for a BLANK independent-review handoff, not verdicts."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

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

    def test_exact_complete_private_handoff_with_blank_human_forms(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / "handoff"
            receipt = prepare_handoff(self.originals, source_file_sha256=self.file_sha,
                                      output=out, salt=b"\x01" * 32)
            self.assertEqual(receipt, dict(positions=8, independent_reviews=0,
                                           neural_calls=0, production_accepted=False))
            self.assertEqual(out.stat().st_mode & 0o077, 0)
            cases = lines(out / "review-questions.jsonl")
            forms = lines(out / "reviewer-blank-form.jsonl")
            mappings = lines(out / "operator-private-map.jsonl")
            self.assertEqual(len(cases), len(forms))
            self.assertEqual(len(forms), len(mappings))
            self.assertEqual(len({v["ticket"] for v in cases}), 8)
            self.assertEqual({v["ticket"] for v in cases},
                             {v["ticket"] for v in mappings})
            self.assertEqual({v["ticket"] for v in cases},
                             {v["ticket"] for v in forms})
            self.assertTrue(all(v["grounded_and_cited"] is None and
                                v["exact_refusal"] is None and
                                v["cited_semantically_supported"] is None
                                for v in forms))
            self.assertTrue(all("condition" not in view and
                                "raw_reader_answer" in view for view in cases))
            self.assertEqual({row["condition"] for row in mappings},
                             {"no_evidence", "ordinary_retrieval",
                              "human_sufficient", "critical_premise_removed"})
            for path in out.iterdir():
                self.assertEqual(path.stat().st_mode & 0o077, 0)
            info = json.loads((out / "handoff-receipt.json").read_text())
            self.assertFalse(info["production_accepted"])
            self.assertFalse(info["independent_human_adjudication_obtained"])
            self.assertEqual(info["reviewer_signatures"], 0)
            self.assertEqual(info["reviewer_verdicts_filled"], 0)
            for name, digest in info["written_file_sha256"].items():
                self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(),
                                 digest)

    def test_real_unicode_excerpt_is_valid_and_preserved_without_gold(self):
        record = self.originals["items"][2]["delivered_sources"][0]
        record["content"] = "前缀🙂事实"
        record["start"] = len("前缀".encode("utf-8"))
        record["end"] = len(record["content"].encode("utf-8"))
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / "pack"
            prepare_handoff(self.originals, source_file_sha256=self.file_sha,
                            output=out, salt=b"\x02" * 32)
            views = lines(out / "review-questions.jsonl")
            self.assertTrue(any(e["excerpt"] == "🙂事实" for v in views
                                for e in v["evidence"]))

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
            bad["items"][2]["delivered_sources"][:1])
        with self.assertRaisesRegex(ValueError, "no-evidence condition not empty"):
            prepare_cases(bad)

    def test_removed_condition_cannot_keep_all_sufficient_sources(self):
        bad = copy.deepcopy(self.originals)
        bad["items"][3]["delivered_sources"] = copy.deepcopy(
            bad["items"][2]["delivered_sources"])
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
                    prepare_handoff(bad, source_file_sha256=self.file_sha,
                                    output=out)
                self.assertFalse(out.exists())

    def test_wrong_pinned_file_sha_rejected_before_packet_creation(self):
        with tempfile.TemporaryDirectory() as root:
            src = Path(root) / "source.json"
            raw = json.dumps(self.originals, ensure_ascii=False).encode("utf-8")
            src.write_bytes(raw)
            original_sha = hashlib.sha256(raw).hexdigest()
            loaded = load_strict_json_file(src, expected_file_sha256=original_sha,
                                           require_pin=True)
            self.assertEqual(loaded, self.originals)
            with self.assertRaisesRegex(ValueError, "raw-file SHA256 mismatch"):
                load_strict_json_file(src, expected_file_sha256="0"*64,
                                      require_pin=True)
            with self.assertRaisesRegex(ValueError, "original FILE SHA256"):
                prepare_handoff(loaded, source_file_sha256="wrong",
                                output=Path(root) / "not-created")

    def test_no_output_overwrite_or_model_approval(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / "pack"
            prepare_handoff(self.originals, source_file_sha256=self.file_sha,
                            output=out, salt=b"\x03" * 32)
            original=(out / "review-questions.jsonl").read_bytes()
            with self.assertRaises(FileExistsError):
                prepare_handoff(self.originals, source_file_sha256=self.file_sha,
                                output=out, salt=b"\x03" * 32)
            self.assertEqual((out / "review-questions.jsonl").read_bytes(), original)
            self.assertFalse(any("signature_hex" in x for x in
                                 (out / "handoff-receipt.json").read_text().splitlines()))


if __name__ == "__main__":
    unittest.main()
