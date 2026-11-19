"""Protocol-only tests for the prospective equal-budget transfer plan."""

from pathlib import Path
import hashlib
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neuron_shared_encoder.prospective_plan import (  # noqa: E402
    CandidateArmV1,
    ProspectiveCaseV1,
    ProspectiveEqualBudgetPlanV1,
    ProspectivePlanError,
    READER_ARMS,
    REQUIRED_CANDIDATES,
    ReaderDesignV1,
    ResourceBudgetV1,
    ResourceCostV1,
    ResourceReceiptV1,
    build_system2_interval_gate,
    reader_request_digest,
)


def digest(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


STEM = digest("shared-stem")
OTHER_STEM = digest("teacher-stem")
OBJECTIVE = digest("fixed-objective")
BUDGET = digest("matched-budget")
COST_WEIGHTS = digest("cost-weights")
MANIFEST = digest("reader-manifest")
SOURCE = digest("future-source")
OOD_SOURCE = digest("ood-source")
LABELS = digest("held-labels")
MODEL = digest("pinned-model")
GIT_BLOB = "1" * 40


def budget() -> ResourceBudgetV1:
    return ResourceBudgetV1(BUDGET, COST_WEIGHTS, 8, 4096, 1000.0, 200.0, 50.0, 10.0)


def reader() -> ReaderDesignV1:
    return ReaderDesignV1(MANIFEST, SOURCE, task_count=2)


def candidate(candidate_id: str) -> CandidateArmV1:
    if candidate_id == "shared_head":
        family, rank, cells, control, stem, gate, reference = "shared_head", 0, 1, False, STEM, True, False
    elif candidate_id == "split_head":
        family, rank, cells, control, stem, gate, reference = "split_head", 0, 4, False, STEM, True, False
    elif candidate_id.startswith("lora_r"):
        family, rank, cells, control, stem, gate, reference = "lora", int(candidate_id[-1]), 1, False, STEM, True, False
    elif candidate_id == "full_fork":
        family, rank, cells, control, stem, gate, reference = "full_fork", 0, 1, True, OTHER_STEM, False, True
    elif candidate_id == "no_change_teacher":
        family, rank, cells, control, stem, gate, reference = "baseline", 0, 1, True, OTHER_STEM, False, True
    else:
        family, rank, cells, control, stem, gate, reference = "baseline", 0, 1, True, STEM, True, False
    return CandidateArmV1(
        candidate_id=candidate_id,
        family=family,
        stem_digest=stem,
        adapter_digest=digest(candidate_id + ":adapter"),
        head_digest=digest(candidate_id + ":head"),
        objective_digest=OBJECTIVE,
        budget_digest=BUDGET,
        resident_params=1000 + len(candidate_id),
        active_params=100 + len(candidate_id),
        cell_count=cells,
        adapter_rank=rank,
        shared_stem_frozen=stem == STEM,
        control=control,
        gate_eligible=gate,
        reference_only=reference,
    )


def plan() -> ProspectiveEqualBudgetPlanV1:
    return ProspectiveEqualBudgetPlanV1(
        plan_id="prospective.text.p0",
        shared_stem_digest=STEM,
        objective_digest=OBJECTIVE,
        budget=budget(),
        reader=reader(),
        candidates=tuple(candidate(identifier) for identifier in REQUIRED_CANDIDATES),
    )


def resource(candidate_id: str, *, evidence_class: str = "REAL_SHADOW", calls: int = 8) -> ResourceReceiptV1:
    return ResourceReceiptV1(candidate_id, BUDGET, evidence_class, calls, 100, 100.0, 100.0, 10.0, 5.0, True)


def case(candidate_id: str, arm: str, *, task_id: str = "task_a", source: str = SOURCE, source_split: str = "future", status: str = "COMPLETE", evidence_class: str = "REAL_SHADOW") -> ProspectiveCaseV1:
    state = {"question": "q", "repository_source": "docs/source.md", "source_excerpt_untrusted": "evidence:" + arm}
    questions = {"answer": {"criteria": {"A": "a", "B": "b", "C": "c", "D": "d", "UNKNOWN": "unknown"}}}
    request = reader_request_digest(task_id=task_id, reader_arm=arm, source_path="docs/source.md", state=state, questions=questions, manifest_sha256=MANIFEST)
    missing = tuple(sorted(("label_digest", "model_digest", "quality", "quality_lcb", "quality_ucb", "resource", "resident_params", "active_params"))) if status == "INCOMPLETE" else ()
    return ProspectiveCaseV1(
        case_id=f"{candidate_id}.{task_id}.{source_split}.0.{arm}",
        candidate_id=candidate_id,
        task_id=task_id,
        reader_arm=arm,
        source_split=source_split,
        source_digest=source,
        source_blob_digest=GIT_BLOB if source_split == "future" else "2" * 40,
        request_digest=request,
        reader_manifest_digest=MANIFEST,
        budget_digest=BUDGET,
        replicate=0,
        evidence_class=evidence_class if status == "COMPLETE" else "INCOMPLETE",
        status=status,
        label_digest=None if status == "INCOMPLETE" else LABELS,
        model_digest=None if status == "INCOMPLETE" else MODEL,
        quality=None if status == "INCOMPLETE" else 0.8,
        quality_lcb=None if status == "INCOMPLETE" else 0.7,
        quality_ucb=None if status == "INCOMPLETE" else 0.9,
        resource=None if status == "INCOMPLETE" else resource(candidate_id, evidence_class=evidence_class),
        resident_params=None if status == "INCOMPLETE" else 1000,
        active_params=None if status == "INCOMPLETE" else 100,
        missing_fields=missing,
    )


def complete_cases() -> list[ProspectiveCaseV1]:
    """Build the minimum complete future/OOD matrix for the two-task Reader."""
    return [
        case(
            candidate_id,
            arm,
            task_id=task_id,
            source=SOURCE if source_split == "future" else OOD_SOURCE,
            source_split=source_split,
        )
        for candidate_id in REQUIRED_CANDIDATES
        for source_split in ("future", "ood")
        for task_id in ("task_a", "task_b")
        for arm in READER_ARMS
    ]


class ProspectivePlanTests(unittest.TestCase):
    def test_complete_required_plan_is_shadow_only_and_equal_budgeted(self):
        item = plan()
        self.assertEqual(item.expected_calls, 9 * 8)
        self.assertEqual(item.status, "SHADOW_ONLY")
        self.assertFalse(item.selection_authority)
        self.assertEqual(item.to_dict()["schema"], "hepta.prospective.equal-budget-plan.v1")

    def test_missing_candidate_is_rejected(self):
        with self.assertRaises(ProspectivePlanError):
            ProspectiveEqualBudgetPlanV1(
                "prospective.text.p0", STEM, OBJECTIVE, budget(), reader(),
                tuple(candidate(identifier) for identifier in REQUIRED_CANDIDATES[:-1]),
            )

    def test_multi_presentation_is_deferred_until_case_schema_v2(self):
        with self.assertRaises(ProspectivePlanError):
            ReaderDesignV1(MANIFEST, SOURCE, task_count=2, presentations=4)

    def test_teacher_and_full_fork_are_reference_only(self):
        with self.assertRaises(ProspectivePlanError):
            CandidateArmV1("full_fork", "full_fork", OTHER_STEM, digest("a"), digest("h"), OBJECTIVE, BUDGET, 1000, 100, 1, 0, False, True, True, False)

    def test_gate_candidates_share_stem_and_objective(self):
        bad = list(plan().candidates)
        bad[1] = CandidateArmV1("split_head", "split_head", OTHER_STEM, digest("a"), digest("h"), digest("bad-objective"), BUDGET, 1000, 100, 2, 0, True, False, True, False)
        with self.assertRaises(ProspectivePlanError):
            ProspectiveEqualBudgetPlanV1("prospective.text.p0", STEM, OBJECTIVE, budget(), reader(), tuple(bad))

    def test_resource_receipts_require_equal_calls_and_real_shadow(self):
        item = plan()
        receipts = tuple(resource(identifier) for identifier in REQUIRED_CANDIDATES)
        item.validate_resource_receipts(receipts)
        with self.assertRaises(ProspectivePlanError):
            item.validate_resource_receipts(tuple(resource(identifier, calls=7) for identifier in REQUIRED_CANDIDATES))
        with self.assertRaises(ProspectivePlanError):
            item.validate_resource_receipts(tuple(resource(identifier, evidence_class="SYNTHETIC_SMOKE") for identifier in REQUIRED_CANDIDATES))

    def test_four_reader_arms_are_required_for_each_candidate(self):
        item = plan()
        cases = complete_cases()
        item.validate_cases(cases)
        with self.assertRaises(ProspectivePlanError):
            item.validate_cases(cases[:-1])

    def test_source_splits_cannot_overlap(self):
        item = plan()
        cases = complete_cases()
        # Keep the matrix cardinality intact while making one OOD source reuse
        # the future source identity.
        cases[-1] = case("no_change_teacher", "full", task_id="task_b", source=SOURCE, source_split="ood")
        with self.assertRaises(ProspectivePlanError):
            item.validate_cases(cases)

    def test_incomplete_case_cannot_enter_matrix(self):
        item = plan()
        cases = complete_cases()
        cases[-1] = case("no_change_teacher", "full", task_id="task_b", source=OOD_SOURCE, source_split="ood", status="INCOMPLETE")
        with self.assertRaises(ProspectivePlanError):
            item.validate_cases(cases)

    def test_request_digest_rejects_gold_key(self):
        with self.assertRaises(ProspectivePlanError):
            reader_request_digest(
                task_id="task_a", reader_arm="full", source_path="docs/source.md",
                state={"gold": "A"}, questions={}, manifest_sha256=MANIFEST,
            )

    def test_request_digest_changes_with_arm_and_excludes_gold(self):
        state = {"question": "q", "repository_source": "docs/source.md"}
        questions = {"answer": {"criteria": {"A": "a"}}}
        one = reader_request_digest(task_id="task_a", reader_arm="none", source_path="docs/source.md", state=state, questions=questions, manifest_sha256=MANIFEST)
        two = reader_request_digest(task_id="task_a", reader_arm="full", source_path="docs/source.md", state=state, questions=questions, manifest_sha256=MANIFEST)
        self.assertNotEqual(one, two)

    def test_system2_interval_overlap_is_no_go(self):
        item = plan()
        gate_ids = tuple(candidate.candidate_id for candidate in item.candidates if candidate.gate_eligible)
        intervals = {candidate_id: (10.0, 20.0) for candidate_id in gate_ids}
        costs = {
            candidate_id: ResourceCostV1(
                encoder_flops=0.0,
                cell_flops=0.0,
                controller_flops=0.0,
                verification_flops=0.0,
                latency_ms=0.0,
                memory_bytes=0.0,
                energy_mj=0.0,
            )
            for candidate_id in gate_ids
        }
        evidence = {candidate_id: digest("evidence:" + candidate_id) for candidate_id in gate_ids}
        evidence_classes = {candidate_id: "REAL_SHADOW" for candidate_id in gate_ids}
        advisory = build_system2_interval_gate(item, intervals, costs, evidence, evidence_classes, complete_cases()).advisory()
        self.assertEqual(advisory["decision"], "NO_GO")
        self.assertIsNone(advisory["candidate_id"])
        self.assertFalse(advisory["model_efficacy_measured"])
        self.assertEqual(advisory["evaluator_authority"], "DENY_ALL")

    def test_system2_unique_interval_dominance_is_advisory_only(self):
        item = plan()
        gate_ids = tuple(candidate.candidate_id for candidate in item.candidates if candidate.gate_eligible)
        intervals = {
            candidate_id: ((100.0, 120.0) if candidate_id == "split_head" else (0.0, 10.0))
            for candidate_id in gate_ids
        }
        costs = {
            candidate_id: ResourceCostV1(
                encoder_flops=0.0,
                cell_flops=0.0,
                controller_flops=0.0,
                verification_flops=0.0,
                latency_ms=0.0,
                memory_bytes=0.0,
                energy_mj=0.0,
            )
            for candidate_id in gate_ids
        }
        evidence = {candidate_id: digest("evidence:" + candidate_id) for candidate_id in gate_ids}
        evidence_classes = {candidate_id: "REAL_SHADOW" for candidate_id in gate_ids}
        gate = build_system2_interval_gate(item, intervals, costs, evidence, evidence_classes, complete_cases())
        advisory = gate.advisory()
        self.assertEqual(advisory["decision"], "ADVISORY_SELECT")
        self.assertEqual(advisory["candidate_id"], "split_head")
        self.assertFalse(advisory["model_efficacy_measured"])
        self.assertEqual(advisory["evaluator_authority"], "DENY_ALL")


if __name__ == "__main__":
    unittest.main()
