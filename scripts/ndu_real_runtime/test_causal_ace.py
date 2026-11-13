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


def cost_fixture(stage, name):
    ledger = {
        key: {
            "status": "not_applicable",
            "values": {},
            "evidence": f"fixture {name}: no {key} operation in this disjoint record",
        }
        for key in COST_STAGES
    }
    ledger[stage] = {
        "status": "measured",
        "values": dict.fromkeys(COST_UNITS, 1.0),
        "evidence": f"fixture meter: {name}/{stage}",
    }
    return ledger


def e_fixture():
    start = {
        "initial_bundle": pin("initial-model"),
        "seed": 17,
        "source_cluster": "source-1",
        "training_families": ["seen-task"],
        "holdout_family": "unseen-task",
    }
    start.update(
        {
            key: pin(key)
            for key in (
                "training_data",
                "development_data",
                "acceptance_data",
                "holdout_data",
            )
        }
    )
    plan = {
        "schema": "ndu.causal.improver-comparison.v1",
        "improvers": {
            "parent": {
                "artifact_digest": pin("parent-improver"),
                "parent_digest": None,
            },
            "child": {
                "artifact_digest": pin("child-improver"),
                "parent_digest": pin("parent-improver"),
            },
        },
        "cost_penalty": {"unit": "cpu_seconds", "per_unit": 0.01},
        "runs": [],
    }
    registry = {
        "schema": "ndu.causal.improver-attempt-registry.v1",
        "sealed": True,
        "entries": [],
        "run_overheads": {},
        "finals": {},
    }
    rows, evaluations = [], {}
    for role in ("parent", "child"):
        run = {
            "run_id": role,
            "pair_id": "pair-1",
            "role": role,
            "improver_digest": plan["improvers"][role]["artifact_digest"],
            "producer_owner": "trainer-" + role,
            "evaluator_owner": "independent-evaluator",
            "common_start": deepcopy(start),
            "full_budget_contract": {
                "scope": list(COST_STAGES),
                "limits": dict.fromkeys(COST_UNITS, 100),
                "candidate_attempts": 8,
            },
            "acceptance_profile": pin("acceptance-profile"),
            "holdout_profile": pin("future-holdout-profile"),
        }
        plan["runs"].append(run)
        registry["run_overheads"][role] = cost_fixture(
            "preparation", role + "-construction-and-setup"
        )
        for index in (1, 2, 3):
            attempt_id = role + str(index)
            entry = {
                "attempt_id": attempt_id,
                "run_id": role,
                "operation_id": "original/" + attempt_id,
                "request_sha256": pin("request." + attempt_id),
                "retry_of": None,
                "original_attempt_reference": "original/journal/" + attempt_id,
            }
            registry["entries"].append(entry)
            if role == "parent" and index == 3:
                continue
            valid = index == 1 or role == "child" and index == 2
            row = {
                key: entry[key]
                for key in ("attempt_id", "run_id", "operation_id", "request_sha256")
            }
            row.update(
                terminal_status="SUCCEEDED"
                if valid
                else "FAILED"
                if index == 2
                else "CANCELLED",
                candidate_digest=pin("candidate." + attempt_id),
                validity="VALID" if valid else "INVALID",
                evaluation_reference=pin("evaluation." + attempt_id) if valid else None,
                rolled_back=role == "parent" and index == 2,
                rollback_reference=pin("rollback." + attempt_id)
                if role == "parent" and index == 2
                else None,
                costs=cost_fixture("training", attempt_id),
            )
            rows.append(row)
            if valid:
                evaluations[("acceptance", row["evaluation_reference"])] = {
                    "kind": "acceptance",
                    "run_id": role,
                    "actor_id": run["evaluator_owner"],
                    "attempt_id": attempt_id,
                    "operation_id": entry["operation_id"],
                    "candidate_bundle": row["candidate_digest"],
                    "baseline_bundle": start["initial_bundle"],
                    "evaluation_profile": run["acceptance_profile"],
                    "data_digest": start["acceptance_data"],
                    "evidence_digest": pin("evidence." + attempt_id),
                    "observed_unix_seconds": 12,
                    "baseline_utility": 0.4,
                    "candidate_utility": 0.6,
                    "accepted": index == 1,
                }
        final = {
            "attempt_id": role + "1",
            "candidate_bundle": pin("candidate." + role + "1"),
            "selection_digest": pin("selected." + role),
            "evaluation_reference": pin("final." + role),
        }
        registry["finals"][role] = final
        evaluations[("heldout_final", final["evaluation_reference"])] = {
            "kind": "heldout_final",
            "run_id": role,
            "actor_id": run["evaluator_owner"],
            "candidate_bundle": final["candidate_bundle"],
            "baseline_bundle": start["initial_bundle"],
            "evaluation_profile": run["holdout_profile"],
            "data_digest": start["holdout_data"],
            "evidence_digest": pin("final-evidence." + role),
            "observed_unix_seconds": 20,
            "baseline_utility": 0.4,
            "candidate_utility": 0.6 if role == "parent" else 0.8,
            "selection_digest": final["selection_digest"],
            "selection_committed_unix_seconds": 15,
            "task_family": start["holdout_family"],
        }
    return plan, registry, rows, evaluations


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


class ImproverChecks(unittest.TestCase):
    def compare(self, fixture, *, authenticated=True):
        plan, registry, rows, evaluations = fixture
        return compare_improvers(
            plan,
            registry,
            rows,
            read_evaluation=lambda kind, reference: evaluations.get((kind, reference)),
            verify_evaluation=(lambda kind, record, owner: record["actor_id"] == owner)
            if authenticated
            else None,
        )

    def test_complete_denominators_and_unknown_cost_survive(self):
        result = self.compare(e_fixture())
        parent, child = result["runs"]["parent"], result["runs"]["child"]
        self.assertEqual(
            (
                result["registered_attempts"],
                result["missing_results"],
                result["status"],
            ),
            (6, ["parent3"], "HOLD_INCOMPLETE_EVIDENCE"),
        )
        self.assertEqual(
            {
                key: parent[key]
                for key in (
                    "attempted",
                    "valid",
                    "invalid",
                    "unknown_validity",
                    "accepted",
                    "accepted_per_attempt",
                    "accepted_per_valid_resolved",
                )
            },
            {
                "attempted": 3,
                "valid": 1,
                "invalid": 1,
                "unknown_validity": 1,
                "accepted": 1,
                "accepted_per_attempt": 1 / 3,
                "accepted_per_valid_resolved": 1,
            },
        )
        self.assertEqual(parent["acceptance_probability_bounds"], [1 / 3, 2 / 3])
        self.assertEqual(parent["reported_rollback_bounds"], [1 / 3, 2 / 3])
        self.assertEqual(parent["cost_totals"], dict.fromkeys(COST_UNITS))
        self.assertEqual(
            parent["cost_known_lower_bounds"], dict.fromkeys(COST_UNITS, 3.0)
        )
        self.assertIsNone(parent["net_improvement"])
        self.assertEqual(child["accepted_per_valid_resolved"], 0.5)
        self.assertAlmostEqual(child["net_improvement"], 0.36)
        self.assertFalse(result["scientific_efficacy_qualified"])

    def test_unverified_evaluations_are_neither_acceptances_nor_rejections(self):
        result = self.compare(e_fixture(), authenticated=False)
        parent = result["runs"]["parent"]
        self.assertEqual(
            (
                parent["accepted"],
                parent["rejected"],
                parent["unresolved_evaluation"],
                parent["accepted_per_valid_resolved"],
                parent["heldout_delta"],
            ),
            (0, 0, 1, None, None),
        )
        self.assertEqual(parent["acceptance_probability_bounds"], [0, 2 / 3])

    def test_dropping_failed_result_does_not_shrink_registry_denominator(self):
        fixture = e_fixture()
        fixture[2][:] = [row for row in fixture[2] if row["attempt_id"] != "parent2"]
        parent = self.compare(fixture)["runs"]["parent"]
        self.assertEqual(
            (parent["attempted"], parent["terminal_counts"]["UNKNOWN"]), (3, 2)
        )

    def test_mismatched_start_budget_lineage_and_self_evaluation_are_refused(self):
        for target in ("start", "budget", "lineage", "self_evaluation", "holdout"):
            with self.subTest(target=target):
                fixture = e_fixture()
                plan = fixture[0]
                child = plan["runs"][1]
                if target == "start":
                    child["common_start"]["seed"] += 1
                elif target == "budget":
                    child["full_budget_contract"]["limits"]["cpu_seconds"] += 1
                elif target == "lineage":
                    plan["improvers"]["child"]["parent_digest"] = pin("other-parent")
                elif target == "self_evaluation":
                    child["evaluator_owner"] = child["producer_owner"]
                else:
                    child["common_start"]["holdout_family"] = "seen-task"
                with self.assertRaises(ACEValidationError):
                    self.compare(fixture)

    def test_duplicate_attempts_and_retry_of_unknown_cannot_create_more_samples(self):
        fixture = e_fixture()
        fixture[1]["entries"].append(deepcopy(fixture[1]["entries"][0]))
        with self.assertRaisesRegex(ACEValidationError, "DUPLICATE_OR_UNBOUND"):
            self.compare(fixture)
        fixture = e_fixture()
        retry = deepcopy(fixture[1]["entries"][2])
        retry.update(
            attempt_id="parent4", operation_id="original/parent4", retry_of="parent3"
        )
        fixture[1]["entries"].append(retry)
        with self.assertRaisesRegex(ACEValidationError, "RETRY_OF_UNRESOLVED"):
            self.compare(fixture)
        fixture = e_fixture()
        fixture[2].append(deepcopy(fixture[2][0]))
        with self.assertRaisesRegex(ACEValidationError, "DUPLICATE_RESULT"):
            self.compare(fixture)

    def test_success_with_missing_cost_and_unmeasured_energy_stays_incomplete(self):
        fixture = e_fixture()
        child1 = next(row for row in fixture[2] if row["attempt_id"] == "child1")
        child1["costs"] = None
        child = self.compare(fixture)["runs"]["child"]
        self.assertEqual(
            (child["reported_cost_coverage_complete"], child["net_improvement"]),
            (False, None),
        )
        fixture = e_fixture()
        child1 = next(row for row in fixture[2] if row["attempt_id"] == "child1")
        child1["costs"]["training"]["values"]["energy_joules"] = None
        child = self.compare(fixture)["runs"]["child"]
        self.assertIsNone(child["cost_totals"]["energy_joules"])
        self.assertFalse(child["reported_cost_coverage_complete"])
        self.assertAlmostEqual(child["net_improvement"], 0.36)

    def test_actual_cost_scope_nonfinite_values_and_budget_overrun_are_rejected(self):
        for mutation in (
            "missing_stage",
            "nan",
            "negative",
            "unsupported_unit",
            "overrun",
            "silent_zero",
        ):
            with self.subTest(mutation=mutation):
                fixture = e_fixture()
                costs = fixture[2][0]["costs"]
                if mutation == "missing_stage":
                    costs.pop("reencoding")
                elif mutation == "unsupported_unit":
                    fixture[0]["cost_penalty"]["unit"] = "mixed_resources"
                elif mutation == "silent_zero":
                    costs["recovery"]["evidence"] = ""
                else:
                    costs["training"]["values"]["cpu_seconds"] = {
                        "nan": float("nan"),
                        "negative": -1,
                        "overrun": 101,
                    }[mutation]
                with self.assertRaises(ACEValidationError):
                    self.compare(fixture)

    def test_evaluation_mismatch_and_posthoc_selection_are_rejected(self):
        for mutation in ("candidate", "profile", "posthoc_selection", "baseline"):
            with self.subTest(mutation=mutation):
                fixture = e_fixture()
                final = fixture[3][("heldout_final", pin("final.child"))]
                if mutation == "candidate":
                    final["candidate_bundle"] = pin("another-candidate")
                elif mutation == "profile":
                    final["evaluation_profile"] = pin("acceptance-profile")
                elif mutation == "posthoc_selection":
                    final["selection_committed_unix_seconds"] = (
                        final["observed_unix_seconds"] + 1
                    )
                else:
                    final["baseline_utility"] = 0.3
                with self.assertRaises(ACEValidationError):
                    self.compare(fixture)

    def test_zero_attempts_have_no_invented_rates(self):
        plan, registry, _rows, evaluations = e_fixture()
        registry.update(entries=[], finals={})
        result = self.compare((plan, registry, [], evaluations))
        self.assertEqual(result["runs"]["parent"]["attempted"], 0)
        self.assertIsNone(result["runs"]["parent"]["valid_per_attempt"])
        self.assertEqual(result["status"], "HOLD_INCOMPLETE_EVIDENCE")

    def test_unknown_terminal_cost_is_only_a_prefix_even_with_numeric_measurements(
        self,
    ):
        fixture = e_fixture()
        row = deepcopy(fixture[2][1])
        row.update(
            attempt_id="parent3",
            operation_id="original/parent3",
            request_sha256=pin("request.parent3"),
            terminal_status="UNKNOWN",
            validity="UNKNOWN",
            candidate_digest=None,
            rolled_back=False,
            rollback_reference=None,
            costs=cost_fixture("training", "parent3-prefix"),
        )
        fixture[2].append(row)
        parent = self.compare(fixture)["runs"]["parent"]
        self.assertEqual(parent["cost_totals"], dict.fromkeys(COST_UNITS))
        self.assertEqual(
            parent["cost_known_lower_bounds"], dict.fromkeys(COST_UNITS, 4.0)
        )
        self.assertEqual(parent["reported_rollback_bounds"], [1 / 3, 2 / 3])

    def test_complete_accounting_is_still_descriptive_and_not_efficacy_evidence(self):
        fixture = e_fixture()
        row = deepcopy(fixture[2][1])
        row.update(
            attempt_id="parent3",
            operation_id="original/parent3",
            request_sha256=pin("request.parent3"),
            candidate_digest=pin("candidate.parent3"),
            rolled_back=False,
            rollback_reference=None,
        )
        fixture[2].append(row)
        result = self.compare(fixture)
        self.assertEqual(
            (
                result["status"],
                result["scientific_efficacy_qualified"],
                result["cost_provenance_verified"],
            ),
            ("DESCRIPTIVE_COMPLETE", False, False),
        )
        self.assertAlmostEqual(
            result["paired_contrasts"][0]["net_improvement_child_minus_parent"], 0.2
        )

    def test_rolled_back_candidate_cannot_remain_final_gain(self):
        fixture = e_fixture()
        child = next(row for row in fixture[2] if row["attempt_id"] == "child1")
        child.update(
            rolled_back=True, rollback_reference=pin("original-child-rollback")
        )
        with self.assertRaisesRegex(
            ACEValidationError, "FINAL_CANDIDATE_WAS_ROLLED_BACK"
        ):
            self.compare(fixture)


class ScalarAndIdentityChecks(unittest.TestCase):
    def test_architecture_and_composition_do_not_coerce_boolean_numbers(self):
        for bad in (True, float("nan"), [], " "):
            with self.subTest(value=repr(bad)):
                arms, registry = a_fixture()
                arms[0]["resources"]["memory_bytes"] = bad
                with self.assertRaises(ACEValidationError):
                    assess_a_capabilities(
                        arms, registry, source_commit="a" * 40, source_tree="b" * 40
                    )
                manifest = manifest_fixture()
                manifest["components"]["A"]["rank"] = bad
                with self.assertRaises(ACEValidationError):
                    validate_composition_manifest(manifest)
        for bad in (True, "0" * 64, "sha256:not-a-digest"):
            manifest = manifest_fixture()
            manifest["bundle_digest"] = bad
            with self.assertRaises(ACEValidationError):
                validate_composition_manifest(manifest)

    def test_owner_binding_does_not_accept_bad_digest_or_truthy_verification(self):
        expected, records = next_use_fixture()
        expected["selection_digest"] = True
        with self.assertRaisesRegex(ACEValidationError, "NEXT_USE_IDENTITY"):
            check_next_use(expected, "original/journal/receipt")
        expected, records = next_use_fixture()
        with self.assertRaisesRegex(ACEValidationError, "AUTHENTICATION_REJECTED"):
            check_next_use(
                expected,
                "original/journal/receipt",
                read_original=lambda kind, ref: records.get((kind, ref)),
                verify_owner=lambda *_args: 1,
            )

    def test_costs_and_evaluator_scalars_are_strict(self):
        for bad in (True, float("nan"), float("inf"), 10**1000):
            with self.subTest(value=repr(bad)[:30]):
                fixture = e_fixture()
                fixture[2][0]["costs"]["training"]["values"]["cpu_seconds"] = bad
                with self.assertRaisesRegex(ACEValidationError, "INVALID_COST"):
                    compare_improvers(*fixture[:3])
        plan, registry, rows, evaluations = e_fixture()
        with self.assertRaisesRegex(ACEValidationError, "AUTHENTICATION_REJECTED"):
            compare_improvers(
                plan,
                registry,
                rows,
                read_evaluation=lambda kind, ref: evaluations.get((kind, ref)),
                verify_evaluation=lambda *_args: 1,
            )


if __name__ == "__main__":
    unittest.main()
