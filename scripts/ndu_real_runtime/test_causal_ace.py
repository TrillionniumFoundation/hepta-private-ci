"""Adversarial A/C/E protocol tests; fixtures are not real owner evidence."""

from copy import deepcopy
import hashlib
import unittest

from .causal_ace import (
    ACEValidationError,
    COST_STAGES,
    COST_UNITS,
    assess_a_capabilities,
    check_next_use,
    compare_improvers,
    validate_c_design,
    validate_composition_manifest,
)


def pin(value):
    return hashlib.sha256(value.encode()).hexdigest()


def a_fixture():
    resources = {
        key: pin(key)
        for key in (
            "model_family",
            "information",
            "tools",
            "training_opportunities",
            "tuning_opportunities",
            "full_budget",
        )
    }
    resources.update(memory_bytes=4096, parameter_count=256)
    registry, arms = {}, []
    for kind in ("single_agent", "fixed_roles", "cell"):
        roles = [
            {
                "role_id": name,
                "module_path": f"{kind}.{name}",
                "state_owner": f"owner.{name}",
                "local_parameters": [f"{name}.weight"],
            }
            for name in (["solo"] if kind == "single_agent" else ["A", "B"])
        ]
        registry[kind] = {
            "source_commit": "a" * 40,
            "source_tree": "b" * 40,
            "implementation_sha256": pin(kind),
            "entrypoint": f"fixture:{kind}",
            "kind": kind,
            "roles": roles,
            "parameter_inventory": [
                parameter for role in roles for parameter in role["local_parameters"]
            ],
            "supported_ablations": [
                "none",
                "reset_state",
                "freeze_differentiation",
                "remove_role",
            ],
        }
        for ablation in (
            ["none"] if kind != "cell" else registry[kind]["supported_ablations"]
        ):
            arms.append(
                {
                    "arm_id": kind + ":" + ablation,
                    "architecture": kind,
                    "implementation_id": kind,
                    "ablation": ablation,
                    "removed_role": "B" if ablation == "remove_role" else None,
                    "resources": deepcopy(resources),
                }
            )
    return arms, registry


def manifest_fixture():
    order = ["encoder", "base", "A", "B", "heads"]
    components = {}
    for index, name in enumerate(order):
        low_rank = name in {"A", "B"}
        components[name] = {
            "sha256": pin(name),
            "implementation_sha256": pin("implementation." + name),
            "version": 1,
            "kind": "low_rank" if low_rank else "dense",
            "shape": [2, 2],
            "rank": 1 if low_rank else 0,
            "scale": 0.5 if low_rank else 1,
            "input_schema": pin(f"interface.{index}"),
            "output_schema": pin(f"interface.{index + 1}"),
            "base_sha256": pin("base") if low_rank else None,
            "dependencies": [order[index - 1]] if index else [],
            "tensors": {f"{name}.down": [1, 2], f"{name}.up": [2, 1]}
            if low_rank
            else {f"{name}.weight": [2, 2]},
        }
    compatibility = {
        key: pin(key)
        for key in (
            "tokenizer",
            "normalizer",
            "calibration",
            "numeric_profile",
            "output_schema",
            "state_schema",
            "state_semantics",
        )
    }
    compatibility["output_schema"] = components["heads"]["output_schema"]
    return {
        "schema": "ndu.causal.composition.v1",
        "bundle_digest": pin("baseline-bundle"),
        "components": components,
        "order": order,
        "compatibility": compatibility,
    }


def c_design_fixture():
    baseline = manifest_fixture()
    manifests = {"none": baseline}
    for update, changed in (
        ("A", ("A",)),
        ("B", ("B",)),
        ("AB", ("A", "B")),
        ("shared_base", ("base",)),
    ):
        current = deepcopy(baseline)
        current["bundle_digest"] = pin("bundle." + update)
        for name in changed:
            current["components"][name].update(
                sha256=pin(update + "." + name), version=2
            )
        if update == "shared_base":
            for name in ("A", "B"):
                current["components"][name]["base_sha256"] = current["components"][
                    "base"
                ]["sha256"]
        manifests[update] = current
    design = {
        "schema": "ndu.causal.composition-design.v1",
        "baseline_manifest": "none",
        "state_modes": ["reset", "migrate"],
        "recovery_domains": ["model", "external_effects"],
        "conditions": [
            {
                "arm_id": f"{update}.{mode}",
                "update": update,
                "state_mode": mode,
                "manifest": update,
            }
            for update in manifests
            for mode in ("reset", "migrate")
        ],
    }
    return design, manifests


def next_use_fixture():
    expected = {
        "operation_id": "learning-original",
        "predecessor": pin("predecessor"),
        "next_use_owner": "independent-observer",
        "state_owner": "original-state-owner",
        "principal_id": "principal",
        "agent_id": "agent",
        "cell_id": "cell",
        "source_run_id": "old-task",
        "next_run_id": "different-task",
        "candidate_bundle": pin("full-selected-bundle"),
        "selection_digest": pin("selection"),
        "checkpoint_digest": pin("next-checkpoint"),
        "source_checkpoint_digest": pin("old-checkpoint"),
        "state_receipt_digest": pin("state-receipt"),
        "state_mode": "migrate",
        "retained": False,
    }
    partition = {key: expected[key] for key in ("principal_id", "agent_id", "cell_id")}
    partition["run_id"] = expected["next_run_id"]
    receipt = {
        "actor_id": expected["next_use_owner"],
        "operation_id": expected["operation_id"],
        "predecessor": expected["predecessor"],
        "evidence_digest": pin("owner-evidence"),
        "observed_unix_seconds": 100,
        "observation": {
            "kind": "NextUse",
            "candidate_bundle": expected["candidate_bundle"],
            "state_partition": partition,
            "selection_digest": expected["selection_digest"],
            "checkpoint_digest": expected["checkpoint_digest"],
            "state_cutover_receipt": expected["state_receipt_digest"],
            "committed_step_receipt": pin("committed-step"),
        },
    }
    state = {
        "actor_id": expected["state_owner"],
        "state_partition": partition,
        "candidate_bundle": expected["candidate_bundle"],
        "checkpoint_digest": expected["checkpoint_digest"],
        "transition": {
            "kind": "migrate",
            "source_checkpoint": expected["source_checkpoint_digest"],
            "target_checkpoint": expected["checkpoint_digest"],
            "transform": pin("qualified-transform"),
            "qualification": pin("qualification"),
        },
    }
    records = {
        ("next_use", "original/journal/receipt"): receipt,
        ("state_transition", expected["state_receipt_digest"]): state,
    }
    return expected, records


class ArchitectureChecks(unittest.TestCase):
    def run_check(self, arms, registry):
        return assess_a_capabilities(
            arms, registry, source_commit="a" * 40, source_tree="b" * 40
        )

    def test_complete_design_and_absent_implementation_are_distinct(self):
        arms, registry = a_fixture()
        self.assertEqual(
            self.run_check(arms, registry)["status"], "READY_FOR_MATCHED_EXECUTION"
        )
        absent = self.run_check(arms, {})
        self.assertEqual(
            (
                absent["status"],
                absent["missing_conditions"],
                absent["runtime_consumption_verified"],
            ),
            ("BLOCKED_UNIMPLEMENTED", [], False),
        )
        self.assertTrue(
            all(
                row["reason"] == "NO_SOURCE_BOUND_IMPLEMENTATION"
                for row in absent["arms"]
            )
        )

    def test_shared_head_relabel_and_unimplemented_ablation_are_blocked(self):
        arms, registry = a_fixture()
        registry["cell"]["kind"] = "shared_heads"
        self.assertEqual(
            {row["status"] for row in self.run_check(arms, registry)["arms"][2:]},
            {"BLOCKED_UNIMPLEMENTED"},
        )
        registry["cell"]["kind"] = "cell"
        registry["cell"]["supported_ablations"].remove("reset_state")
        self.assertEqual(
            self.run_check(arms, registry)["arms"][3]["reason"],
            "ABLATION_NOT_IMPLEMENTED",
        )

    def test_false_local_state_and_parameter_partitions_are_rejected(self):
        for field in ("state_owner", "module_path", "local_parameters"):
            with self.subTest(field=field):
                arms, registry = a_fixture()
                roles = registry["cell"]["roles"]
                roles[1][field] = roles[0][field]
                with self.assertRaisesRegex(ACEValidationError, "SHARED_HEADS"):
                    self.run_check(arms, registry)

    def test_source_resources_and_missing_comparators(self):
        arms, registry = a_fixture()
        registry["cell"]["source_commit"] = "c" * 40
        with self.assertRaisesRegex(ACEValidationError, "SOURCE_MISMATCH"):
            self.run_check(arms, registry)
        arms, registry = a_fixture()
        arms[-1]["resources"]["memory_bytes"] *= 2
        with self.assertRaisesRegex(ACEValidationError, "UNMATCHED_RESOURCES"):
            self.run_check(arms, registry)
        self.assertEqual(
            self.run_check(arms[:2], registry)["status"], "BLOCKED_UNIMPLEMENTED"
        )


class CompositionChecks(unittest.TestCase):
    def test_tensor_loader_readback_and_full_factorial(self):
        design, manifests = c_design_fixture()
        manifest = manifests["AB"]
        inventory = {
            key: {"sha256": value["sha256"], "tensors": deepcopy(value["tensors"])}
            for key, value in manifest["components"].items()
        }
        self.assertTrue(
            validate_composition_manifest(manifest, tensor_inventory=inventory)[
                "tensor_inventory_checked"
            ]
        )
        self.assertEqual(
            validate_c_design(design, manifests),
            {
                "status": "DESIGN_STRUCTURALLY_VALID",
                "conditions": 10,
                "next_use_verified": False,
                "model_recovery_verified": False,
                "external_effect_recovery_verified": False,
                "authority_granted": False,
            },
        )
        inventory["A"]["tensors"]["A.down"] = [2, 2]
        with self.assertRaisesRegex(ACEValidationError, "LOADED_TENSOR_MISMATCH"):
            validate_composition_manifest(manifest, tensor_inventory=inventory)
        inventory["A"]["tensors"]["A.down"] = [True, 2]
        with self.assertRaisesRegex(ACEValidationError, "LOADED_TENSOR_MISMATCH"):
            validate_composition_manifest(manifest, tensor_inventory=inventory)

    def test_incompatible_composition_counterexamples(self):
        cases = [
            ("rank", 3, "LOW_RANK_FACTORS"),
            ("scale", float("nan"), "SHAPE_RANK_SCALE"),
            ("version", 0, "VERSION_OR_PIN"),
            ("base_sha256", pin("wrong-base"), "BASE_INCOMPATIBLE"),
            ("input_schema", pin("wrong-schema"), "INTERFACE_INCOMPATIBLE"),
            ("tensors", {"A.down": [1, 2], "A.up": [2, 2]}, "LOW_RANK_FACTORS"),
        ]
        for field, value, code in cases:
            with self.subTest(field=field):
                manifest = manifest_fixture()
                manifest["components"]["A"][field] = value
                with self.assertRaisesRegex(ACEValidationError, code):
                    validate_composition_manifest(manifest)
        manifest = manifest_fixture()
        manifest["order"][2:4] = ["B", "A"]
        with self.assertRaisesRegex(ACEValidationError, "COMPONENT_ORDER"):
            validate_composition_manifest(manifest)

    def test_hidden_update_and_unpaired_state_models_are_refused(self):
        design, manifests = c_design_fixture()
        manifests["A"]["components"]["B"].update(
            sha256=pin("hidden-B-update"), version=2
        )
        with self.assertRaisesRegex(ACEValidationError, "WRONG_UPDATE_TARGET"):
            validate_c_design(design, manifests)
        design, manifests = c_design_fixture()
        manifests["A-other"] = deepcopy(manifests["A"])
        manifests["A-other"]["bundle_digest"] = pin("another-model")
        design["conditions"][3]["manifest"] = "A-other"
        with self.assertRaisesRegex(ACEValidationError, "STATE_PAIR_CHANGED_MODEL"):
            validate_c_design(design, manifests)
        design["conditions"].pop()
        design["conditions"][3]["manifest"] = "A"
        with self.assertRaisesRegex(ACEValidationError, "INCOMPLETE_FACTORIAL"):
            validate_c_design(design, manifests)

    def read_next(self, expected, records, *, verifier=None):
        return check_next_use(
            expected,
            "original/journal/receipt",
            read_original=lambda kind, ref: records.get((kind, ref)),
            verify_owner=verifier
            or (lambda kind, record, owner: record["actor_id"] == owner),
        )

    def test_next_use_needs_independent_owner_and_does_not_prove_recovery(self):
        expected, records = next_use_fixture()
        self.assertEqual(
            check_next_use(expected, "original/journal/receipt"),
            {"status": "HOLD_ORIGINAL_OWNER_PORT_REQUIRED", "authority_granted": False},
        )
        self.assertEqual(
            self.read_next(expected, records),
            {
                "status": "ORIGINAL_NEXT_USE_BINDINGS_MATCH",
                "state_mode": "migrate",
                "authentication": "delegated_to_host_original_owner_verifier",
                "model_recovery_verified": False,
                "external_effect_recovery_verified": False,
                "authority_granted": False,
            },
        )
        with self.assertRaisesRegex(ACEValidationError, "AUTHENTICATION_REJECTED"):
            self.read_next(expected, records, verifier=lambda *_args: False)
        records.clear()
        self.assertEqual(
            self.read_next(expected, records)["status"],
            "HOLD_ORIGINAL_RECEIPT_UNAVAILABLE",
        )

    def test_original_receipt_must_consume_selected_bundle_in_distinct_task(self):
        for key, value in (
            ("candidate_bundle", pin("only-adapter-not-full-bundle")),
            ("selection_digest", pin("different-selection")),
            (
                "state_partition",
                {
                    "principal_id": "principal",
                    "agent_id": "agent",
                    "cell_id": "cell",
                    "run_id": "old-task",
                },
            ),
        ):
            with self.subTest(key=key):
                expected, records = next_use_fixture()
                records[("next_use", "original/journal/receipt")]["observation"][
                    key
                ] = value
                with self.assertRaisesRegex(ACEValidationError, "NEXT_USE_MISMATCH"):
                    self.read_next(expected, records)

    def test_reset_is_not_migration_and_retained_model_has_own_receipt_kind(self):
        expected, records = next_use_fixture()
        state = records[("state_transition", expected["state_receipt_digest"])]
        state["transition"] = {
            "kind": "reset",
            "initializer": pin("initializer"),
            "target_checkpoint": expected["checkpoint_digest"],
        }
        with self.assertRaisesRegex(ACEValidationError, "TRANSITION_FIELDS"):
            self.read_next(expected, records)
        expected.update(state_mode="reset", retained=True)
        observation = records[("next_use", "original/journal/receipt")]["observation"]
        observation.update(
            kind="RetainedModelNextUse",
            retained_bundle=observation.pop("candidate_bundle"),
            task_owner_publication=observation.pop("state_cutover_receipt"),
        )
        self.assertEqual(self.read_next(expected, records)["state_mode"], "reset")


