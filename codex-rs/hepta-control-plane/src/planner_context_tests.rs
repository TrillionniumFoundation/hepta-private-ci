use pretty_assertions::assert_eq;

use super::*;

fn observed() -> ObservedContextV1<'static> {
    ObservedContextV1 {
        owner_id: StableId::new("actual-state-owner").expect("owner id"),
        body_generation: Generation::new(7).expect("owner generation"),
        source_snapshot_digest: Digest32::of_bytes(b"canonical-read-cut"),
        read_digest: Digest32::of_bytes(b"verified-read"),
        verified_item_count: 2,
        encoded_context: b"verified content",
        maximum_context_bytes: 128,
        observed_at_micros: 100,
        expires_at_micros: 200,
    }
}

#[test]
fn measured_context_is_selected_and_budget_excess_abstains() {
    let read = plan_observed_context(observed()).expect("read plan");
    assert!(read.read_allowed);
    assert_eq!(
        read.evaluation.plan.chosen_plan_digest(),
        Some(read.context_digest)
    );
    assert!(!read.evaluation.plan.authority().grants_any());
    let mut over_budget = observed();
    over_budget.maximum_context_bytes = 1;
    let abstain = plan_observed_context(over_budget).expect("bounded abstain plan");
    assert!(!abstain.read_allowed);
    assert_eq!(
        abstain.evaluation.plan.resource_rejected_candidate_ids(),
        &[StableId::new("read-context").expect("id")]
    );
    assert_eq!(
        abstain.evaluation.plan.chosen_candidate_id(),
        Some(&StableId::new("abstain").expect("id"))
    );
}

#[test]
fn empty_context_never_becomes_a_utility_claim_and_invalid_observations_reject() {
    let mut empty = observed();
    empty.verified_item_count = 0;
    assert!(
        !plan_observed_context(empty)
            .expect("empty context plan")
            .read_allowed
    );
    let mut invalid = observed();
    invalid.expires_at_micros = 100;
    assert!(matches!(
        plan_observed_context(invalid),
        Err(NduPlanningError::Planner(PlannerError::InvalidTime(_)))
    ));
    let mut oversized = observed();
    oversized.verified_item_count = 5;
    assert_eq!(
        plan_observed_context(oversized),
        Err(NduPlanningError::Planner(PlannerError::LimitExceeded(
            "observed_context"
        )))
    );
}

#[test]
fn receipt_binds_actual_bytes_source_and_generation() {
    let original = plan_observed_context(observed()).expect("original plan");
    let mut bytes = observed();
    bytes.encoded_context = b"changed content";
    let mut source = observed();
    source.source_snapshot_digest = Digest32::of_bytes(b"other-read-cut");
    let mut generation = observed();
    generation.body_generation = Generation::new(8).expect("next generation");
    for changed in [bytes, source, generation] {
        let changed = plan_observed_context(changed).expect("changed plan");
        assert_ne!(
            original.evaluation.plan.receipt_digest(),
            changed.evaluation.plan.receipt_digest()
        );
    }
    assert_eq!(
        original,
        plan_observed_context(observed()).expect("deterministic replay")
    );
}
