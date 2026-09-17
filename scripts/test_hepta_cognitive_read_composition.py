#!/usr/bin/env python3
"""Bind cognitive.read status claims to its actual product callsites."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs/modules/cognitive.read/IMPLEMENTATION_MAP.json"


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


class CognitiveReadCompositionMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.row = json.loads(MAP_PATH.read_text(encoding="utf-8"))

    def test_status_model_separates_implementation_composition_and_qualification(self) -> None:
        self.assertEqual(self.row["implementationState"], "implemented")
        self.assertEqual(self.row["compositionState"], "product_composed")
        self.assertEqual(
            self.row["qualificationState"],
            "pending_exact_candidate_and_independent_acceptance",
        )
        self.assertTrue(self.row["productionImplementation"])
        self.assertEqual(self.row["productCallerState"], "composed")
        self.assertTrue(self.row["claimBoundary"]["productCompositionImplemented"])
        self.assertFalse(self.row["claimBoundary"]["productExecutionProved"])
        self.assertFalse(self.row["claimBoundary"]["independentAcceptance"])
        self.assertFalse(self.row["claimBoundary"]["activation"])
        self.assertFalse(self.row["claimBoundary"]["release"])

    def test_reviewed_source_base_is_exact_and_ancestral(self) -> None:
        source = self.row["sourceBase"]
        self.assertEqual(self.row["sourceBaseRole"], "reviewed_parent")
        tree = git("rev-parse", f"{source['commit']}^{{tree}}").stdout.strip()
        self.assertEqual(tree, source["tree"])
        ancestor = git("merge-base", "--is-ancestor", source["commit"], "HEAD", check=False)
        self.assertEqual(
            ancestor.returncode,
            0,
            msg=f"cognitive.read reviewed source base is not an ancestor of HEAD: {ancestor.stderr}",
        )

    def test_product_callers_are_real_and_symbol_bound(self) -> None:
        callers = self.row.get("productCallers")
        self.assertIsInstance(callers, list)
        self.assertGreaterEqual(len(callers), 2)
        roles = set()
        for caller in callers:
            path = ROOT / caller["path"]
            self.assertTrue(path.is_file(), msg=f"missing product caller {path}")
            source = path.read_text(encoding="utf-8")
            self.assertIn(caller["symbol"], source)
            roles.add(caller["role"])
        self.assertIn("canonical_owner_read_adapter", roles)
        self.assertIn("final_model_dispatch_consumer", roles)

    def test_final_use_gate_precedes_durable_dispatch_and_turn_start(self) -> None:
        source = (
            ROOT / "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"
        ).read_text(encoding="utf-8")
        call = source.index("revalidate_cognitive_context_before_dispatch(&owner")
        durable_dispatch = source.index("control.dispatch_native(", call)
        turn_start = source.index("ClientRequest::TurnStart", durable_dispatch)
        self.assertLess(call, durable_dispatch)
        self.assertLess(durable_dispatch, turn_start)
        self.assertIn("current.snapshot_digest != expected.snapshot_digest", source)
        self.assertIn("current.read_digest != expected.read_digest", source)

    def test_finalization_regressions_are_registered(self) -> None:
        required = {
            "codex-rs/hepta-agentd/src/cognitive_finalization_tests.rs",
            "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs",
            "codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs",
        }
        declared = {
            test
            for operation in self.row["operations"]
            for test in operation.get("tests", [])
        }
        self.assertTrue(required.issubset(declared))
        for path in required:
            self.assertTrue((ROOT / path).is_file(), msg=f"missing declared test {path}")


if __name__ == "__main__":
    unittest.main()
