import hashlib
import unittest

from stem_transfer_cell_artifact import (
    ARM_ORDER,
    CellArtifactV1,
    ContractError,
    ModalityEnvelopeV1,
    ParameterLedgerV1,
    ResourceCostV1,
    SplitGateV1,
    StemManifestV1,
    System2CandidateV1,
    System2IntervalGateV1,
    TransferCaseV1,
    TransferMatrixV1,
    build_four_condition_plan,
    canonical_json,
    content_digest,
    manifest_digest,
    pareto_frontier,
    propose_split,
    utility,
    validate_no_model_visible_gold,
)


def digest(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


STEM = StemManifestV1(
    stem_id="stem.shared.v1",
    stem_digest=digest("stem"),
    tokenizer_digest=digest("tokenizer"),
    preprocessor_digest=digest("preprocessor"),
    adapter_basis_digest=digest("basis"),
    hidden_width=1024,
    modality_projectors=("audio", "image", "text", "video"),
)

PARENT = CellArtifactV1(
    cell_id="cell.reasoning.v1",
    parent_cell_id=None,
    stem_digest=STEM.stem_digest,
    adapter_basis_digest=STEM.adapter_basis_digest,
    adapter_rank=32,
    layer_mask=(4, 8, 12),
    head_digest=digest("head"),
    memory_schema_digest=digest("memory"),
    state_namespace="state.reasoning.v1",
    objective_digest=digest("objective"),
)


class ContractTests(unittest.TestCase):
    def test_manifest_is_content_addressable(self):
        self.assertEqual(manifest_digest(STEM), content_digest(STEM.to_dict()))
        self.assertEqual(canonical_json({"b": 1, "a": 2}), '{"a":2,"b":1}')

    def test_manifest_rejects_mutable_policy(self):
        with self.assertRaises(ContractError):
            StemManifestV1(**{**STEM.__dict__, "freeze_policy": "mutable"})

    def test_cell_rejects_runtime_mutation(self):
        with self.assertRaises(ContractError):
            CellArtifactV1(**{**PARENT.__dict__, "current_run_mutation": True})

    def test_cell_rejects_authority_minting(self):
        with self.assertRaises(ContractError):
            CellArtifactV1(**{**PARENT.__dict__, "authority": ("production_activation",)})

    def test_transfer_matrix_requires_one_frozen_stem(self):
        case = TransferCaseV1("task.a", "text", STEM.stem_digest, digest("source"), 0.8, 10, 20, 1)
        matrix = TransferMatrixV1("matrix.v1", STEM, (case,), digest("budget"))
        self.assertEqual(matrix.cases[0].stem_digest, STEM.stem_digest)
        other = TransferCaseV1("task.b", "image", digest("other-stem"), digest("source2"), 0.8, 10, 20, 1)
        with self.assertRaises(ContractError):
            TransferMatrixV1("matrix.bad", STEM, (case, other), digest("budget"))

    def test_transfer_matrix_requires_independent_source_policy(self):
        case = TransferCaseV1("task.a", "text", STEM.stem_digest, digest("source"), 0.8, 10, 20, 1)
        with self.assertRaises(ContractError):
            TransferMatrixV1("matrix.bad", STEM, (case,), digest("budget"), "same_training_source")

    def test_pareto_frontier_is_deterministic(self):
        cases = (
            TransferCaseV1("task.slow", "text", STEM.stem_digest, digest("a"), 0.9, 100, 100, 100),
            TransferCaseV1("task.fast", "text", STEM.stem_digest, digest("b"), 0.89, 10, 10, 10),
            TransferCaseV1("task.bad", "text", STEM.stem_digest, digest("c"), 0.80, 100, 100, 100),
        )
        self.assertEqual(tuple(c.task_id for c in pareto_frontier(cases)), ("task.fast", "task.slow"))

    def test_utility_penalizes_resource_cost(self):
        case = TransferCaseV1("task.a", "text", STEM.stem_digest, digest("a"), 0.8, 10, 20, 3, 0.1)
        self.assertAlmostEqual(utility(case, flop_penalty=0.01), 0.7)

    def test_parameter_ledger_separates_logical_and_active(self):
        ledger = ParameterLedgerV1(100, 10, 30, 8, 4, 2, logical_cells=100, active_cells=2)
        self.assertEqual(ledger.logical_params, 146)
        self.assertEqual(ledger.active_params, 124)

    def test_parameter_ledger_rejects_active_above_resident(self):
        with self.assertRaises(ContractError):
            ParameterLedgerV1(1, 1, 2, 3, 0, 0, 1, 1)

    def test_four_condition_reader_plan_hides_gold(self):
        plan = build_four_condition_plan(
            task_id="reader.task",
            question="Which option is supported?",
            options=("a", "b"),
            source_evidence="source quote",
            distractor_evidence="distractor quote",
            withheld_evidence="withheld quote",
            evaluator_gold="a",
        )
        validate_no_model_visible_gold(plan)
        self.assertEqual(tuple(plan["arms"]), ARM_ORDER)
        self.assertNotIn("gold", plan["model_requests"][0])
        self.assertEqual(plan["evaluator"]["gold"], "a")

    def test_reader_plan_rejects_gold_leak(self):
        plan = build_four_condition_plan(
            task_id="reader.task",
            question="q",
            options=("a",),
            source_evidence="s",
            distractor_evidence="d",
            withheld_evidence="w",
            evaluator_gold="a",
        )
        bad = dict(plan)
        bad["model_requests"] = ({"gold": "a"},)
        with self.assertRaises(ContractError):
            validate_no_model_visible_gold(bad)

    def test_reader_validator_rejects_missing_or_undeclared_requests(self):
        plan = build_four_condition_plan(
            task_id="reader.task",
            question="q",
            options=("a",),
            source_evidence="s",
            distractor_evidence="d",
            withheld_evidence="w",
            evaluator_gold="a",
        )
        missing = dict(plan)
        missing["model_requests"] = ()
        with self.assertRaises(ContractError):
            validate_no_model_visible_gold(missing)
        undeclared = dict(plan)
        undeclared["model_requests"] = tuple({**request, "nested": {"gold": "a"}} for request in plan["model_requests"])
        with self.assertRaises(ContractError):
            validate_no_model_visible_gold(undeclared)

    def test_reader_validator_rejects_wrong_task_or_duplicate_arm(self):
        plan = build_four_condition_plan(
            task_id="reader.task",
            question="q",
            options=("a",),
            source_evidence="s",
            distractor_evidence="d",
            withheld_evidence="w",
            evaluator_gold="a",
        )
        bad_task = dict(plan)
        bad_task["model_requests"] = ({**plan["model_requests"][0], "task_id": "other.task"}, *plan["model_requests"][1:])
        with self.assertRaises(ContractError):
            validate_no_model_visible_gold(bad_task)
        duplicate = dict(plan)
        duplicate["model_requests"] = tuple({**request, "arm": "none"} for request in plan["model_requests"])
        with self.assertRaises(ContractError):
            validate_no_model_visible_gold(duplicate)

    def test_split_gate_passes_only_with_future_lower_bound(self):
        gate = SplitGateV1(0.82, 0.80, 0.01, 0.02, 0.001, 1, 1, 0)
        proposal = propose_split(PARENT, child_id="cell.reasoning.v2", failure_cluster="long_horizon", gate=gate)
        self.assertEqual(proposal.disposition, "accept_next_snapshot")
        self.assertEqual(proposal.child.fallback_cell_id, PARENT.cell_id)
        self.assertEqual(proposal.child.generation, PARENT.generation + 1)
        self.assertFalse(proposal.child.current_run_mutation)

    def test_split_gate_holds_on_reader_insufficiency(self):
        gate = SplitGateV1(0.95, 0.80, 0.01, 0.02, 0.001, 1, 1, 0, reader_sufficient=False)
        proposal = propose_split(PARENT, child_id="cell.reasoning.v2", failure_cluster="reader", gate=gate)
        self.assertEqual(proposal.disposition, "hold")
        self.assertIn("reader_evidence_insufficient", proposal.gate.reasons())

    def test_split_gate_holds_on_regression_or_ood(self):
        gate = SplitGateV1(0.90, 0.80, 0.03, 0.02, 0.001, 1, 1, 0)
        self.assertEqual(propose_split(PARENT, child_id="cell.reasoning.v2", failure_cluster="regression", gate=gate).disposition, "hold")
        gate = SplitGateV1(0.90, 0.80, 0.01, 0.02, 0.005, 1, 1, 0)
        self.assertEqual(propose_split(PARENT, child_id="cell.reasoning.v3", failure_cluster="ood", gate=gate).disposition, "hold")

    def test_split_child_uses_new_state_namespace(self):
        gate = SplitGateV1(0.82, 0.80, 0.01, 0.02, 0.001, 1, 1, 0)
        proposal = propose_split(PARENT, child_id="cell.reasoning.v2", failure_cluster="memory", gate=gate)
        self.assertNotEqual(proposal.parent.state_namespace, proposal.child.state_namespace)
        self.assertEqual(proposal.child.head_digest, proposal.parent.head_digest)

    def test_split_proposal_requires_parent_fallback_and_zero_delta(self):
        gate = SplitGateV1(0.82, 0.80, 0.01, 0.02, 0.001, 1, 1, 0)
        child = CellArtifactV1(
            cell_id="cell.reasoning.v2",
            parent_cell_id=PARENT.cell_id,
            stem_digest=PARENT.stem_digest,
            adapter_basis_digest=PARENT.adapter_basis_digest,
            adapter_rank=PARENT.adapter_rank,
            layer_mask=PARENT.layer_mask,
            head_digest=PARENT.head_digest,
            memory_schema_digest=PARENT.memory_schema_digest,
            state_namespace="state.reasoning.v1.split.v2",
            objective_digest=PARENT.objective_digest,
            generation=1,
            fallback_cell_id=None,
        )
        from stem_transfer_cell_artifact import SplitProposalV1
        with self.assertRaises(ContractError):
            SplitProposalV1(PARENT, child, gate, "accept_next_snapshot", "memory")

    def test_split_acceptance_cannot_ignore_a_failed_gate(self):
        gate = SplitGateV1(0.70, 0.80, 0.01, 0.02, 0.001, 1, 1, 0)
        with self.assertRaises(ContractError):
            # Direct construction demonstrates the accept gate is enforced.
            from stem_transfer_cell_artifact import SplitProposalV1
            child = CellArtifactV1(
                cell_id="cell.reasoning.v2",
                parent_cell_id=PARENT.cell_id,
                stem_digest=PARENT.stem_digest,
                adapter_basis_digest=PARENT.adapter_basis_digest,
                adapter_rank=PARENT.adapter_rank,
                layer_mask=PARENT.layer_mask,
                head_digest=PARENT.head_digest,
                memory_schema_digest=PARENT.memory_schema_digest,
                state_namespace="state.reasoning.v1.split.v2",
                objective_digest=PARENT.objective_digest,
                generation=1,
                fallback_cell_id=PARENT.cell_id,
            )
            SplitProposalV1(PARENT, child, gate, "accept_next_snapshot", "bad")

    def test_modality_envelope_binds_raw_feature_and_projector(self):
        envelope = ModalityEnvelopeV1("video", STEM.stem_digest, digest("raw"), digest("feature"), digest("projector"), 384, 64, temporal_span_ms=1000)
        self.assertTrue(envelope.readonly)
        with self.assertRaises(ContractError):
            ModalityEnvelopeV1("audio", STEM.stem_digest, digest("raw"), digest("feature"), digest("projector"), 384, 64)

    def test_modality_envelope_rejects_mutable_or_invalid_region_metadata(self):
        with self.assertRaises(ContractError):
            ModalityEnvelopeV1("text", STEM.stem_digest, digest("raw"), digest("feature"), digest("projector"), 384, 1, region_count=1)
        with self.assertRaises(ContractError):
            ModalityEnvelopeV1("text", STEM.stem_digest, digest("raw"), digest("feature"), digest("projector"), 384, 1, readonly=False)
        with self.assertRaises(ContractError):
            ModalityEnvelopeV1("text", STEM.stem_digest, digest("raw"), digest("feature"), digest("projector"), 384, 1, readonly="false")
        with self.assertRaises(ContractError):
            ModalityEnvelopeV1("image", STEM.stem_digest, digest("raw"), digest("feature"), digest("projector"), 384, 1, temporal_span_ms=10)

    def _system2_cost(self, scale):
        return ResourceCostV1(10 * scale, 5 * scale, 2 * scale, 1 * scale, 1 * scale, 1 * scale, 1 * scale)

    def test_system2_interval_gate_requires_unique_dominance(self):
        candidates = (
            System2CandidateV1("cell.a", STEM.stem_digest, digest("objective"), 100, 101, self._system2_cost(1), digest("evidence-a")),
            System2CandidateV1("cell.b", STEM.stem_digest, digest("objective"), 70, 71, self._system2_cost(1), digest("evidence-b")),
        )
        advisory = System2IntervalGateV1(candidates).advisory()
        self.assertEqual(advisory["decision"], "ADVISORY_SELECT")
        self.assertEqual(advisory["candidate_id"], "cell.a")
        self.assertEqual(advisory["evaluator_authority"], "DENY_ALL")

    def test_system2_interval_overlap_is_no_go(self):
        candidates = (
            System2CandidateV1("cell.a", STEM.stem_digest, digest("objective"), 100, 110, self._system2_cost(1), digest("evidence-a")),
            System2CandidateV1("cell.b", STEM.stem_digest, digest("objective"), 100, 110, self._system2_cost(1), digest("evidence-b")),
        )
        self.assertEqual(System2IntervalGateV1(candidates).advisory()["decision"], "NO_GO")

    def test_system2_cost_is_fully_charged(self):
        cost = self._system2_cost(1)
        self.assertEqual(cost.total_units, 21)
        with self.assertRaises(ContractError):
            System2CandidateV1("cell.a", STEM.stem_digest, digest("objective"), 1, 2, cost, digest("evidence"), model_efficacy_measured=True)

    def test_system2_accepts_negative_net_utility_intervals(self):
        cost = self._system2_cost(1)
        candidate = System2CandidateV1("cell.a", STEM.stem_digest, digest("objective"), -5, -4, cost, digest("evidence"))
        self.assertLess(candidate.net_ucb, 0)

    def test_system2_rejects_non_boolean_feasibility(self):
        with self.assertRaises(ContractError):
            System2CandidateV1("cell.a", STEM.stem_digest, digest("objective"), 1, 2, self._system2_cost(1), digest("evidence"), feasible="false")


if __name__ == "__main__":
    unittest.main()
