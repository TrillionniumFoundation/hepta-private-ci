"""Historical real frozen Reader evidence: exact provenance and honest limits."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from system2_native_receipt import verified_archive
from system2_reader_behavior_audit import (
    ARCHIVE,
    ARMS,
    ANSWER_SEAL,
    READER,
    SOURCE,
    lines,
    run,
    summarize,
    validate_reader_input,
)


ARCHIVE_PATH = (
    Path(os.environ["HEPTA_SYSTEM2_NEW_ARCHIVE"])
    if os.environ.get("HEPTA_SYSTEM2_NEW_ARCHIVE")
    else None
)


class FrozenReaderBehaviorAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ARCHIVE_PATH is None:
            raise unittest.SkipTest(
                "Exact archival Reader inputs not staged for this regression job"
            )
        if not ARCHIVE_PATH.is_file():
            raise ValueError("explicit archived Reader fixture unavailable")
        cls.files = verified_archive(ARCHIVE_PATH, ARCHIVE)

    def test_complete_real_neural_receipts_and_splits(self):
        report = summarize(self.files)
        self.assertEqual(report["counted_answers"], 384)
        self.assertEqual(report["totals"]["planned"], 384)
        self.assertEqual(report["totals"]["completed"], 384)
        self.assertEqual(report["reader_identity"], READER)
        self.assertEqual(report["producing_commit"], SOURCE)
        self.assertEqual(report["raw_answer_sha256"], ANSWER_SEAL)
        self.assertEqual([r["arm"] for r in report["per_arm"]], list(ARMS))
        self.assertEqual(report["totals"]["distinct_deterministic_prompts"], 160)
        self.assertFalse(report["citation_semantics_independently_verified"])
        self.assertEqual(report["new_neural_calls"], 0)

    def test_no_evidence_never_means_grounded_answer(self):
        report = summarize(self.files)
        by_arm = {r["arm"]: r for r in report["per_arm"]}
        self.assertEqual(by_arm["no_evidence"]["delivered_zero_evidence"], 48)
        self.assertEqual(by_arm["no_evidence"]["prescribed_strict_refusals"], 0)
        self.assertEqual(by_arm["no_evidence"]["nonrefusal_with_zero_evidence"], 48)
        self.assertEqual(by_arm["ranked3"]["delivered_zero_evidence"], 0)
        self.assertEqual(report["totals"]["zero_evidence_outputs"], 54)
        self.assertEqual(report["totals"]["nonrefusal_zero_evidence_outputs"], 54)

    def test_citation_syntax_rare_and_semantics_unknown(self):
        report = summarize(self.files)
        self.assertEqual(report["totals"]["valid_label_citations"], 4)
        self.assertEqual(report["totals"]["prescribed_refusals"], 0)
        for entry in report["per_arm"]:
            self.assertLessEqual(entry["citation_labels_all_bound"], entry["completed"])
            self.assertEqual(entry["unbound_citation_labels"], 0)
        self.assertFalse(report["human_evidence_sufficiency_verified"])
        self.assertTrue(report["original_annotation_f1_not_readjudged"])

    def test_all_source_bytes_bound_to_original_reader_input(self):
        input_row = lines(self.files["native/reader-inputs.jsonl"])[0]
        key = validate_reader_input(input_row)
        answer = lines(self.files["native/trial/answers.jsonl"])[0]
        rec = answer["receipt"]
        self.assertEqual(
            key[:3], (answer["query_id"], rec["query_digest"], rec["bundle_digest"])
        )
        self.assertEqual(len(key[3]), len(rec["delivered_evidence"]))

    def test_forged_source_span_is_rejected(self):
        row = copy.deepcopy(lines(self.files["native/reader-inputs.jsonl"])[0])
        row["bundle"]["selected"][0]["excerpt"] += " NOT AN ORIGINAL BYTE"
        with self.assertRaises(ValueError):
            validate_reader_input(row)

    def test_spoofed_original_source_is_rejected(self):
        row = copy.deepcopy(lines(self.files["native/reader-inputs.jsonl"])[0])
        row["selected_originals"][0]["content"] = "a forged replacement"
        with self.assertRaises(ValueError):
            validate_reader_input(row)

    def test_mutated_raw_answers_fail_exact_seal(self):
        data = dict(self.files)
        raw = bytearray(data["native/trial/answers.jsonl"])
        raw[35] ^= 1
        data["native/trial/answers.jsonl"] = bytes(raw)
        with self.assertRaises(ValueError):
            summarize(data)

    def test_scoring_cannot_replace_original_answer(self):
        data = dict(self.files)
        rows = lines(data["native/trial/scored.jsonl"])
        rows[0]["answer"] = "A fabricated scored answer."
        data["native/trial/scored.jsonl"] = "".join(
            json.dumps(x) + "\n" for x in rows
        ).encode()
        with self.assertRaises(ValueError):
            summarize(data)

    def test_source_commit_and_reader_inventory_drift_rejected(self):
        for key, value in (
            ("tested-commit.txt", b"0" * 40 + b"\n"),
            ("native/trial/plan.json", None),
        ):
            data = dict(self.files)
            if value is None:
                plan = json.loads(data[key])
                plan["reader_inventory"] = "0" * 64
                data[key] = json.dumps(plan).encode()
            else:
                data[key] = value
            with self.assertRaises(ValueError):
                summarize(data)

    def test_missing_complete_input_and_duplicate_score_rejected(self):
        for key in ("native/reader-inputs.jsonl", "native/trial/scored.jsonl"):
            data = dict(self.files)
            data[key] = b"\n".join(data[key].splitlines()[:-1]) + b"\n"
            with self.assertRaises(ValueError):
                summarize(data)

    def test_original_annotation_is_not_a_new_gold_label(self):
        report = summarize(self.files)
        by_arm = {x["arm"]: x for x in report["per_arm"]}
        self.assertEqual(by_arm["ranked3"]["diagnostic_f1_known"], 37)
        self.assertLess(by_arm["ranked3"]["original_diagnostic_f1_mean"], 0.07)
        self.assertGreater(by_arm["ranked3"]["original_diagnostic_f1_mean"], 0.06)
        self.assertEqual(by_arm["no_evidence"]["diagnostic_f1_known"], 37)

    def test_write_receipt_is_read_only_and_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "summary"
            result = run(ARCHIVE_PATH, out)
            self.assertEqual(result["totals"]["completed"], 384)
            self.assertEqual(
                json.loads((out / "historical-reader-behavior.json").read_text()),
                result,
            )
            self.assertTrue(ARCHIVE_PATH.is_file())


if __name__ == "__main__":
    unittest.main()
