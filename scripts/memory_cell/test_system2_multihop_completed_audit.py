"""Exact real-model evidence and tamper-resistant read-only audit tests."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from system2_multihop_completed_audit import (
    ARCHIVE_SHA,
    READER_IDENTITY,
    behavior,
    read_completed,
    file_sha,
)


ARCHIVE = Path(
    os.environ.get(
        "HEPTA_SYSTEM2_COMPLETED_MULTIHOP_ARCHIVE",
        str(Path(__file__).parents[0] / "_completed100_archive.zip"),
    )
)


def repack(original, output, edits):
    with ZipFile(original) as z:
        src = {n: z.read(n) for n in z.namelist() if n != "SHA256SUMS"}
    src.update(edits)
    sums = "".join(
        f"{hashlib.sha256(data).hexdigest()}  ./{name}\n"
        for name, data in sorted(src.items())
    ).encode()
    with ZipFile(output, "w", ZIP_DEFLATED) as z:
        for name, data in src.items():
            z.writestr(name, data)
        z.writestr("SHA256SUMS", sums)
    return hashlib.sha256(output.read_bytes()).hexdigest()


class CompletedReaderAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ARCHIVE.is_file():
            raise unittest.SkipTest(
                "source-slice fixture not mounted; hosted CI supplies pinned original"
            )
        cls.valid = read_completed(ARCHIVE)

    def test_verified_completed_100_and_model_identity(self):
        a = self.valid
        self.assertEqual(
            (len(a["cases"]), len(a["rows"]), a["manifest_entries"]), (20, 100, 22)
        )
        self.assertEqual(a["archive_sha256"], ARCHIVE_SHA)
        self.assertEqual(
            {r["reader"]["reader_identity"] for r in a["rows"]}, {READER_IDENTITY}
        )

    def test_no_evidence_hallucinations_and_complete_but_unusable_answers(self):
        stat = {r["arm"]: r for r in behavior(self.valid)["by_arm"]}
        self.assertEqual(stat["no_evidence"]["exact_refusals"], 0)
        self.assertEqual(stat["joined_top3"]["complete_source_sets"], 20)
        self.assertEqual(stat["joined_top3"]["correct_bounded_citations"], 0)
        self.assertEqual(stat["joined_top3"]["mentions_target_literal"], 7)
        self.assertEqual(stat["premise_removed"]["mentions_target_literal"], 11)
        self.assertEqual(stat["premise_removed"]["exact_refusals"], 0)
        self.assertEqual(stat["joined_top3"]["hit_generation_ceiling"], 11)

    def test_outer_digest_is_mandatory(self):
        with self.assertRaisesRegex(ValueError, "archive digest"):
            read_completed(ARCHIVE, expected_sha="0" * 64)

    def test_answer_mutation_rejected_even_with_rebuilt_manifest(self):
        with tempfile.TemporaryDirectory() as tmp, ZipFile(ARCHIVE) as z:
            lines = z.read("native/raw-answers.jsonl").splitlines()
            row = json.loads(lines[0])
            row["answer"] += " contamination"
            lines[0] = json.dumps(row).encode()
            changed = b"\n".join(lines) + b"\n"
            out = Path(tmp) / "mutated.zip"
            sha = repack(ARCHIVE, out, {"native/raw-answers.jsonl": changed})
            with self.assertRaisesRegex(ValueError, "seal"):
                read_completed(out, expected_sha=sha)

    def test_resealed_provenance_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, ZipFile(ARCHIVE) as z:
            lines = z.read("native/raw-answers.jsonl").splitlines()
            row = json.loads(lines[0])
            row["reader"]["delivered_evidence"][0]["excerpt"] = "forged"
            lines[0] = json.dumps(row).encode()
            raw = b"\n".join(lines) + b"\n"
            seal = dict(sha256=file_sha(raw), rows=100, scoring_started=False)
            out = Path(tmp) / "mutated.zip"
            sha = repack(
                ARCHIVE,
                out,
                {
                    "native/raw-answers.jsonl": raw,
                    "native/raw-seal.json": json.dumps(seal).encode(),
                },
            )
            with self.assertRaisesRegex(ValueError, "detached"):
                read_completed(out, expected_sha=sha)

    def test_resealed_selected_source_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, ZipFile(ARCHIVE) as z:
            lines = z.read("native/raw-answers.jsonl").splitlines()
            row = json.loads(lines[0])
            row["selected"][0] = "doc:forged"
            lines[0] = json.dumps(row).encode()
            raw = b"\n".join(lines) + b"\n"
            out = Path(tmp) / "mutated.zip"
            sha = repack(
                ARCHIVE,
                out,
                {
                    "native/raw-answers.jsonl": raw,
                    "native/raw-seal.json": json.dumps(
                        dict(sha256=file_sha(raw), rows=100, scoring_started=False)
                    ).encode(),
                },
            )
            with self.assertRaisesRegex(ValueError, "selector"):
                read_completed(out, expected_sha=sha)


if __name__ == "__main__":
    unittest.main()
