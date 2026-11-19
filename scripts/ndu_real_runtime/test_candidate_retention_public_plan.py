"""MEM6 plan/report contracts; fixtures do not establish scientific benefit."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import candidate_retention_public_plan as planning
from .candidate_selector import PROFILE
from .objective import canonical_sha
from .test_run_candidate_retention import request_fixture


def request(root):
    value = request_fixture(root)
    value.update(
        schema=planning.SCHEMA,
        selection_salt=planning.SELECTION_SALT,
        selector_profile_sha256=canonical_sha(PROFILE),
        prior_episode_plan_pins=[
            {"path": "old-plan-" + str(i), "sha256": sha, "bytes": 1}
            for i, sha in enumerate(sorted(planning.REQUIRED_PRIOR_PLANS))
        ],
    )
    value["sampling_profile_sha256"] = canonical_sha(planning.sampling_profile(value))
    return value


def fixture_plan(root):
    value = request(root)
    receipts = [
        {"pin": pin, "source_groups": ["old"], "inherited_excluded_source_groups": []}
        for pin in value["prior_episode_plan_pins"]
    ]
    # Prior-file verification is covered by test_candidate_selection_plan; this
    # fixture isolates the new sampling and fixed-selector materialization.
    with patch.object(
        planning, "prior_source_groups", return_value=({"old"}, receipts)
    ):
        plan, jobs = planning.freeze(value, root / "run")
    return value, plan, jobs


class PublicRetentionPlanTests(unittest.TestCase):
    def test_frozen_pairs_use_public_selector_and_new_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, plan, jobs = fixture_plan(Path(temporary))
            self.assertEqual((len(jobs), len(plan["episodes"])), (6, 12))
            for pair in jobs:
                expected = [j["expected"] for j in pair]
                self.assertEqual(
                    {e["retention_mode"] for e in expected}, set(planning.MODES)
                )
                self.assertEqual(
                    {e["selector_mode"] for e in expected}, {"public_rule"}
                )
                self.assertEqual(
                    expected[0]["candidate_selector_profile"],
                    expected[1]["candidate_selector_profile"],
                )
                self.assertEqual(
                    expected[0]["control_plan_sha256"],
                    expected[1]["control_plan_sha256"],
                )
            self.assertFalse(plan["cross_session_memory_evaluated"])

    def test_allocation_or_selector_changes_fail_before_material_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            value = request(Path(temporary))
            for change in (
                {"selector_profile_sha256": "0" * 64},
                {"groups_per_role": {"development": 2, "retention_validation": 1}},
                {"prior_episode_plan_pins": value["prior_episode_plan_pins"][:1]},
                {"groups_per_role": {"development": True, "retention_validation": 1}},
            ):
                with (
                    self.subTest(change=change),
                    patch.object(planning, "prior_source_groups") as old,
                ):
                    with self.assertRaises(ValueError):
                        planning.freeze({**value, **change}, Path(temporary) / "unused")
                    old.assert_not_called()

    def test_exhaustion_never_relaxes_old_source_exclusions(self):
        with tempfile.TemporaryDirectory() as temporary:
            value = request(Path(temporary))
            with patch.object(
                planning, "prior_source_groups", return_value=({"development"}, [])
            ):
                with self.assertRaisesRegex(
                    ValueError, "Insufficient complete unexcluded"
                ):
                    planning.freeze(value, Path(temporary) / "unused")
            self.assertFalse((Path(temporary) / "unused/PLAN.json").exists())

    def test_independent_cohort_rebuild_rejects_omitted_family_or_changed_episode(self):
        with tempfile.TemporaryDirectory() as temporary:
            value, plan, _ = fixture_plan(Path(temporary))
            with patch.object(
                planning,
                "prior_source_groups",
                return_value=(
                    set(plan["prior_episode_source_groups"]),
                    plan["prior_episode_plans"],
                ),
            ):
                planning.verify_cohort(plan, value["config"]["material_root"])
                omitted = copy.deepcopy(plan)
                omitted["episodes"] = omitted["episodes"][2:]
                omitted["paired_run_order"] = omitted["paired_run_order"][1:]
                changed = copy.deepcopy(plan)
                for row in changed["episodes"][:2]:
                    row["episode_group"] = "different-episode"
                for bad in (omitted, changed):
                    with self.assertRaisesRegex(ValueError, "Full frozen.*roster"):
                        planning.verify_cohort(bad, value["config"]["material_root"])


if __name__ == "__main__":
    unittest.main()
