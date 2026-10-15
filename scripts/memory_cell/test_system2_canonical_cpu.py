"""Sealed source and true CPU replay mechanics, not new task gains."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from system2_canonical_cpu import BUDGETS, PROFILES, cohorts, run, sealed_index, single
from system2_verified_search import digest

COMMIT = "a" * 40


def example(tmp):
    old = Path(tmp) / "source"
    old.mkdir()
    groups = dict(previous_204=[(1, 2, 3, 4)], next_48_tasks=[(4, 4, 4, 4)])
    rows = []
    for group, ns in groups.items():
        for n in ns:
            for b in BUDGETS:
                for p in PROFILES:
                    result, _, _ = single(n, b, p)
                    rows.append(
                        dict(
                            group=group,
                            numbers=n,
                            query_id=digest(n),
                            budget=b,
                            profile=p,
                            found=result["found"],
                            proof=result["proof"],
                            costs=result["costs"],
                            generation_filter=result["generation_filter"],
                            status="completed",
                        )
                    )
    raw = ("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)).encode()
    (old / "predictions.jsonl").write_bytes(raw)
    (old / "prediction-seal.json").write_text(
        json.dumps(
            dict(
                sha256=hashlib.sha256(raw).hexdigest(),
                rows=len(rows),
                posthoc_analysis_started=False,
            )
        )
    )
    (old / "plan.json").write_text(json.dumps(dict(source_commit=COMMIT)))
    return old, groups, rows


class CpuAuditTests(unittest.TestCase):
    def test_fixed_main_cohorts_have_252_distinct_tasks(self):
        groups = cohorts()
        self.assertEqual(list(map(len, groups.values())), [204, 48])
        self.assertFalse(set(groups["previous_204"]) & set(groups["next_48_tasks"]))

    def test_full_fixture_runner_and_no_source_mutation(self):
        with tempfile.TemporaryDirectory() as t:
            source, groups, _ = example(t)
            before = (source / "predictions.jsonl").read_bytes()
            with (
                patch("system2_canonical_cpu.cohorts", return_value=groups),
                patch("system2_canonical_cpu.REPEATS", 2),
            ):
                d = run(source, Path(t) / "output", source_commit=COMMIT)
            self.assertEqual((d["recorded"], d["planned"], d["failures"]), (16, 16, 0))
            self.assertEqual((source / "predictions.jsonl").read_bytes(), before)
            self.assertTrue(all(not row["losses"] for row in d["paired_proof_changes"]))
            self.assertEqual(len(d["summary"]), 4)

    def test_source_tampering_and_missing_rows_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            source, groups, rows = example(t)
            with self.assertRaises(ValueError):
                sealed_index(source, groups, "b" * 40)
            (source / "predictions.jsonl").write_text("{}\n")
            with self.assertRaises(ValueError):
                sealed_index(source, groups, COMMIT)
            raw = ("".join(json.dumps(r) + "\n" for r in rows[:-1])).encode()
            (source / "predictions.jsonl").write_bytes(raw)
            (source / "prediction-seal.json").write_text(
                json.dumps(
                    dict(
                        sha256=hashlib.sha256(raw).hexdigest(),
                        rows=len(rows) - 1,
                        posthoc_analysis_started=False,
                    )
                )
            )
            with self.assertRaises(ValueError):
                sealed_index(source, groups, COMMIT)

    def test_proof_and_question_identity_are_validated(self):
        with tempfile.TemporaryDirectory() as t:
            source, groups, rows = example(t)
            rows[0]["numbers"] = [1, 1, 1, 1]
            raw = ("".join(json.dumps(r) + "\n" for r in rows)).encode()
            (source / "predictions.jsonl").write_bytes(raw)
            (source / "prediction-seal.json").write_text(
                json.dumps(
                    dict(
                        sha256=hashlib.sha256(raw).hexdigest(),
                        rows=len(rows),
                        posthoc_analysis_started=False,
                    )
                )
            )
            with self.assertRaises(ValueError):
                sealed_index(source, groups, COMMIT)

    def test_invalid_commit_rejected_before_output_directory(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "result"
            with self.assertRaises(ValueError):
                run(Path(t) / "fake", out, source_commit="local")
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
