"""Pure read-only controls; no model, optimizer, inferred labels or deployment."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from real_source_rank_null import rank_only_audit
from real_source_reader_probe import (
    EVALUATION,
    FROZEN_PLAN_SHA256,
    build_plan,
    canonical,
    digest,
    plan_from_archives,
    real_source,
)
from test_real_source_reader_probe import pretend_corpus


class RankOnlyNullTests(unittest.TestCase):
    def setUp(self):
        self.files, self.blobs = pretend_corpus()
        self.plan = build_plan(self.files, self.blobs)

    def test_deterministic_rank_null_is_not_a_model_run(self):
        report = rank_only_audit(self.plan, (self.files, self.blobs))
        self.assertEqual(report["authored_cases"], 9)
        self.assertEqual(report["observed_real_model_calls"], 0)
        self.assertEqual(report["repository_name_independence_proxies"], 3)
        self.assertEqual(
            {x["repository_proxy"] for x in report["cases"]}, set(EVALUATION)
        )
        self.assertTrue(report["rank_alone_is_a_shortcut_for_this_mechanical_task"])
        self.assertFalse(report["production_qualified"])
        self.assertFalse(report["parameter_memory_gain_established"])
        for r in report["cases"]:
            self.assertTrue(r["raw_rank_only_answer"].endswith(" [E1]"))
            self.assertEqual(
                r["strict_correct"], r["marker_citation_is_original_and_complete"]
            )

    def test_corrupted_source_code_is_not_accepted(self):
        corrupted = deepcopy(self.blobs)
        item = next(iter(corrupted))
        corrupted[item] = b"def unrelated_function():\n    return None\n"
        with self.assertRaisesRegex(ValueError, "source identity"):
            rank_only_audit(self.plan, (self.files, corrupted))

    def test_precomputed_plan_tampering_is_not_accepted(self):
        plan = deepcopy(self.plan)
        plan["cases"][0]["conditions"]["hybrid_k4"].reverse()
        with self.assertRaisesRegex(ValueError, "source identity"):
            rank_only_audit(plan, (self.files, self.blobs))

    def test_version_mix_rejected(self):
        plan = deepcopy(self.plan)
        plan["replaced_v2_plan_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source identity|retired"):
            rank_only_audit(plan, (self.files, self.blobs))

    def test_negative_source_must_remove_symbols(self):
        plan = deepcopy(self.plan)
        case = plan["cases"][0]
        case["conditions"]["removed_declaration"] = deepcopy(
            case["conditions"]["hybrid_k4"]
        )
        with self.assertRaisesRegex(ValueError, "source identity|lesioned"):
            rank_only_audit(plan, (self.files, self.blobs))

    def test_real_immutable_archives_if_available(self):
        src, reopen = (
            os.environ.get("MEMORY_REAL_SOURCE_ZIP"),
            os.environ.get("MEMORY_REOPEN_ZIP"),
        )
        if not src or not reopen:
            self.skipTest(
                "historical original Git ZIPs not present in test environment"
            )
        src, reopen = Path(src), Path(reopen)
        plan = plan_from_archives(src, reopen)
        self.assertEqual(digest(canonical(plan) + b"\n"), FROZEN_PLAN_SHA256)
        report = rank_only_audit(plan, real_source(src, reopen))
        self.assertEqual(report["fixed_rank_one_strict_correct"], 7)
        self.assertEqual(report["fixed_rank_one_full_target_citation"], 7)
        self.assertEqual(
            report["family_counts"],
            {
                "denoland/deno": dict(tasks=3, rank_one_correct=3),
                "python/cpython": dict(tasks=3, rank_one_correct=2),
                "scikit-learn/scikit-learn": dict(tasks=3, rank_one_correct=2),
            },
        )
        with tempfile.TemporaryDirectory() as td:
            result = Path(td) / "rank-only-audit.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("real_source_rank_null.py")),
                    "--source-zip",
                    str(src),
                    "--reopen-zip",
                    str(reopen),
                    "--output",
                    str(result),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(result.read_bytes(), canonical(report) + b"\n")
            rerun = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("real_source_rank_null.py")),
                    "--source-zip",
                    str(src),
                    "--reopen-zip",
                    str(reopen),
                    "--output",
                    str(result),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(
                rerun.returncode, 0, "audit must not overwrite original"
            )

if __name__ == "__main__":
    unittest.main()
