"""Deterministic original-answer-bound pairing; all Reader outputs synthetic."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import os
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

from real_source_rank_paired_gate import (
    compare_original_reader_to_rank,
    pinned_original_journal,
)
from real_source_reader_probe import (
    FROZEN_PLAN_SHA256,
    TIERS,
    canonical,
    plan_from_archives,
    real_source,
)
from test_real_source_reader_probe import fake_journals


class RankPairedOriginalsTests(unittest.TestCase):
    def setUp(self):
        source = os.environ.get("MEMORY_REAL_SOURCE_ZIP")
        reopened = os.environ.get("MEMORY_REOPEN_ZIP")
        if not source or not reopened:
            self.skipTest("exact original Git ZIPs required for original-bound pairing")
        self.sources = real_source(Path(source), Path(reopened))
        self.plan = plan_from_archives(Path(source), Path(reopened))
        # This fixture generates no pretrained output; it is only an integrity test.
        self.originals = fake_journals(self.plan)

    def test_matrix_and_paired_null_explicit_no_claims(self):
        report = compare_original_reader_to_rank(
            self.plan, self.sources, self.originals
        )
        self.assertEqual(report["planned_original_reader_attempts"], 72)
        self.assertEqual(report["successful_reader_model_calls_after_validation"], 72)
        for tier in TIERS:
            for condition in ("hybrid_k4", "removed_declaration"):
                item = report["comparisons"][tier][condition]
                # Synthetic fixture deliberately produces correct marker for all 9.
                self.assertEqual(item["reader_wins"], 2)
                self.assertEqual(item["reader_losses"], 0)
                self.assertEqual(item["ties"], 7)
                self.assertEqual(item["rank_only_strict_correct"], 7)
                self.assertEqual(item["reader_strict_correct"], 9)
                self.assertEqual(item["reader_original_target_cited"], 7)
                self.assertEqual(len(item["case_outcomes"]), 9)
                self.assertIsNone(item["independent_statistical_interval"])
            lesion = report["comparisons"][tier]["hybrid_vs_full_symbol_lesion"]
            self.assertEqual(lesion["reader_wins"], 0)
            self.assertEqual(lesion["ties"], 9)
        self.assertFalse(report["parameter_learning_gain_established"])
        self.assertFalse(report["production_qualified"])
        self.assertFalse(report["human_semantic_evidence_review_performed"])

    def test_no_model_answer_text_is_exported(self):
        report = compare_original_reader_to_rank(
            self.plan, self.sources, self.originals
        )
        body = canonical(report).decode()
        self.assertNotIn("F01 [E1]", body)
        self.assertNotIn('"answer":', body)
        self.assertIn("original_answer_sha256", body)

    def test_missing_original_inference_is_refused(self):
        self.originals[TIERS[1]].pop()
        with self.assertRaisesRegex(ValueError, "missing original model answers"):
            compare_original_reader_to_rank(self.plan, self.sources, self.originals)

    def test_forged_delivered_source_receipt_is_refused(self):
        self.originals[TIERS[0]][0]["receipt"]["bundle_digest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "delivered evidence/prompt binding"):
            compare_original_reader_to_rank(self.plan, self.sources, self.originals)

    def test_wrong_plan_version_is_refused(self):
        other = deepcopy(self.plan)
        other["schema"] = "hepta.memory.real-git-reader-function-probe.v2"
        with self.assertRaisesRegex(ValueError, "only exact externally frozen v3"):
            compare_original_reader_to_rank(other, self.sources, self.originals)

    def test_changed_original_answer_does_not_inflate_ties(self):
        for row in self.originals[TIERS[0]]:
            if row["condition"] == "hybrid_k4":
                row["answer"] = "F99 [E9]"
                break
        report = compare_original_reader_to_rank(
            self.plan, self.sources, self.originals
        )
        item = report["comparisons"][TIERS[0]]["hybrid_k4"]
        self.assertEqual(item["reader_strict_correct"], 8)
        self.assertEqual(item["reader_wins"] + item["reader_losses"] + item["ties"], 9)
        self.assertEqual(item["reader_original_target_cited"], 6)

    def test_journal_bytes_require_external_hash_and_unique_keys(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "original.jsonl"
            raw = b"".join(canonical(x) + b"\n" for x in self.originals[TIERS[0]])
            path.write_bytes(raw)
            pin = hashlib.sha256(raw).hexdigest()
            result = pinned_original_journal(path, pin)
            self.assertEqual(len(result), 36)
            with self.assertRaisesRegex(ValueError, "differ from external journal pin"):
                pinned_original_journal(path, "0" * 64)
            path.write_bytes(raw.replace(b'"tier":', b'"tier":"leak","tier":', 1))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                pinned_original_journal(
                    path, hashlib.sha256(path.read_bytes()).hexdigest()
                )

    def test_full_cli_requires_external_pins_and_never_overwrites(self):
        src = os.environ.get("MEMORY_REAL_SOURCE_ZIP")
        reopen = os.environ.get("MEMORY_REOPEN_ZIP")
        if not src or not reopen:
            self.skipTest("original Git archives required for CLI smoke")
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            argv = [
                sys.executable,
                str(Path(__file__).with_name("real_source_rank_paired_gate.py")),
                "--source-zip", src,
                "--reopen-zip", reopen,
            ]
            for tier in TIERS:
                original = base / (tier + ".jsonl")
                data = b"".join(
                    canonical(r) + b"\n" for r in self.originals[tier]
                )
                original.write_bytes(data)
                argv.extend([
                    "--" + tier, str(original),
                    "--" + tier + "-sha256", hashlib.sha256(data).hexdigest(),
                ])
            target = base / "unpromoted-postrun.json"
            argv.extend(["--output", str(target)])
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=45
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(target.read_bytes())
            self.assertEqual(
                report["successful_reader_model_calls_after_validation"], 72
            )
            self.assertFalse(report["production_qualified"])
            rerun = subprocess.run(
                argv, capture_output=True, text=True, timeout=45
            )
            self.assertNotEqual(rerun.returncode, 0, "must not overwrite audit")

    def test_original_git_archives_if_available(self):
        source = os.environ.get("MEMORY_REAL_SOURCE_ZIP")
        reopened = os.environ.get("MEMORY_REOPEN_ZIP")
        if not source or not reopened:
            self.skipTest("original six-project ZIPs not locally available")
        source, reopened = Path(source), Path(reopened)
        plan = plan_from_archives(source, reopened)
        self.assertEqual(
            hashlib.sha256(canonical(plan) + b"\n").hexdigest(),
            FROZEN_PLAN_SHA256,
        )
        archives = real_source(source, reopened)
        generated = fake_journals(plan)
        report = compare_original_reader_to_rank(plan, archives, generated)
        self.assertEqual(report["rank_only_strict_correct"], 7)
        self.assertEqual(report["planned_original_reader_attempts"], 72)
        self.assertFalse(report["production_qualified"])


if __name__ == "__main__":
    unittest.main()