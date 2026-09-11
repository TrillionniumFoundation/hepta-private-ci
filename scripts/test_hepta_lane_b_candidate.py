#!/usr/bin/env python3
"""Unit tests for the shared Lane B v3 truth bundle."""

from __future__ import annotations

import json
import unittest

from scripts import hepta_lane_b_schema as schema


class LaneBV3Tests(unittest.TestCase):
    def test_duplicate_json_keys_fail(self) -> None:
        with self.assertRaises(schema.Invalid):
            json.loads('{"a":1,"a":2}', object_pairs_hook=schema.pairs)

    def test_closed_sets(self) -> None:
        self.assertEqual(11, len(schema.MODULES))
        self.assertEqual(39, sum(map(len, schema.EXPECTED_OPERATIONS.values())))
        self.assertEqual(9, len(schema.EXTERNAL_GATES))

    def test_symbol_count_ignores_calls(self) -> None:
        self.assertEqual(1, schema.symbol_occurrences(" pub fn run() {}\nrun();\n", "pub fn run("))

    def test_bundle_is_repository_closed(self) -> None:
        bundle = schema.load_bundle()
        mapped, delegated = schema.verify_structure(bundle, inspect_source=False)
        self.assertEqual((39, 3), (mapped, delegated))
        self.assertEqual(4, schema.verify_companions(bundle))

    def test_agentd_separates_owner_and_callee_roots(self) -> None:
        bundle = schema.load_bundle()
        agentd = next(m for m in bundle["modules"] if m["module"] == "runtime.agentd")
        self.assertEqual(["codex-rs/hepta-agentd"], agentd["canonicalRoots"])
        self.assertEqual(["codex-rs/app-server", "codex-rs/core"], agentd["integrationRoots"])
        delegated = [o for o in agentd["operations"] if "delegatedCallee" in o]
        self.assertEqual(3, len(delegated))
        for operation in delegated:
            self.assertTrue(schema.path_inside(operation["ownerEntrypoint"]["path"], agentd["canonicalRoots"]))
            self.assertTrue(schema.path_inside(operation["delegatedCallee"]["path"], agentd["integrationRoots"]))

    def test_external_gates_cannot_be_self_closed(self) -> None:
        bundle = schema.load_bundle()
        self.assertEqual(0, bundle["gaps"]["repositoryControlled"]["open"])
        self.assertTrue(all(g["state"] == "open" and g["selfCertifiable"] is False
                            for g in bundle["external"]["gates"]))


if __name__ == "__main__":
    unittest.main()
