"""Model-free exact-census and archive-integrity regression tests."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from historical_component_receipt import (
    ARMS,
    KIND,
    SOURCE_COMMIT,
    archive_records,
    compare,
)


def fake_rows():
    rows = []
    for i in range(8):
        kind = KIND[i // 2]
        qid = f"q{i}"
        for arm in ARMS:
            selected = ["required"]
            if arm == "hybrid":
                selected = ["required", "distractor", "another"]
            elif arm == "empty":
                selected = []
            elif arm == "entity_time" and kind == "correction":
                selected = ["obsolete", "required"]
            elif arm == "without_prerequisite":
                selected = []
            row = dict(
                question_id=qid,
                arm=arm,
                kind=kind,
                status="succeeded",
                selected=selected,
                answer="site_correct" if arm != "hybrid" else "site_wrong",
                candidate_digest="fixed-pool-" + qid,
                receipt=dict(
                    reader_identity="reader",
                    reader_profile="fixed-decoder",
                    token_limit=2048,
                ),
                strict_task_success=arm
                not in ("hybrid", "empty", "without_prerequisite"),
                required_sources_covered=arm not in ("empty", "without_prerequisite"),
            )
            rows.append(row)
    return rows


def archive(path, *, tamper=None, unsafe=False):
    rows = fake_rows()
    scored = deepcopy(rows)
    if tamper is not None:
        scored[0]["answer"] = tamper
    files = {
        "tested-commit.txt": (SOURCE_COMMIT + "\n").encode(),
        "run/raw-answers.jsonl": (
            "\n".join(json.dumps(r) for r in rows) + "\n"
        ).encode(),
        "run/scored-answers.json": json.dumps(scored).encode(),
    }
    if unsafe:
        files["../outside"] = b"poison"
    manifest = "".join(
        f"{hashlib.sha256(raw).hexdigest()}  {name}\n"
        for name, raw in sorted(files.items())
    )
    files["SHA256SUMS"] = manifest.encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, raw in files.items():
            z.writestr(name, raw)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HistoricalComponentTests(unittest.TestCase):
    def test_filtering_is_distinct_from_full_graph_closure(self):
        report = compare(fake_rows())
        self.assertEqual(report["actual_model_attempts"], 48)
        c = report["contrasts"]
        self.assertEqual(c["entity_time_minus_hybrid"]["wins"], 8)
        self.assertEqual(c["organized_minus_entity_time"]["wins"], 0)
        self.assertEqual(c["organized_minus_entity_time"]["selection_changed"], 2)
        self.assertEqual(
            c["program_support_minus_organized"]["identical_ordered_selection"], 8
        )
        self.assertFalse(report["significance_established"])

    def test_missing_duplicate_inconsistent_and_incorrect_status_are_rejected(self):
        rows = fake_rows()
        for changed in (rows[:-1], rows + rows[:1]):
            with self.assertRaises(ValueError):
                compare(changed)
        for field, value in (
            ("strict_task_success", 1),
            ("status", "unavailable"),
            ("candidate_digest", "different"),
            ("selected", ["same", "same"]),
        ):
            changed = deepcopy(rows)
            changed[0][field] = value
            with self.assertRaises(ValueError):
                compare(changed)
        changed = deepcopy(rows)
        changed[0]["receipt"]["reader_identity"] = "another_reader"
        with self.assertRaises(ValueError):
            compare(changed)

    def test_archive_sha_and_original_answer_are_both_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.zip"
            pin = archive(path)
            records, manifest = archive_records(path, pin)
            self.assertEqual(len(records), 48)
            self.assertEqual(manifest["archived_files"], 3)
            with self.assertRaises(ValueError):
                archive_records(path, "0" * 64)
            bad = archive(path, tamper="postprocessed")
            with self.assertRaises(ValueError):
                archive_records(path, bad)

    def test_path_traversal_rejected_even_with_valid_hash_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.zip"
            pin = archive(path, unsafe=True)
            with self.assertRaises(ValueError):
                archive_records(path, pin)


if __name__ == "__main__":
    unittest.main()
