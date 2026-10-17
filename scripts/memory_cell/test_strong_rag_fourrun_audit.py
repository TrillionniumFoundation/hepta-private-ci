"""Fail-closed model-free integrity and exact four-original-run regression tests."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

import strong_rag_fourrun_audit as audit


def fake_run():
    def row(arm):
        return {
            "candidate_digest": "pool",
            "selected": ["original-source"],
            "answer": "site_11111111 [E1]",
            "receipt": {
                "reader_profile": "reader-a",
                "input_ids_digest": "a" * 64,
                "delivered_evidence": ["verbatim-source"],
                "input_tokens": 100,
                "generated_ids_digest": "b" * 64,
            },
        }

    stages = {}
    for phase, arms in (
        ("calibration", audit.CAL_ARMS),
        ("evaluation", audit.EVAL_ARMS),
    ):
        rows = {(phase, arm): row(arm) for arm in arms}
        scored = {key: {"strict_task_success": True} for key in rows}
        metrics = {
            arm: dict(correct=1, input_tokens=100, complete_declared_citation_chains=1)
            for arm in arms
        }
        stages[phase] = dict(rows=rows, scored=scored, metrics=metrics)
    return stages


class FourRunAuditTests(unittest.TestCase):
    def test_strict_json_rejects_duplicate_nonfinite_and_unknown_constant(self):
        for payload in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":1e9999}'):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                audit.strict_json(payload)

    def test_path_and_archive_reject_injection(self):
        for bad in ("../escape", "/absolute", "a\\b", "./a", "a/../b", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                audit._canonical(bad)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bad.zip"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("a", "data")
                z.writestr("SHA256SUMS", "0" * 64 + "  a\n")
            with self.assertRaisesRegex(ValueError, "manifest"):
                audit.archive(
                    path, hashlib.sha256(path.read_bytes()).hexdigest(), 1, kind="full"
                )

    def test_unregistered_or_missing_run_cannot_pass(self):
        with self.assertRaises(ValueError):
            audit.compare_four({"A": fake_run()})
        with self.assertRaises(ValueError):
            audit.run({})

    def test_four_matching_sources_are_not_independent(self):
        runs = {k: fake_run() for k in audit.PINS}
        result = audit.compare_four(runs)
        self.assertEqual(result["actual_archived_model_generations"], 448)
        self.assertEqual(
            result["cross_run_unstable_inputs"], dict(calibration=0, evaluation=0)
        )
        self.assertFalse(result["repeated_questions_are_independent"])
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["org_task_accuracy_superiority"])

    def test_changed_prompt_or_evidence_blocks_cross_run_claim(self):
        for key, value in (
            ("input_ids_digest", "z" * 64),
            ("reader_profile", "other"),
            ("delivered_evidence", ["fabricated"]),
            ("input_tokens", 101),
        ):
            runs = {k: fake_run() for k in audit.PINS}
            runs["D"]["evaluation"]["rows"][("evaluation", "organized")]["receipt"][
                key
            ] = value
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(ValueError, "changed frozen original"),
            ):
                audit.compare_four(runs)

    def test_output_variation_is_recorded_not_repaired(self):
        runs = {k: fake_run() for k in audit.PINS}
        key = ("evaluation", "hybrid_k6")
        runs["D"]["evaluation"]["rows"][key]["answer"] = "site_99999999 [E1]"
        runs["D"]["evaluation"]["scored"][key]["strict_task_success"] = False
        result = audit.compare_four(runs)
        self.assertEqual(result["cross_run_unstable_inputs"]["evaluation"], 1)
        self.assertEqual(len(result["across_run_task_outcome_flips"]), 1)
        self.assertFalse(result["production_accepted"])

    def test_real_four_sealed_archives_if_supplied(self):
        root = os.environ.get("HEPTA_MEMORY_FOURRUN_ARCHIVES")
        if not root:
            self.skipTest("real pinned ZIPs supplied only in separate read-only replay")
        paths = {
            k: (Path(root) / f"{k}-full.zip", Path(root) / f"{k}-replay.zip")
            for k in audit.PINS
        }
        result = audit.run(paths)
        self.assertEqual(
            result["cross_run_unstable_inputs"], {"calibration": 4, "evaluation": 9}
        )
        self.assertEqual(len(result["across_run_task_outcome_flips"]), 2)
        self.assertTrue(
            all(
                x["organizer_minus_entity_time_tasks"] == 0
                for x in result["causal_differences"].values()
            )
        )
        self.assertTrue(
            all(
                x["organizer_minus_entity_time_citation_chains"] == 0
                for x in result["causal_differences"].values()
            )
        )
        self.assertFalse(result["production_accepted"])


if __name__ == "__main__":
    unittest.main()
