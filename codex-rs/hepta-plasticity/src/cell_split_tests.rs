use super::*;
use codex_hepta_types::Generation;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}
fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}
fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn signal(operation: CellSplitOperationV1) -> CellSplitProposalSignalV1 {
    let (predecessor_digest, candidate_digest) = match operation {
        CellSplitOperationV1::Add => (None, Some(digest(b"candidate"))),
        CellSplitOperationV1::Retire => (Some(digest(b"predecessor")), None),
        CellSplitOperationV1::Split
        | CellSplitOperationV1::Merge
        | CellSplitOperationV1::Rewire => {
            (Some(digest(b"predecessor")), Some(digest(b"candidate")))
        }
    };
    CellSplitProposalSignalV1 {
        signal_id: id("signal:cell:1"),
        cell_id: id("cell:1"),
        operation,
        baseline_generation: generation(7),
        candidate_generation: generation(8),
        predecessor_digest,
        candidate_digest,
        evidence_digest: digest(b"evidence"),
        budget: CellSplitBudgetV1 {
            compute_micros: 10,
            memory_bytes: 20,
            storage_bytes: 30,
            network_bytes: 40,
        },
        risk: CellSplitRiskV1 {
            risk_ppm: 10,
            maximum_risk_ppm: 100,
            risk_evidence_digest: digest(b"risk"),
        },
        rollback: CellSplitRollbackV1 {
            predecessor_digest: digest(b"rollback-predecessor"),
            procedure_digest: digest(b"rollback-procedure"),
            timeout_micros: 100,
        },
        guardrails: CellSplitGuardrailsV1 {
            canary: CellSplitCanaryV1 {
                cohort_digest: digest(b"canary"),
                maximum_exposure_ppm: 10_000,
                duration_micros: 100,
            },
            quarantine: CellSplitQuarantineV1 {
                trigger_digest: digest(b"quarantine"),
                duration_micros: 200,
            },
            holdout: CellSplitHoldoutV1 {
                cohort_digest: digest(b"holdout"),
                evaluation_digest: digest(b"holdout-evaluation"),
                minimum_observations: 3,
            },
        },
    }
}

fn request(operation: CellSplitOperationV1) -> CellSplitPlannerRequestV1 {
    CellSplitPlannerRequestV1::new(
        id("plan:cell:1"),
        id("generator:1"),
        id("evaluator:1"),
        id("reviewer:1"),
        id("operator:1"),
        generation(7),
        Some(signal(operation)),
    )
}

#[test]
fn planner_emits_all_operations_and_no_change_competitor() {
    for operation in [
        CellSplitOperationV1::Add,
        CellSplitOperationV1::Split,
        CellSplitOperationV1::Merge,
        CellSplitOperationV1::Rewire,
        CellSplitOperationV1::Retire,
    ] {
        let plan = plan_cell_split_v1(request(operation)).expect("valid plan");
        assert_eq!(plan.candidates.len(), 2);
        assert!(plan.no_change_candidate().is_some());
        assert_eq!(plan.change_candidate().and_then(|candidate| candidate.operation), Some(operation));
        assert_eq!(plan.status, CellSplitPlanStatusV1::RequiresIndependentReview);
        assert!(!plan.authority.grants_any());
        verify_cell_split_v1(&plan).expect("deterministic verification");
    }
}

#[test]
fn planner_is_deterministic_and_does_not_select() {
    let left = plan_cell_split_v1(request(CellSplitOperationV1::Split)).expect("left");
    let right = plan_cell_split_v1(request(CellSplitOperationV1::Split)).expect("right");
    assert_eq!(left, right);
    assert!(cell_split_generator_signing_payload_v1(&left)
        .windows(left.plan_digest.as_array().len())
        .any(|window| window == &left.plan_digest.as_array()[..]));
}

#[test]
fn planner_rejects_missing_signal_evidence_rollback_and_holdout() {
    let mut missing_signal = request(CellSplitOperationV1::Add);
    missing_signal.signal = None;
    assert_eq!(
        plan_cell_split_v1(missing_signal),
        Err(CellSplitPlannerErrorV1::MissingSignal)
    );

    let mut missing_evidence = request(CellSplitOperationV1::Add);
    missing_evidence
        .signal
        .as_mut()
        .expect("signal")
        .evidence_digest = Digest32::ZERO;
    assert_eq!(
        plan_cell_split_v1(missing_evidence),
        Err(CellSplitPlannerErrorV1::MissingEvidence("signal"))
    );

    let mut missing_rollback = request(CellSplitOperationV1::Add);
    missing_rollback
        .signal
        .as_mut()
        .expect("signal")
        .rollback
        .procedure_digest = Digest32::ZERO;
    assert_eq!(
        plan_cell_split_v1(missing_rollback),
        Err(CellSplitPlannerErrorV1::MissingRollback)
    );

    let mut missing_holdout = request(CellSplitOperationV1::Add);
    missing_holdout
        .signal
        .as_mut()
        .expect("signal")
        .guardrails
        .holdout
        .minimum_observations = 0;
    assert_eq!(
        plan_cell_split_v1(missing_holdout),
        Err(CellSplitPlannerErrorV1::MissingHoldout)
    );
}

#[test]
fn planner_rejects_stale_generation_and_generator_selection() {
    let mut stale = request(CellSplitOperationV1::Merge);
    stale.current_generation = generation(6);
    assert_eq!(
        plan_cell_split_v1(stale),
        Err(CellSplitPlannerErrorV1::StaleGeneration)
    );

    let mut selected = request(CellSplitOperationV1::Merge);
    selected.generator_selected_candidate_id = Some(id("cell-candidate:chosen"));
    assert_eq!(
        plan_cell_split_v1(selected),
        Err(CellSplitPlannerErrorV1::GeneratorSelectionForbidden)
    );
}

#[test]
fn planner_rejects_non_independent_roles_and_tampering() {
    let mut roles = request(CellSplitOperationV1::Rewire);
    roles.reviewer_id = roles.evaluator_id.clone();
    assert_eq!(
        plan_cell_split_v1(roles),
        Err(CellSplitPlannerErrorV1::IndependentIdentityRequired)
    );

    let mut tampered = plan_cell_split_v1(request(CellSplitOperationV1::Retire)).expect("plan");
    tampered.candidates[0].evidence_digest = digest(b"tampered");
    assert_eq!(
        verify_cell_split_v1(&tampered),
        Err(CellSplitPlannerErrorV1::CandidateSetMismatch)
    );
}
