"""Model-free CSPRNG label sealer regressions, without human review claims."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from memory_trial_preexposure_freeze import dump_exclusive, freeze
from memory_trial_independent_score import COMMITMENT_SCHEME, commit_identifier, score
from test_memory_trial_admission import fixture


NOW = datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)


def inputs():
    plan, originals, ignored = fixture()
    for c in plan["cases"]:
        c["answer_sha256"] = None
    answers = [{"id": c["id"], "expected": "site_aabb" + str(i)}
               for i, c in enumerate(plan["cases"])]
    for original, old in zip(originals, ignored, strict=True):
        if original["id"] == "case-3":
            for name in ("program_exit_code", "program_test_count", "program_tests_passed"):
                original.setdefault(name, old[name])
        original["cost"] = {k: 0.0 for k in
                            ("extraction", "indexing", "training", "query",
                             "maintenance", "revocation", "raw_storage")}
        original["diagnostic_count"] = 1
        original["recovery_success"] = False
    counter = iter(range(1, len(answers) + 20))
    salt = lambda n: next(counter).to_bytes(n, "big").hex()
    return plan, originals, answers, salt


class FreezeTests(unittest.TestCase):
    def test_seal_then_score_without_exposing_gold_in_plan(self):
        template, originals, reviews, random_bytes = inputs()
        public, protected = freeze(template, reviews, now=NOW, nonce_factory=random_bytes)
        self.assertEqual(public["answer_commitment_scheme"], COMMITMENT_SCHEME)
        self.assertNotIn(reviews[0]["expected"], json.dumps(public))
        self.assertEqual(public["cases"][0]["answer_sha256"],
                         commit_identifier(protected[0]["expected"], protected[0]["nonce"]))
        self.assertIsNone(template["cases"][0]["answer_sha256"])
        rows, report = score(public, originals, protected)
        self.assertEqual(len(rows), 160)
        self.assertEqual(report["recomputed_strict_successes"], 0)
        self.assertFalse(report["production_qualified"])

    def test_missing_reviews(self):
        p, _, reviews, rng = inputs()
        with self.assertRaisesRegex(ValueError, "incomplete protected"):
            freeze(p, reviews[:-1], now=NOW, nonce_factory=rng)

    def test_reject_expired_task_window(self):
        p, _, reviews, rng = inputs()
        p["cases"][0]["task_revealed_at"] = "2026-10-15T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "already exposed"):
            freeze(p, reviews, now=NOW, nonce_factory=rng)

    def test_refuse_replace_existing_answer_commit(self):
        p, _, reviews, rng = inputs()
        p["cases"][0]["answer_sha256"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "already committed"):
            freeze(p, reviews, now=NOW, nonce_factory=rng)

    def test_reject_duplicate_review(self):
        p, _, reviews, rng = inputs()
        with self.assertRaisesRegex(ValueError, "duplicate or unexpected"):
            freeze(p, reviews + [reviews[0]], now=NOW, nonce_factory=rng)

    def test_reject_duplicate_nonce(self):
        p, _, reviews, _ = inputs()
        with self.assertRaisesRegex(ValueError, "random independent"):
            freeze(p, reviews, now=NOW, nonce_factory=lambda _: "a" * 64)

    def test_reject_gold_with_citation_as_label(self):
        p, _, reviews, rng = inputs()
        reviews[0]["expected"] = "site_1234 [E1]"
        with self.assertRaisesRegex(ValueError, "exact protocol identifier"):
            freeze(p, reviews, now=NOW, nonce_factory=rng)

    def test_exclusive_private_file_and_no_clobber(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "private.json"
            value = dump_exclusive(path, {"protected": True})
            self.assertEqual(len(value), 64)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                dump_exclusive(path, {"protected": False})


if __name__ == "__main__":
    unittest.main()