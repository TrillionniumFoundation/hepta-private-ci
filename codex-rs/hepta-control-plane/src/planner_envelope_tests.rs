use super::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use crate::NduPlanEvaluationInputV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlanningRequestV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;
use crate::bind_ndu_plan_evaluation_v1;
use crate::collect_snapshot;
use crate::prepare_plan;

fn digest(value: &str) -> Digest32 { Digest32::of_bytes(value.as_bytes()) }
fn id(value: &str) -> StableId { StableId::new(value).expect("fixture ID") }

fn fixture(name: &str) -> (GlobalStateSnapshotV1, PreparedPlanInputV1, NduPlanEvaluationV1, FeasiblePlanReceiptV1) {
    let generation = Generation::new(1).expect("generation");
    let snapshot = collect_snapshot(SnapshotRequestV1 {
        objective_digest: digest("objective"),
        body_generation: generation,
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        snapshot_policy_digest: digest("snapshot-policy"),
        collected_at_micros: 100,
        maximum_owner_age_micros: 100,
        expires_at_micros: 200,
        required_owner_ids: vec![id("owner")],
    }, vec![OwnerSummaryV1 {
        owner_id: id("owner"),
        revision: Revision::new(1).expect("revision"),
        objective_digest: digest("objective"),
        body_generation: generation,
        configuration_digest: digest("configuration"),
        observed_at_micros: 100,
        expires_at_micros: 200,
        readiness: OwnerReadinessV1::Ready,
        source_frontier_digest: digest("owner-frontier"),
        support_digest: digest("support"),
    }]).expect("snapshot");
    let prepared = prepare_plan(&snapshot, PlanningRequestV1 {
        plan_id: id(name),
        now_micros: 100,
        deadline_micros: 200,
        evaluation_policy_digest: digest("evaluation-policy"),
        resource_profile_digest: digest("resources"),
        candidates: vec![PlanCandidateV1 {
            candidate_id: id("abstain"),
            operation_id: id("abstain"),
            plan_digest: digest("abstain-body"),
            required_owner_ids: vec![id("owner")],
            final_payload_digests: Vec::new(),
            resource_costs: vec![PlannerAxisValueV1 { axis: id("budget"), value: FixedQ32::ZERO }],
        }],
        resource_reservations: vec![ResourceReservationV1 {
            axis: id("budget"),
            endowment: FixedQ32::ZERO,
            essential_floor: FixedQ32::ZERO,
        }],
    }).expect("prepared");
    let evaluation = bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
        objective_digest: digest("objective"),
        body_generation: generation,
        evaluation_policy_digest: digest("evaluation-policy"),
        evaluation_digest: digest("NDU-owner-evaluation"),
        evaluated_candidate_ids: vec![id("abstain")],
        rejected_candidate_ids: Vec::new(),
        pareto_candidate_ids: vec![id("abstain")],
        advisory_candidate_id: Some(id("abstain")),
        uncertainty_digest: digest("uncertainty"),
        disposition: PlanningEvaluationDispositionV1::InfeasibleExplicitAbstain,
    }).expect("NDU projection");
    let receipt = finalize_plan(&snapshot, &prepared, &evaluation, 100).expect("receipt");
    (snapshot, prepared, evaluation, receipt)
}

#[test]
fn all_five_canonical_sections_match_native_digests_and_round_trip() {
    let (snapshot, prepared, evaluation, receipt) = fixture("plan");
    let archive = PlannerDecisionEnvelopeV1::from_plan(&snapshot, &prepared, &evaluation, &receipt, 100)
        .expect("native digest parity");
    assert_eq!(archive.receipt_digest(), receipt.receipt_digest());
    assert_eq!(PlannerDecisionEnvelopeV1::decode(archive.canonical_bytes()).expect("decode"), archive);
    assert!(archive.canonical_bytes().windows(b"abstain".len()).any(|bytes| bytes == b"abstain"));
    assert!(archive.canonical_bytes().windows(b"owner".len()).any(|bytes| bytes == b"owner"));
    assert!(archive.canonical_bytes().len() > 5 * 32);
}

#[test]
fn every_byte_corruption_is_detected() {
    let (snapshot, prepared, evaluation, receipt) = fixture("plan");
    let archive = PlannerDecisionEnvelopeV1::from_plan(&snapshot, &prepared, &evaluation, &receipt, 100)
        .expect("archive");
    for index in 0..archive.bytes.len() {
        let mut corrupted = archive.bytes.clone();
        corrupted[index] ^= 1;
        assert!(PlannerDecisionEnvelopeV1::decode(&corrupted).is_err(), "byte {index}");
    }
}

#[test]
fn every_truncation_and_unknown_trailing_field_are_rejected() {
    let (snapshot, prepared, evaluation, receipt) = fixture("plan");
    let archive = PlannerDecisionEnvelopeV1::from_plan(&snapshot, &prepared, &evaluation, &receipt, 100)
        .expect("archive");
    for cut in 0..archive.bytes.len() {
        assert!(PlannerDecisionEnvelopeV1::decode(&archive.bytes[..cut]).is_err(), "cut {cut}");
    }
    let mut trailing = archive.bytes.clone();
    trailing.push(0);
    assert!(PlannerDecisionEnvelopeV1::decode(&trailing).is_err());
}

#[test]
fn readable_archive_does_not_authorize_expired_inputs() {
    let (snapshot, prepared, evaluation, receipt) = fixture("plan");
    let archive = PlannerDecisionEnvelopeV1::from_plan(&snapshot, &prepared, &evaluation, &receipt, 100)
        .expect("archive");
    assert!(archive.revalidate(&snapshot, &prepared, &evaluation, &receipt, 199).is_ok());
    assert!(archive.revalidate(&snapshot, &prepared, &evaluation, &receipt, 200).is_err());
}

#[test]
fn a_receipt_from_another_prepared_plan_cannot_be_archived_or_reused() {
    let (snapshot, prepared, evaluation, receipt) = fixture("plan");
    let (_, other_prepared, other_evaluation, other_receipt) = fixture("other-plan");
    assert!(PlannerDecisionEnvelopeV1::from_plan(&snapshot, &prepared, &evaluation, &other_receipt, 100).is_err());
    let archive = PlannerDecisionEnvelopeV1::from_plan(&snapshot, &prepared, &evaluation, &receipt, 100)
        .expect("archive");
    assert!(archive.revalidate(&snapshot, &other_prepared, &other_evaluation, &other_receipt, 100).is_err());
}
