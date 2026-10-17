"""Tests of strict-vs-surface bookkeeping, not model-effect qualification."""

import hashlib
import os
import zipfile
from pathlib import Path
import tempfile
import unittest

from historical_reader_failure_modes import classify, diagnose, sealed_zip

ARCHIVES = Path(os.environ.get("HEPTA_MEMORY_EVENT_ARCHIVES_DIR", "/nonexistent"))


class ReaderFailureDiagnosticsTests(unittest.TestCase):
    @staticmethod
    def row(answer, success=False, parsed=None):
        return dict(
            status="succeeded",
            answer=answer,
            strict_task_success=success,
            parsed_identifier=parsed,
        )

    def test_bracketed_correct_literal_never_promotes_primary_score(self):
        self.assertEqual(
            classify(self.row("[site_2749e2c9]"), "site_2749e2c9"),
            "gold_literal_without_strict_grammar",
        )

    def test_exact_identifier_boundaries_prevent_substring_credit(self):
        self.assertEqual(
            classify(self.row("site_11112"), "site_1111"), "wrong_identifier"
        )

    def test_wrong_answer_and_abstention_are_not_grammar_failures(self):
        self.assertEqual(
            classify(self.row("site_wrong [E1]"), "site_true"), "wrong_identifier"
        )
        self.assertEqual(
            classify(self.row("I do not have enough evidence."), "site_true"),
            "explicit_abstention",
        )

    def test_conflicting_gold_and_wrong_identifiers_not_adjudicated(self):
        self.assertEqual(
            classify(self.row("site_true or site_wrong"), "site_true"),
            "multiple_identifiers_unadjudicated",
        )

    def test_observed_strict_success_is_never_recomputed(self):
        self.assertEqual(
            classify(self.row("site_true", success=True), "site_true"), "strict_correct"
        )
        self.assertEqual(
            classify(dict(status="failed"), "site_true"), "unobserved_generation"
        )

    @unittest.skipUnless(
        os.environ.get("HEPTA_MEMORY_EVENT_ARCHIVES_DIR"),
        "pinned historical ZIP files not staged",
    )
    def test_original_real_model_archives_are_not_relabelled(self):
        r = diagnose(
            ARCHIVES / "event-inputs-20261010.zip",
            ARCHIVES / "event-reader-actual-48.zip",
            ARCHIVES / "event-reader-smol-48.zip",
        )
        q = r["models"]["qwen-3b"]["by_arm"]["hybrid"]
        s = r["models"]["smol-1.7b"]["by_arm"]["hybrid"]
        self.assertEqual(
            q,
            dict(
                gold_literal_without_strict_grammar=1,
                strict_correct=3,
                wrong_identifier=4,
            ),
        )
        self.assertEqual(s, dict(explicit_abstention=7, strict_correct=1))
        self.assertEqual(r["new_model_generations"], 0)
        self.assertFalse(r["production_accepted"])

    def test_outer_and_inner_archive_seals_both_enforced(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "archive.zip"

            def write_archive(payload):
                seal = hashlib.sha256(b"original").hexdigest()
                with zipfile.ZipFile(path, "w") as z:
                    z.writestr("original.txt", payload)
                    z.writestr("SHA256SUMS", f"{seal}  original.txt\n")
                return hashlib.sha256(path.read_bytes()).hexdigest()

            first = write_archive(b"original")
            self.assertEqual(sealed_zip(path, first)["original.txt"], b"original")
            tampered_outer = write_archive(b"modified")
            with self.assertRaisesRegex(ValueError, "wrong immutable archive"):
                sealed_zip(path, first)
            with self.assertRaisesRegex(ValueError, "tampered manifest member"):
                sealed_zip(path, tampered_outer)


if __name__ == "__main__":
    unittest.main()
