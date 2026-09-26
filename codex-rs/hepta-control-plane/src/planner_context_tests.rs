use pretty_assertions::assert_eq;

use super::*;

static RECORDS: std::sync::LazyLock<Vec<VerifiedContextRecordV1>> =
    std::sync::LazyLock::new(|| {
        vec![
            VerifiedContextRecordV1 {
                record_id: StableId::new("record-a").expect("record"),
                revision: Revision::new(1).expect("revision"),
                content_digest: Digest32::of_bytes(b"content-a"),
            },
            VerifiedContextRecordV1 {
                record_id: StableId::new("record-b").expect("record"),
                revision: Revision::new(2).expect("revision"),
                content_digest: Digest32::of_bytes(b"content-b"),
            },
        ]
    });

fn observed() -> ObservedContextV1<'static> {
    ObservedContextV1 {
        owner_id: StableId::new("actual-state-owner").expect("owner id"),
        body_generation: Generation::new(7).expect("owner generation"),
        source_snapshot_digest: Digest32::of_bytes(b"canonical-read-cut"),
        read_digest: Digest32::of_bytes(b"verified-read"),
        request_binding_digest: Digest32::of_bytes(b"request-query-ranker-binding"),
        verified_records: &RECORDS,
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
}

#[test]
fn empty_context_never_becomes_a_utility_claim_and_invalid_observations_reject() {
    let mut empty = observed();
    empty.verified_records = &[];
    assert!(
        !plan_observed_context(empty)
            .expect("empty plan")
            .read_allowed
    );
    let mut invalid = observed();
    invalid.expires_at_micros = 100;
    assert!(matches!(
        plan_observed_context(invalid),
        Err(NduPlanningError::Planner(PlannerError::InvalidTime(_)))
    ));
    let mut oversized_records = RECORDS.clone();
    oversized_records.extend(RECORDS.iter().cloned());
    oversized_records.push(VerifiedContextRecordV1 {
        record_id: StableId::new("record-c").expect("record"),
        revision: Revision::new(1).expect("revision"),
        content_digest: Digest32::of_bytes(b"content-c"),
    });
    let mut oversized = observed();
    oversized.verified_records = &oversized_records;
    assert_eq!(
        plan_observed_context(oversized),
        Err(NduPlanningError::Planner(PlannerError::LimitExceeded(
            "observed_context"
        )))
    );
}

#[test]
fn receipt_binds_bytes_records_request_source_and_generation() {
    let original = plan_observed_context(observed()).expect("original plan");
    let mut bytes = observed();
    bytes.encoded_context = b"changed content";
    let mut request = observed();
    request.request_binding_digest = Digest32::of_bytes(b"other request");
    let mut records = RECORDS.clone();
    records[0].content_digest = Digest32::of_bytes(b"changed-record");
    let mut record_change = observed();
    record_change.verified_records = &records;
    let mut source = observed();
    source.source_snapshot_digest = Digest32::of_bytes(b"other-read-cut");
    let mut generation = observed();
    generation.body_generation = Generation::new(8).expect("next generation");
    for changed in [bytes, request, record_change, source, generation] {
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
