"""Reference-only tests for frozen 1+2+7 learning-scope boundaries."""

from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hepta_cells.lineage_policy import (
    COST_AXES,
    LINEAGES,
    CellEnrollment,
    CellRoster,
    ComponentPins,
    LineagePolicyError,
    UpdateEvidence,
    review_update,
)


def pin(number):
    return f"{number:064x}"


def components():
    return ComponentPins(**{
        name: pin(i + 1) for i, name in enumerate((
            "base", "heads", "composition", "encoder", "tokenizer",
            "normalizer", "calibration", "numeric_profile", "output_schema",
            "state_schema", "state_semantics",
        ))
    })


def enrollment(lineage, *, scope=None, kernel=None, name=None, **overrides):
    default_kernels = {
        "PERC": "shared_semantic", "MEM": "shared_semantic",
        "PRED": "stateful_temporal", "CTRL": "stateful_temporal",
        "VERIFY": "shared_semantic", "ACT": "stateful_temporal",
        "LEARN": "deterministic",
    }
    kernel = kernel or default_kernels[lineage]
    c = dict(
        lineage=lineage, kernel=kernel, principal_id="principal-a",
        agent_id="agent-a", cell_id=name or lineage.lower(), run_id="run-a",
        state_owner="original-cell-owner", bundle_digest=pin(120),
        generation=7, components=components(), data_scope="data-allowed",
        feature_share_group="shared-perception" if lineage in {"PERC", "MEM"} else None,
        feature_abi=pin(230) if lineage in {"PERC", "MEM"} else None,
        trainable_scope=scope,
        max_training_steps=12 if scope else 0,
        evaluation_profile=pin(220) if scope else None,
        update_rule=pin(221) if scope else None,
    )
    c.update(overrides)
    return CellEnrollment(**c)


def roster():
    return CellRoster(tuple(enrollment(lineage, scope=(
        "kernel_and_heads" if lineage == "PRED" else
        "heads" if lineage == "VERIFY" else None
    )) for lineage in sorted(LINEAGES)))


def evidence(cell, **overrides):
    c = dict(
        partition=cell.partition, source_bundle=cell.bundle_digest,
        candidate_bundle=pin(121), candidate_generation=cell.generation + 1,
        candidate_components=replace(cell.components, heads=pin(333)),
        training_source=cell.bundle_digest, dataset_digest=pin(201),
        update_rule=cell.update_rule, evaluation_profile=cell.evaluation_profile,
        evaluation_receipt_digest=pin(222), completed_training_steps=4,
        costs={axis: 0.0 for axis in COST_AXES},
    )
    c.update(overrides)
    return UpdateEvidence(**c)


class LineagePolicyTests(unittest.TestCase):
    def test_seven_lineages_two_trainable_kernels_and_no_adoption(self):
        r = roster()
        self.assertEqual({c.lineage for c in r.cells}, LINEAGES)
        self.assertEqual(sum(c.trainable_scope is not None for c in r.cells), 2)
        for lineage in ("PRED", "VERIFY"):
            decision = review_update(r, evidence(next(c for c in r.cells if c.lineage == lineage)))
            self.assertEqual(decision.status, "REVIEW_ONLY")
            self.assertFalse(decision.adoption_authorized)
            self.assertTrue(decision.native_validation_required)
            self.assertTrue(decision.independent_evaluator_required)

    def test_frozen_not_trainable(self):
        r = roster()
        with self.assertRaisesRegex(LineagePolicyError, "frozen"):
            review_update(r, evidence(next(c for c in r.cells if c.lineage == "MEM")))

    def test_coverage_and_duplicate_partition_rejected(self):
        all_cells = roster().cells
        with self.assertRaisesRegex(LineagePolicyError, "seven"):
            CellRoster(all_cells[:-1])
        with self.assertRaisesRegex(LineagePolicyError, "duplicate"):
            CellRoster(all_cells + (all_cells[0],))

    def test_same_lineage_multiple_isolated_instances_allowed(self):
        all_cells = roster().cells
        extension = replace(
            all_cells[1], cell_id="different-mem-instance",
            feature_share_group=None, feature_abi=None,
        )
        out = CellRoster(all_cells + (extension,))
        self.assertEqual(len(out.cells), 8)
        self.assertNotEqual(out.cells[1].partition, extension.partition)

    def test_three_trainable_max_and_limit_cannot_be_relaxed(self):
        base = roster().cells
        candidate = replace(
            next(c for c in base if c.lineage == "PERC"),
            trainable_scope="heads", max_training_steps=8,
            evaluation_profile=pin(220), update_rule=pin(221),
        )
        mixed = tuple(candidate if c.lineage == "PERC" else c for c in base)
        self.assertEqual(sum(c.trainable_scope is not None for c in CellRoster(mixed).cells), 3)
        extra = replace(
            next(c for c in base if c.lineage == "MEM"),
            trainable_scope="heads", max_training_steps=8,
            evaluation_profile=pin(220), update_rule=pin(221),
        )
        with self.assertRaisesRegex(LineagePolicyError, "trainable"):
            CellRoster(tuple(extra if c.lineage == "MEM" else c for c in mixed))
        with self.assertRaisesRegex(LineagePolicyError, "roster"):
            CellRoster(mixed, max_trainable_instances=4)

    def test_semantic_pool_requires_same_real_frozen_bindings(self):
        base = roster().cells
        mem = next(c for c in base if c.lineage == "MEM")
        changed = replace(mem, components=replace(mem.components, encoder=pin(999)))
        with self.assertRaisesRegex(LineagePolicyError, "feature group"):
            CellRoster(tuple(changed if c is mem else c for c in base))
        changed = replace(mem, principal_id="other-principal")
        with self.assertRaisesRegex(LineagePolicyError, "feature group"):
            CellRoster(tuple(changed if c is mem else c for c in base))
        changed = replace(mem, agent_id="other-agent")
        with self.assertRaisesRegex(LineagePolicyError, "feature group"):
            CellRoster(tuple(changed if c is mem else c for c in base))
        changed = replace(mem, data_scope="other-permitted-data")
        with self.assertRaisesRegex(LineagePolicyError, "feature group"):
            CellRoster(tuple(changed if c is mem else c for c in base))
        changed = replace(mem, state_owner="different-owner")
        with self.assertRaisesRegex(LineagePolicyError, "feature group"):
            CellRoster(tuple(changed if c is mem else c for c in base))
        changed = replace(mem, feature_abi=pin(231))
        with self.assertRaisesRegex(LineagePolicyError, "feature group"):
            CellRoster(tuple(changed if c is mem else c for c in base))

    def test_shared_feature_abi_is_explicit_and_not_self_authorizing(self):
        with self.assertRaisesRegex(LineagePolicyError, "feature_abi"):
            enrollment("PERC", feature_abi=None)
        with self.assertRaisesRegex(LineagePolicyError, "feature_abi"):
            enrollment("MEM", feature_abi="0" * 64)
        with self.assertRaisesRegex(LineagePolicyError, "unshared"):
            enrollment("PERC", feature_share_group=None)
        with self.assertRaisesRegex(LineagePolicyError, "unshared"):
            enrollment("CTRL", feature_abi=pin(123))

    def test_frozen_training_budget_type_cannot_be_weakened(self):
        for bad in (False, 0.0, None, "", (), -0.0):
            with self.subTest(value=repr(bad)):
                with self.assertRaisesRegex(LineagePolicyError, "frozen cell"):
                    enrollment("MEM", max_training_steps=bad)
        with self.assertRaisesRegex(LineagePolicyError, "frozen cell"):
            enrollment("MEM", evaluation_profile="")
        with self.assertRaisesRegex(LineagePolicyError, "frozen cell"):
            enrollment("MEM", update_rule="")

    def test_next_generation_must_fit_native_unsigned_u64(self):
        old = roster()
        target = next(c for c in old.cells if c.lineage == "PRED")
        exhausted = replace(target, generation=2**64 - 1)
        r = CellRoster(tuple(exhausted if c is target else c for c in old.cells))
        with self.assertRaisesRegex(LineagePolicyError, "candidate violates"):
            review_update(r, evidence(exhausted, candidate_generation=2**64))
        with self.assertRaisesRegex(LineagePolicyError, "candidate violates"):
            review_update(r, evidence(exhausted, candidate_generation=True))
        self.assertEqual(
            review_update(old, evidence(target)).status, "REVIEW_ONLY"
        )

    def test_temporal_cannot_share_live_feature_pool(self):
        with self.assertRaisesRegex(LineagePolicyError, "semantic features"):
            enrollment("PRED", feature_share_group="shared-perception")

    def test_learn_is_an_original_owner_orchestrator(self):
        with self.assertRaisesRegex(LineagePolicyError, "LEARN orchestrates"):
            enrollment("LEARN", kernel="stateful_temporal", scope="kernel_and_heads")

    def test_invalid_training_scopes_or_missing_evaluator(self):
        with self.assertRaisesRegex(LineagePolicyError, "requested fields"):
            enrollment("VERIFY", scope="kernel_and_heads")
        with self.assertRaisesRegex(LineagePolicyError, "evaluation_profile"):
            enrollment("VERIFY", scope="heads", evaluation_profile=None)
        with self.assertRaisesRegex(LineagePolicyError, "frozen cell"):
            enrollment("MEM", max_training_steps=1)

    def test_no_model_identity_or_zero_digest_bypass(self):
        with self.assertRaisesRegex(LineagePolicyError, "bundle"):
            enrollment("MEM", bundle_digest="0" * 64)
        with self.assertRaisesRegex(LineagePolicyError, "encoder"):
            replace(components(), encoder="0" * 64)
        with self.assertRaisesRegex(LineagePolicyError, "generation"):
            enrollment("MEM", generation=True)

    def test_head_update_cannot_change_encoder_or_numeric_domain(self):
        r = roster()
        c = next(c for c in r.cells if c.lineage == "VERIFY")
        for field in ("encoder", "numeric_profile", "state_semantics", "base", "organ_adapter"):
            with self.subTest(field=field):
                changed = replace(evidence(c).candidate_components, **{field: pin(400)})
                with self.assertRaisesRegex(LineagePolicyError, "frozen"):
                    review_update(r, evidence(c, candidate_components=changed))

    def test_temporal_update_rejects_cell_adapter_or_schema(self):
        r = roster()
        c = next(c for c in r.cells if c.lineage == "PRED")
        for field in ("cell_adapter", "state_schema"):
            with self.subTest(field=field):
                changed = replace(evidence(c).candidate_components, **{field: pin(401)})
                with self.assertRaisesRegex(LineagePolicyError, "frozen"):
                    review_update(r, evidence(c, candidate_components=changed))

    def test_no_update_and_stale_provenance_rejected(self):
        r = roster()
        c = next(c for c in r.cells if c.lineage == "VERIFY")
        for overrides in (
            {"candidate_components": c.components},
            {"candidate_generation": c.generation + 2},
            {"source_bundle": pin(600)},
            {"training_source": pin(600)},
            {"evaluation_profile": pin(600)},
            {"update_rule": pin(600)},
            {"candidate_bundle": c.bundle_digest},
            {"completed_training_steps": 13},
        ):
            with self.subTest(overrides=tuple(overrides)):
                with self.assertRaises(LineagePolicyError):
                    review_update(r, evidence(c, **overrides))

    def test_missing_cost_or_original_evaluation_stays_hold(self):
        r = roster()
        c = next(c for c in r.cells if c.lineage == "VERIFY")
        costs = evidence(c).costs
        costs["resident_byte_seconds"] = None
        result = review_update(r, evidence(c, costs=costs, evaluation_receipt_digest=None))
        self.assertEqual(result.status, "HOLD")
        self.assertEqual(set(result.reasons), {
            "resident_byte_seconds", "original_signed_evaluation",
        })
        self.assertFalse(result.adoption_authorized)

    def test_cost_census_cannot_drop_failures_or_unmeasured_axes(self):
        r = roster()
        c = next(c for c in r.cells if c.lineage == "VERIFY")
        for costs in (
            {},
            dict(evidence(c).costs, training_cpu_seconds=-1.0),
            dict(evidence(c).costs, evaluation_cpu_seconds=float("nan")),
            dict(evidence(c).costs, transport_bytes=True),
        ):
            with self.subTest(costs=costs):
                with self.assertRaises(LineagePolicyError):
                    review_update(r, evidence(c, costs=costs))


if __name__ == "__main__":
    unittest.main()
