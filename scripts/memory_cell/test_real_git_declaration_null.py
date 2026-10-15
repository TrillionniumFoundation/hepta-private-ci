"""Actual SHA-pinned Git-source declaration-null tests; no model executions."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from real_git_declaration_null import audit, read_snippets_only
from real_source_reader_probe import (
    FROZEN_PLAN_SHA256,
    build_plan,
    canonical,
    digest,
    plan_from_archives,
    real_source,
)
from real_git_order_v4 import ORDER_PLAN_SHA256, build_order_plan
from test_real_source_reader_probe import pretend_corpus


def make_snippet(marker: str, content: str) -> dict:
    return dict(marker=marker, text=f"Source marker: {marker}\nFile: x.py\n{content}")


class DeclarationNullTests(unittest.TestCase):
    def setUp(self):
        self.files, self.blobs = pretend_corpus()
        self.plan = build_plan(self.files, self.blobs)

    def test_symbol_comes_from_question_not_gold(self):
        q = "Find declaration for `precise_function_1_0` in source files."
        content = [
            make_snippet("F01", "def precise_function_1_0():\n    pass"),
            make_snippet("F02", "def a_different_function():\n    pass"),
        ]
        chosen = read_snippets_only(q, content)
        self.assertEqual(chosen["answer"], "F01 [E1]")
        self.assertFalse(chosen["abstained"])

    def test_reversed_order_changes_only_citation_index(self):
        q = "Where is `precise_function_1_0` declared?"
        candidates = [
            make_snippet("F01", "def something_other():\n    pass"),
            make_snippet("F02", "def precise_function_1_0():\n    pass"),
        ]
        a = read_snippets_only(q, candidates)
        b = read_snippets_only(q, list(reversed(candidates)))
        self.assertEqual(a["answer"], "F02 [E2]")
        self.assertEqual(b["answer"], "F02 [E1]")

    def test_no_evidence_and_full_symbol_lesion_abstain(self):
        q = "Identify declaration for `precise_function_1_0`"
        self.assertIsNone(read_snippets_only(q, [])["answer"])
        deleted = [
            make_snippet("F01", "def another():\n    pass"),
            make_snippet("F02", "def different():\n    pass"),
        ]
        self.assertTrue(read_snippets_only(q, deleted)["abstained"])

    def test_comments_calls_and_partial_symbol_do_not_count(self):
        q = "Find `precise_function_1_0` declaration"
        snippets = [
            make_snippet("F01", "# def precise_function_1_0():"),
            make_snippet("F02", "value = precise_function_1_0()"),
            make_snippet("F03", "def precise_function_1_0_suffix():"),
        ]
        self.assertEqual(read_snippets_only(q, snippets)["evidence_match_count"], 0)

    def test_duplicate_declarations_require_abstention_not_rank_choice(self):
        q = "Find `precise_function_1_0`"
        snippets = [
            make_snippet("F01", "def precise_function_1_0():"),
            make_snippet("F02", "async def precise_function_1_0():"),
        ]
        result = read_snippets_only(q, snippets)
        self.assertTrue(result["abstained"])
        self.assertEqual(result["evidence_match_count"], 2)

    def test_malformed_query_marker_and_duplicate_source_reject(self):
        q = "Find `precise_function_1_0`"
        bad = [make_snippet("F01", "def precise_function_1_0():")]
        for question, rows in [
            ("Query has no symbol", bad),
            ("Find `foo` and `bar`", bad),
            (q, [make_snippet("wrong", "def precise_function_1_0():")]),
            (q, bad * 2),
            (q, bad * 5),
        ]:
            with self.subTest(question=question, rows=len(rows)):
                with self.assertRaises(ValueError):
                    read_snippets_only(question, rows)

    def test_exact_original_fixture_supports_both_python_and_rust(self):
        for case in self.plan["cases"]:
            snippets = case["conditions"]["hybrid_k4"]
            chosen = read_snippets_only(case["question"], snippets)
            self.assertIsNotNone(chosen["answer"])
            self.assertEqual(chosen["evidence_match_count"], 1)
            self.assertTrue(
                read_snippets_only(
                    case["question"], case["conditions"]["removed_declaration"]
                )["abstained"]
            )

    def test_v4_permutation_only_not_new_source(self):
        if not os.environ.get("MEMORY_REAL_SOURCE_ZIP") or not os.environ.get(
            "MEMORY_REOPEN_ZIP"
        ):
            self.skipTest("exact original plan archives not present")
        v3 = plan_from_archives(
            Path(os.environ["MEMORY_REAL_SOURCE_ZIP"]),
            Path(os.environ["MEMORY_REOPEN_ZIP"]),
        )
        v4 = build_order_plan(v3)
        for case in v4["cases"]:
            normal = read_snippets_only(
                case["question"], case["conditions"]["lexical_order"]
            )
            reverse = read_snippets_only(
                case["question"], case["conditions"]["reverse_order"]
            )
            self.assertEqual(normal["answer"].split()[0], reverse["answer"].split()[0])
            self.assertEqual(
                {e["marker"] for e in case["conditions"]["lexical_order"]},
                {e["marker"] for e in case["conditions"]["reverse_order"]},
            )

    def test_original_git_source_and_pinned_report(self):
        if not os.environ.get("MEMORY_REAL_SOURCE_ZIP") or not os.environ.get(
            "MEMORY_REOPEN_ZIP"
        ):
            self.skipTest("external immutable Git original ZIP files absent")
        src = Path(os.environ["MEMORY_REAL_SOURCE_ZIP"])
        reopen = Path(os.environ["MEMORY_REOPEN_ZIP"])
        v3 = plan_from_archives(src, reopen)
        self.assertEqual(digest(canonical(v3) + b"\n"), FROZEN_PLAN_SHA256)
        v4 = build_order_plan(v3)
        self.assertEqual(digest(canonical(v4) + b"\n"), ORDER_PLAN_SHA256)
        report = audit(v3, real_source(src, reopen))
        self.assertEqual(report["source_only_predicted_attempts"], 54)
        self.assertEqual(report["rank_only_first_original_correct"], 7)
        self.assertEqual(report["rank_only_first_reversed_correct"], 1)
        self.assertEqual(
            [
                report["arms"][k]["correct"]
                for k in (
                    "v3:none",
                    "v3:hybrid_k4",
                    "v3:mechanical_support",
                    "v3:removed_declaration",
                    "v4:lexical_order",
                    "v4:reverse_order",
                )
            ],
            [0, 9, 9, 0, 9, 9],
        )
        self.assertFalse(report["production_qualified"])
        self.assertEqual(report["actual_model_generations"], 0)
        self.assertFalse(report["parameter_memory_benefit_established"])

    def test_reversed_rank_null_is_computed_from_frozen_source_order(self):
        if not os.environ.get("MEMORY_REAL_SOURCE_ZIP") or not os.environ.get(
            "MEMORY_REOPEN_ZIP"
        ):
            self.skipTest("original Git files not present")
        src = Path(os.environ["MEMORY_REAL_SOURCE_ZIP"])
        reopen = Path(os.environ["MEMORY_REOPEN_ZIP"])
        v3 = plan_from_archives(src, reopen)
        v4 = build_order_plan(v3)
        cases = {c["id"]: c for c in v4["cases"]}
        root = {c["id"]: c for c in v3["cases"]}
        observed = sum(
            cases[id_]["conditions"]["reverse_order"][0]["marker"]
            == next(e["marker"] for e in root[id_]["conditions"]["mechanical_support"])
            for id_ in root
        )
        self.assertEqual(observed, 1)
        self.assertEqual(
            audit(v3, real_source(src, reopen))["rank_only_first_reversed_correct"],
            observed,
        )

    def test_original_git_mutation_rejected(self):
        changed = deepcopy(self.blobs)
        name = next(iter(changed))
        changed[name] = b"def unrelated_function():\n    pass\n"
        with self.assertRaisesRegex(ValueError, "source byte/plan drift"):
            audit(self.plan, (self.files, changed))

    def test_malicious_staged_reordering_cannot_score(self):
        v3 = deepcopy(self.plan)
        v3["cases"][0]["conditions"]["hybrid_k4"].reverse()
        with self.assertRaisesRegex(ValueError, "source byte/plan drift"):
            audit(v3, (self.files, self.blobs))

    def test_cli_write_once_and_recompute_receipt(self):
        if not os.environ.get("MEMORY_REAL_SOURCE_ZIP") or not os.environ.get(
            "MEMORY_REOPEN_ZIP"
        ):
            self.skipTest("external immutable Git original ZIP files absent")
        src = Path(os.environ["MEMORY_REAL_SOURCE_ZIP"])
        reopen = Path(os.environ["MEMORY_REOPEN_ZIP"])
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "result.json"
            cmd = [
                sys.executable,
                str(Path(__file__).with_name("real_git_declaration_null.py")),
                "--source-zip",
                str(src),
                "--reopen-zip",
                str(reopen),
                "--output",
                str(target),
            ]
            first = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            self.assertEqual(first.returncode, 0, first.stderr)
            x = json.loads(target.read_bytes())
            self.assertEqual(x["arms"]["v4:reverse_order"]["correct"], 9)
            old = digest(target.read_bytes())
            second = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(old, digest(target.read_bytes()))


if __name__ == "__main__":
    unittest.main()
