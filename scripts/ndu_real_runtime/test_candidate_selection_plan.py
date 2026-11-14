"""Metadata exclusion and late worker-failure contracts; no actor simulation."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ndu_real_materials.common import binding, write_json
from . import candidate_selection_plan as planning


class PriorPlanTests(unittest.TestCase):
    def test_changed_sample_allocation_is_rejected_before_source_reads(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from .candidate_selector import PROFILE
        from .objective import canonical_sha

        fake = SimpleNamespace(
            verify_sources=Mock(
                side_effect=AssertionError("source read before allocation check")
            )
        )
        request = {
            "schema": planning.SCHEMA,
            "source_commit": "a" * 40,
            "experiment_id": "mem5-test",
            "selection_salt": planning.SELECTION_SALT,
            "max_workers": 2,
            "selector_profile_sha256": canonical_sha(PROFILE),
        }
        for allocation in (
            {"development": 1, "retention_validation": 4},
            {"development": 10, "retention_validation": 4.0},
            {"confirmation": 10, "retention_validation": 4},
        ):
            with patch.dict(
                "sys.modules", {"ndu_real_runtime.run_candidate_retention": fake}
            ):
                with self.assertRaisesRegex(ValueError, r"10\+4"):
                    planning.freeze(
                        {**request, "groups_per_role": allocation}, Path("unused")
                    )
        fake.verify_sources.assert_not_called()

    def fixture(self, root, *, count=1):
        catalog = {
            "cases": [
                {
                    "id": "case-old-dev",
                    "source_id": "old-dev",
                    "role": "development",
                    "episode_group": "episode-old-dev",
                },
                {
                    "id": "case-old-ret",
                    "source_id": "old-ret",
                    "role": "retention_validation",
                    "episode_group": "episode-old-ret",
                },
            ]
        }
        request = {
            "registry_sha256": "1" * 64,
            "config": {"reference_index_sha256": "2" * 64},
            "prior_episode_plan_pins": [],
        }
        for index in range(count):
            case = catalog["cases"][index]
            plan = {
                "schema": "ndu.real.candidate-retention-plan.v1",
                "registry_sha256": request["registry_sha256"],
                "reference_index_sha256": request["config"]["reference_index_sha256"],
                "excluded_source_groups": ["older-exposure"],
                "episodes": [
                    {
                        "original_operation_id": f"prior-{index}-{mode}",
                        "case_id": case["id"],
                        "source_group_id": case["source_id"],
                        "split": case["role"],
                        "episode_group": case["episode_group"],
                    }
                    for mode in ("current_only", "bounded")
                ],
            }
            path = root / f"plan-{index}.json"
            write_json(path, plan)
            request["prior_episode_plan_pins"].append(binding(path, root))
        return request, catalog

    def test_pinned_prior_plans_cover_both_arms_without_dropping_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, catalog = self.fixture(root, count=2)
            old = copy.deepcopy(request)
            with patch.object(
                planning,
                "BASELINE_MEM_PLAN_SHA256",
                request["prior_episode_plan_pins"][0]["sha256"],
            ):
                groups, receipts = planning.prior_source_groups(request, catalog, root)
            self.assertEqual(groups, {"old-dev", "old-ret", "older-exposure"})
            self.assertEqual([r["episode_count"] for r in receipts], [2, 2])
            self.assertEqual(
                [r["source_groups"] for r in receipts], [["old-dev"], ["old-ret"]]
            )
            self.assertEqual(request, old)
            self.assertNotIn("reference", json.dumps(receipts))

    def test_byte_mutation_and_missing_mandatory_campaign_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, catalog = self.fixture(root)
            with self.assertRaisesRegex(ValueError, "original MEM campaign"):
                planning.prior_source_groups(request, catalog, root)
            expected = request["prior_episode_plan_pins"][0]["sha256"]
            path = root / "plan-0.json"
            path.write_bytes(path.read_bytes() + b" ")
            with patch.object(planning, "BASELINE_MEM_PLAN_SHA256", expected):
                with self.assertRaisesRegex(ValueError, "registered bytes"):
                    planning.prior_source_groups(request, catalog, root)

    def test_registry_role_source_and_operation_corruption_are_rejected(self):
        mutations = (
            lambda p: p.update(registry_sha256="3" * 64),
            lambda p: p.update(reference_index_sha256="4" * 64),
            lambda p: p.update(excluded_source_groups=["bad/escaping/source"]),
            lambda p: p["episodes"][0].update(split="confirmation"),
            lambda p: p["episodes"][0].update(source_group_id="wrong-source"),
            lambda p: p["episodes"][0].update(episode_group="wrong-episode"),
            lambda p: p["episodes"][1].update(
                original_operation_id=p["episodes"][0]["original_operation_id"]
            ),
        )
        for mutate in mutations:
            with (
                self.subTest(mutation=mutate),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                request, catalog = self.fixture(root)
                path = root / "plan-0.json"
                plan = json.loads(path.read_text())
                mutate(plan)
                path.write_text(json.dumps(plan))
                request["prior_episode_plan_pins"] = [binding(path, root)]
                with patch.object(
                    planning,
                    "BASELINE_MEM_PLAN_SHA256",
                    request["prior_episode_plan_pins"][0]["sha256"],
                ):
                    with self.assertRaises(ValueError):
                        planning.prior_source_groups(request, catalog, root)

    def test_duplicate_plan_pins_do_not_create_a_fake_exclusion_roster(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, catalog = self.fixture(root)
            pin = request["prior_episode_plan_pins"][0]
            request["prior_episode_plan_pins"].append(copy.deepcopy(pin))
            with patch.object(planning, "BASELINE_MEM_PLAN_SHA256", pin["sha256"]):
                with self.assertRaisesRegex(ValueError, "uniquely cover"):
                    planning.prior_source_groups(request, catalog, root)


if __name__ == "__main__":
    unittest.main()
