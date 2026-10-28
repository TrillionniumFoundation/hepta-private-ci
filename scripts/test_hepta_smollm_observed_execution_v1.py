"""Synthetic record boundaries and real local export filtering; no model claim."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import hepta_smollm_answer_eos_research_v3 as research
import hepta_smollm_observed_execution_v1 as observed
import test_hepta_smollm_answer_eos_research_v3 as original
import test_hepta_smollm_metadata_artifact_v1 as original_export


class ObservedBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.base = original.ResearchBoundaryTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        policy = dict(
            profile="linux-owned-exit-worker-pidfd-v4",
            maximum_drain_ns=100000000,
            observer_source_sha256="1" * 64,
            base_observer_source_sha256="2" * 64,
            diagnostic_source_sha256="3" * 64,
        )
        identity = hashlib.sha256(
            json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        context = dict(
            profile="canonical-parent-original-task-observed-execution-v1",
            observer=identity,
            plan_sha256="4" * 64,
            model_plan="5" * 64,
        )
        phases = []
        for prefix in ("train-", "evaluate-"):
            budget = (
                dict(wall_seconds=1800, rss_bytes=16 * 1024**3)
                if prefix == "train-"
                else dict(wall_seconds=600, rss_bytes=8 * 1024**3)
            )
            for role in observed.ROLES:
                phases.append(
                    dict(
                        name=prefix + role,
                        budget=budget,
                        exit_observation_profile=policy,
                        terminal_reconciliation_profile="explicit-linux-owned-exit-worker-pidfd-v4",
                        outcome="success",
                        exit_code=0,
                        stop_reason=None,
                        waited_child_reaped=True,
                        owned_child_reap_resolved=True,
                        owned_child_echild_observed=False,
                        waited_child_observation_error=None,
                    )
                )
        self.loop = copy.deepcopy(self.base.loop)
        self.loop.update(
            schema=observed.LOOP,
            execution_profile=observed.PROFILE,
            rounds=[
                dict(
                    schema=observed.ASSESSMENT,
                    execution_profile=observed.PROFILE,
                    model_plan_profile="strict-v1",
                    observation_execution=copy.deepcopy(context),
                    phases=copy.deepcopy(phases),
                )
                for _ in range(3)
            ],
        )

    def test_only_explicit_original_parent_request_is_allowed(self):
        value = dict(observation_profile=observed.PROFILE, round=1)
        observed.validate_request(SimpleNamespace(**value))
        for change in (
            dict(observation_profile="strict-v2"),
            dict(round=4),
            dict(research_profile="research"),
            dict(proposal_parent=Path("/candidate")),
        ):
            with self.assertRaises(ValueError):
                observed.validate_request(SimpleNamespace(**dict(value, **change)))

    def test_complete_new_context_retains_original_ordinary_readback_gate(self):
        before = copy.deepcopy(self.loop)
        research.validate_ordinary_loop(self.base.session, self.loop)
        self.assertEqual(self.loop, before)
        changed = copy.deepcopy(self.loop)
        changed["ordinary_sessions"][-1]["parent"] = dict(adapter="changed")
        with self.assertRaises(ValueError):
            research.validate_ordinary_loop(self.base.session, changed)

    def test_old_namespace_cannot_relabel_new_context(self):
        changed = copy.deepcopy(self.loop)
        changed["schema"] = self.base.loop["schema"]
        with self.assertRaisesRegex(ValueError, "legacy loop"):
            research.validate_ordinary_loop(self.base.session, changed)
        for schema in ("unknown", self.base.loop["schema"]):
            changed = copy.deepcopy(self.loop)
            changed["rounds"][0]["schema"] = schema
            with self.assertRaises(ValueError):
                observed.validate_loop_context(changed)

    def test_missing_duplicate_or_reordered_original_control_refuses(self):
        for mutation in ("missing", "duplicate", "reorder"):
            changed = copy.deepcopy(self.loop)
            phases = changed["rounds"][0]["phases"]
            if mutation == "missing":
                phases.pop()
            elif mutation == "duplicate":
                phases[-1] = phases[0]
            else:
                phases[0], phases[1] = phases[1], phases[0]
            with self.assertRaisesRegex(ValueError, "five train"):
                observed.validate_loop_context(changed)

    def test_success_exit_cannot_replace_original_exact_reap(self):
        for change in (
            dict(waited_child_reaped=False),
            dict(owned_child_echild_observed=True),
            dict(exit_code=False),
            dict(stop_reason="rss-observation-unavailable"),
        ):
            changed = copy.deepcopy(self.loop)
            changed["rounds"][1]["phases"][0].update(change)
            with self.assertRaises(ValueError):
                observed.validate_loop_context(changed)

    def test_observer_or_original_resource_budget_drift_refuses(self):
        for change in (
            dict(budget=dict(wall_seconds=1801, rss_bytes=16 * 1024**3)),
            dict(terminal_reconciliation_profile="strict-v1"),
            dict(
                exit_observation_profile=dict(
                    profile="strict-v1", maximum_drain_ns=100000000
                )
            ),
        ):
            changed = copy.deepcopy(self.loop)
            changed["rounds"][2]["phases"][0].update(change)
            with self.assertRaises(ValueError):
                observed.validate_loop_context(changed)

    def test_observed_loop_cannot_claim_installed_or_qualified_child(self):
        for field, value in (
            ("installed_children", 1),
            ("product_qualification_issued", True),
            ("completed_rounds", 2),
        ):
            changed = copy.deepcopy(self.loop)
            changed[field] = value
            with self.assertRaises(ValueError):
                research.validate_ordinary_loop(self.base.session, changed)

    def test_metadata_export_retains_new_context_but_omits_model_and_archive(self):
        files = original_export.MetadataArtifactTests()
        files.setUp()
        self.addCleanup(files.doCleanups)
        prefix = "n/p/round-1/"
        names = (
            "observation-chain-source.txt",
            prefix + "observation-plan-v1.json",
            prefix + "train-candidate/parent-step-input-observed-v1.json",
            prefix + "train-candidate/parent-step-result-observed-v1.json",
        )
        for name in names:
            files.file(name, b"{}\n")
        files.file(
            prefix + "train-candidate/execution/artifact.safetensors",
            b"synthetic exclusion fixture",
        )
        files.file(
            prefix + "train-candidate/execution/checkpoint.tar.gz",
            b"synthetic exclusion fixture",
        )
        files.index()
        result = files.run_export()
        self.assertEqual(set(result["files"]), set(names) | {"evidence-index.json"})
        self.assertEqual(result["omitted_file_count"], 2)
        self.assertFalse(result["checkpoint_payloads_exported"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
