#!/usr/bin/env python3
"""Regression tests for source finalization; no compiler or repository writes."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "kg_finalize", Path(__file__).with_name("hepta-kg-convergence-finalize.py")
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

G14_SPEC = importlib.util.spec_from_file_location(
    "kg_g14_docs_finalize", Path(__file__).with_name("hepta-kg-g14-docs-finalize.py")
)
assert G14_SPEC is not None and G14_SPEC.loader is not None
G14_MODULE = importlib.util.module_from_spec(G14_SPEC)
G14_SPEC.loader.exec_module(G14_MODULE)


def fixture() -> str:
    call = (
        "    let (edges, omitted) = collect_relation_query_edges(\n"
        "        generation.edges.iter(),\n"
        "        generation.edges.len(),\n"
        + MODULE.OLD_ARGUMENTS + "    );\n"
    )
    return (
        MODULE.OLD_ADJACENCY + "\n" + call + call
        + MODULE.OLD_SIGNATURE
        + "\n    if measure_work { work.omitted_edges += 1; }\n"
        + "    (Vec::new(), 0)\n}\n\nfn saturating_u64(value: usize) -> u64 { value as u64 }\n"
    )


def g14_rule(text: str, replacement: str = "replacement") -> tuple[str, str, str, str, str]:
    import hashlib

    return (
        "fixture.md",
        "paragraph",
        text[:24],
        hashlib.sha256(text.encode("utf-8")).hexdigest(),
        replacement,
    )


class G14DocsFinalizeTests(unittest.TestCase):
    def test_exact_post_transform_rule_synchronizes_once(self) -> None:
        anchor = "post-transform exact G14 anchor"
        source = "before\n\n" + anchor + "\n\nafter\n"
        result = G14_MODULE.apply_rule(source, g14_rule(anchor))
        self.assertEqual(result, "before\n\nreplacement\n\nafter\n")

    def test_missing_post_transform_anchor_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            G14_MODULE.apply_rule("unrelated", g14_rule("post-transform exact G14 anchor"))

    def test_duplicate_post_transform_anchor_is_rejected(self) -> None:
        anchor = "post-transform exact G14 anchor"
        with self.assertRaises(SystemExit):
            G14_MODULE.apply_rule(anchor + "\n\n" + anchor, g14_rule(anchor))

    def test_post_transform_anchor_digest_drift_is_rejected(self) -> None:
        anchor = "post-transform exact G14 anchor"
        rule = list(g14_rule(anchor))
        rule[3] = "0" * 64
        with self.assertRaises(SystemExit):
            G14_MODULE.apply_rule(anchor, tuple(rule))

    def test_rules_cover_the_three_g14_documents(self) -> None:
        self.assertEqual(
            {rule[0] for rule in G14_MODULE.RULES},
            {
                "docs/modules/knowledge.graph/TECHNICAL.md",
                "qualification/module-execution-dossiers/detail/knowledge.graph.md",
                "codex-rs/hepta-memory/LANE_C_SQLITE.md",
            },
        )
        self.assertEqual(len(G14_MODULE.RULES), 16)


class FinalizeTests(unittest.TestCase):
    def test_success_preserves_name_but_replaces_complete_signature(self) -> None:
        result = MODULE.finalize(fixture())
        self.assertIn(MODULE.NEW_SIGNATURE, result)
        self.assertEqual(result.count("collect_relation_query_edges::<MEASURE_WORK>("), 2)
        self.assertNotIn(MODULE.OLD_SIGNATURE, result)
        self.assertNotIn("if measure_work", result)
        self.assertIn("if MEASURE_WORK", result)
        self.assertNotIn("#[allow", result)

    def test_missing_signature_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.finalize(fixture().replace(MODULE.OLD_SIGNATURE, ""))

    def test_duplicate_signature_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.finalize(fixture() + MODULE.OLD_SIGNATURE)

    def test_missing_call_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.finalize(fixture().replace(MODULE.OLD_ARGUMENTS, "", 1))

    def test_unexpected_extra_call_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.finalize(fixture() + "collect_relation_query_edges(\n")

    def test_changed_adjacency_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.finalize(fixture().replace(MODULE.OLD_ADJACENCY, ""))

    def test_repeated_application_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.finalize(MODULE.finalize(fixture()))


if __name__ == "__main__":
    unittest.main()

# Candidate-branch trigger: execute the retained convergence workflow on this exact source head.
