"""No models or semantic judgments in these receipt-integrity fixtures."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from reader_reference_receipt import align_records, archive, matched_view


def row(q="q", arm="empty", status="succeeded"):
    result = dict(question_id=q, arm=arm, status=status)
    if status == "succeeded":
        result.update(
            answer="blue",
            receipt=dict(
                reader_identity="model",
                reader_profile="profile",
                input_tokens=10,
                generated_tokens=2,
                seconds=0.1,
            ),
        )
    return result


def scored(raw):
    return [
        r
        | dict(
            f1=0.5 if r["status"] == "succeeded" else None,
            exact_match=False if r["status"] == "succeeded" else None,
            target_unanswerable=False,
        )
        for r in raw
    ]


class ReceiptTests(unittest.TestCase):
    def test_complete_census_keeps_unavailable(self):
        raw = [row(), row(q="missing", status="unavailable")]
        expected = [(r["question_id"], r["arm"]) for r in raw]
        result = align_records(raw, scored(raw), expected)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[("missing", "empty")]["status"], "unavailable")

    def test_missing_duplicate_and_extra_case_reject(self):
        raw = [row()]
        for changed in ([], raw + raw, raw + [row(q="extra")]):
            with self.assertRaises(ValueError):
                align_records(changed, scored(changed), [("q", "empty")])

    def test_posthoc_answer_metadata_or_record_order_reject(self):
        raw = [row(), row(q="other")]
        expected = [(r["question_id"], r["arm"]) for r in raw]
        for field, value in (
            ("answer", "changed"),
            ("arm", "changed"),
            ("status", "failed"),
            ("receipt", {}),
        ):
            changed = scored(deepcopy(raw))
            changed[0][field] = value
            with self.assertRaises(ValueError):
                align_records(raw, changed, expected)
        with self.assertRaises(ValueError):
            align_records(raw, list(reversed(scored(raw))), expected)

    def test_raw_annotations_and_unknown_scoring_fields_reject(self):
        raw = [row() | {"f1": 1.0}]
        with self.assertRaises(ValueError):
            align_records(raw, scored(raw), [("q", "empty")])
        raw = [row()]
        with self.assertRaises(ValueError):
            align_records(raw, [scored(raw)[0] | {"approved": True}], [("q", "empty")])

    def test_external_and_inner_file_pins_are_both_required(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "test.zip"
            value = b"original"
            h = hashlib.sha256(value).hexdigest()
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("data", value)
                z.writestr("SHA256SUMS", h + "  ./data\n")
            pin = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(archive(path, pin)["data"], value)
            with self.assertRaises(ValueError):
                archive(path, "0" * 64)
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("data", b"changed")
                z.writestr("SHA256SUMS", h + "  ./data\n")
            with self.assertRaises(ValueError):
                archive(path, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_missing_inventory_entry_and_traversal_reject(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "test.zip"
            for name in ("extra", "../escape"):
                with zipfile.ZipFile(path, "w") as z:
                    z.writestr(name, "x")
                    z.writestr("SHA256SUMS", "")
                with self.assertRaises(ValueError):
                    archive(path, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_matched_subset_is_chosen_without_scores(self):
        plan = dict(
            cases=[
                dict(
                    question=dict(identity="kept"), conditions=dict(reviewed_minimal={})
                ),
                dict(
                    question=dict(identity="unknown"),
                    conditions=dict(reviewed_minimal=dict(status="unavailable")),
                ),
            ]
        )
        raw = [
            row(q=q, arm=a)
            for q in ("kept", "unknown")
            for a in ("reviewed_minimal", "reviewed_reversed", "retrieved2", "empty")
        ]
        records = {(r["question_id"], r["arm"]): r for r in scored(raw)}
        value = matched_view(plan, {"model": records})
        self.assertEqual(value["auxiliary_case_ids"], ["kept"])
        self.assertEqual(value["original_case_count"], 2)
        self.assertFalse(value["replaces_full_census"])
        for record in records.values():
            record["f1"] = 0
        self.assertEqual(
            matched_view(plan, {"model": records})["auxiliary_case_ids"], ["kept"]
        )
        self.assertIsNone(
            value["per_reader"]["model"]["empty"]["semantic_citation_precision"]
        )


if __name__ == "__main__":
    unittest.main()
