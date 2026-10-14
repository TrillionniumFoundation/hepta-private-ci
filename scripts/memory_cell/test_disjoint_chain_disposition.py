"""Negative controls for source-pinned disposition; no synthetic model claims."""

from copy import deepcopy
import io
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile

from disjoint_chain_disposition import checked_zip, classify, digest, strict_json


def pack(files):
    blobs = dict(files)
    blobs["SHA256SUMS"] = "".join(
        f"{digest(data)}  {name}\n" for name, data in sorted(files.items())
    ).encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as sink:
        for name, data in blobs.items():
            sink.writestr(name, data)
    return out.getvalue()


def case():
    row = {
        "question_id": "q1",
        "arm": "organized",
        "kind": "composition",
        "selected": ["E1_original", "E2_original"],
        "status": "succeeded",
        "strict_task_success": True,
        "receipt": {
            "delivered_evidence": [
                {"original_id": "E1_original"},
                {"original_id": "E2_original"},
            ]
        },
    }
    citation = {
        "question_id": "q1",
        "arm": "organized",
        "generation_status": "succeeded",
        "strict_task_success": True,
        "cited_source_ids": ["E2_original"],
        "missing_program_declared_support": ["E1_original"],
    }
    return row, citation


class DisjointChainTests(unittest.TestCase):
    def test_real_delivery_gap_is_not_missing_retrieval(self):
        row, citation = case()
        self.assertEqual(
            classify(row, citation),
            {"delivered_but_uncited": ["E1_original"], "not_delivered": []},
        )

    def test_missing_evidence_classification_distinct(self):
        row, citation = case()
        row["selected"] = ["E2_original"]
        row["receipt"]["delivered_evidence"] = [{"original_id": "E2_original"}]
        self.assertEqual(classify(row, citation)["not_delivered"], ["E1_original"])

    def test_citations_do_not_repair_model_answer(self):
        row, citation = case()
        original = deepcopy(row)
        classify(row, citation)
        self.assertEqual(row, original)

    def test_reject_undelivered_citation(self):
        row, citation = case()
        citation["cited_source_ids"].append("invented")
        with self.assertRaisesRegex(ValueError, "source identities"):
            classify(row, citation)

    def test_reject_delivery_mismatch(self):
        row, citation = case()
        row["receipt"]["delivered_evidence"].reverse()
        with self.assertRaisesRegex(ValueError, "frozen selection"):
            classify(row, citation)

    def test_reject_query_or_status_drift(self):
        row, citation = case()
        for name, value in (("question_id", "other"), ("strict_task_success", False)):
            modified = dict(citation, **{name: value})
            with self.assertRaises(ValueError):
                classify(row, modified)

    def test_reject_duplicate_sources(self):
        row, citation = case()
        row["selected"].append("E2_original")
        row["receipt"]["delivered_evidence"].append({"original_id": "E2_original"})
        with self.assertRaisesRegex(ValueError, "source identities"):
            classify(row, citation)

    def test_strict_json_rejects_ambiguous_and_nonfinite(self):
        for data in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                strict_json(data)

    def test_valid_pinned_archive_and_wrong_external_pin(self):
        data = pack({"original.json": b'{"sample":1}\n'})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "a.zip"
            path.write_bytes(data)
            self.assertEqual(
                checked_zip(path, digest(data), count=1)["original.json"],
                b'{"sample":1}\n',
            )
            with self.assertRaisesRegex(ValueError, "external original ZIP hash"):
                checked_zip(path, "f" * 64, count=1)

    def test_edited_inner_member_even_with_matching_outer_pin(self):
        data = pack({"original.json": b"{}"})
        with zipfile.ZipFile(io.BytesIO(data)) as source:
            files = {key: source.read(key) for key in source.namelist()}
        files["original.json"] = b'{"edited":true}'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "edited.zip"
            with zipfile.ZipFile(path, "w") as sink:
                for name, value in files.items():
                    sink.writestr(name, value)
            with self.assertRaisesRegex(ValueError, "member changed"):
                checked_zip(path, digest(path.read_bytes()), count=1)

    def test_traversal_and_duplicate_archive_members_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "archive.zip"
            unsafe = pack({"../escape": b"{}"})
            path.write_bytes(unsafe)
            with self.assertRaisesRegex(ValueError, "unsafe"):
                checked_zip(path, digest(unsafe), count=1)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(path, "w") as z:
                    z.writestr("dup", b"one")
                    z.writestr("dup", b"two")
                    z.writestr("SHA256SUMS", b"")
            with self.assertRaises(ValueError):
                checked_zip(path, digest(path.read_bytes()), count=2)

    def test_missing_or_replaced_manifest_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "archive.zip"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("one.json", b"{}")
                z.writestr("SHA256SUMS", b"")
            with self.assertRaisesRegex(ValueError, "incomplete inner manifest"):
                checked_zip(path, digest(path.read_bytes()), count=1)


if __name__ == "__main__":
    unittest.main()
