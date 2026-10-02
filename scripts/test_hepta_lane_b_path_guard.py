"""Canonical cross-lane source ownership must stay registered and bounded."""

import copy
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "lane_b_path_guard", Path(__file__).with_name("hepta-lane-b-path-guard.py")
)
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


class RegisteredDelegationTests(unittest.TestCase):
    def test_actual_registered_cross_lane_owner_is_accepted(self):
        self.assertEqual(GUARD.verify(), 0)

    def test_unregistered_owner_is_rejected_by_full_guard(self):
        original = GUARD.load
        target = GUARD.ROOT / "docs/modules/runtime.agentd/IMPLEMENTATION_MAP.json"
        row = copy.deepcopy(original(target))
        operation = next(
            r
            for r in row["operations"]
            if r.get("operation") == "admit_revalidated_run_start"
        )
        operation["delegatedCallees"][0]["ownerModule"] = "unregistered.owner"
        with mock.patch.object(
            GUARD, "load", side_effect=lambda p: row if p == target else original(p)
        ):
            with self.assertRaisesRegex(GUARD.Invalid, "unregistered delegated owner"):
                GUARD.verify()

    def test_registered_name_does_not_allow_source_root_escape(self):
        original = GUARD.load
        target = GUARD.ROOT / "docs/modules/runtime.agentd/IMPLEMENTATION_MAP.json"
        row = copy.deepcopy(original(target))
        operation = next(
            r
            for r in row["operations"]
            if r.get("operation") == "admit_revalidated_run_start"
        )
        operation["delegatedCallees"][0]["ownerModule"] = "neuron.runtime"
        with mock.patch.object(
            GUARD, "load", side_effect=lambda p: row if p == target else original(p)
        ):
            with self.assertRaisesRegex(GUARD.Invalid, "delegate-root escape"):
                GUARD.verify()
