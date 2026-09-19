use super::*;
use codex_hepta_types::ProbabilityQ32;
use pretty_assertions::assert_eq;

use crate::CandidateSetCompleteness;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[test]
fn canonical_decision_json_uses_registry_field_names_and_order() {
    let decision = EpisodeDecision {
        record_id: id("decision-1"),
        episode_id: id("episode-1"),
        objective_digest: digest("objective"),
        policy_id: id("policy-1"),
        candidate_ids: vec![id("abstain"), id("choice")],
        selected_candidate_id: id("choice"),
        selected_propensity: ProbabilityQ32::from_raw(1 << 31).expect("probability"),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: digest("support"),
    };
    let wire = LearningDecisionV1::from_episode_decision(
        &decision,
        digest("candidate-set"),
        digest("policy"),
        None,
    );
    let encoded = wire.to_canonical_json().expect("encode");
    let text = std::str::from_utf8(&encoded).expect("utf8");
    assert!(text.starts_with("{\"decisionId\":\"decision-1\",\"episodeId\":\"episode-1\",\"candidateSetDigest\":"));
    assert!(text.contains("\"policyDigest\":"));
    assert!(text.contains("\"chosenId\":\"choice\""));
    assert!(text.contains("\"propensityPpm\":500000"));
    assert!(text.ends_with("\"randomSeedDigest\":null}"));
    assert_eq!(
        LearningDecisionV1::from_canonical_json(&encoded).expect("decode"),
        wire
    );
}

#[test]
fn unknown_critical_fields_reject() {
    let bytes = br#"{"decisionId":"decision-1","episodeId":"episode-1","candidateSetDigest":"0000000000000000000000000000000000000000000000000000000000000001","policyDigest":"0000000000000000000000000000000000000000000000000000000000000002","chosenId":"choice","propensityPpm":1,"randomSeedDigest":null,"futureCritical":true}"#;
    assert_eq!(
        LearningDecisionV1::from_canonical_json(bytes),
        Err(ProtocolAdapterError::Json)
    );
}

#[test]
fn credit_batch_adapter_preserves_allocations_and_residual() {
    let principal = crate::AuthenticatedPrincipalV1 {
        principal_id: id("allocator"),
        credential_chain_digest: digest("credential"),
        signing_key_digest: digest("key"),
        scope_digest: digest("scope"),
        authority_epoch: 1,
        authenticated_at: 1,
        expires_at: 100,
    };
    let batch = CreditAllocationBatchV1 {
        batch_id: id("credit-batch"),
        episode_id: id("episode-1"),
        outcome_id: id("outcome-1"),
        allocator: principal,
        terminal_outcome: codex_hepta_types::FixedQ32::from_raw(100),
        allocations: vec![
            crate::CreditAllocationV1 {
                target_id: id("artifact-a"),
                credit: codex_hepta_types::FixedQ32::from_raw(60),
            },
            crate::CreditAllocationV1 {
                target_id: id("artifact-b"),
                credit: codex_hepta_types::FixedQ32::from_raw(30),
            },
        ],
        conservation_residual: codex_hepta_types::FixedQ32::from_raw(10),
        support_digest: digest("support"),
        finalized: true,
    };
    let wire =
        CreditAssignmentReceiptV1::from_credit_batch(&batch, digest("outcome"), digest("rule"));
    assert_eq!(wire.credit_id, id("credit-batch"));
    assert_eq!(wire.allocations.len(), 2);
    assert_eq!(wire.conservation_residual_q32, 10);
    let roundtrip = CreditAssignmentReceiptV1::from_canonical_json(
        &wire.to_canonical_json().expect("encode"),
    )
    .expect("decode");
    assert_eq!(roundtrip, wire);
}

#[test]
fn dataset_adapter_binds_revocation_cut_as_deletion_cutoff() {
    let principal = crate::AuthenticatedPrincipalV1 {
        principal_id: id("producer"),
        credential_chain_digest: digest("credential"),
        signing_key_digest: digest("key"),
        scope_digest: digest("scope"),
        authority_epoch: 1,
        authenticated_at: 1,
        expires_at: 100,
    };
    let receipt = DatasetSnapshotReceiptV3 {
        snapshot: crate::DatasetSnapshotV2 {
            snapshot_id: id("dataset-1"),
            ledger_head_digest: digest("head"),
            objective_digest: digest("objective"),
            eligible_frontier: 4,
            outcome_watermark: 50,
            source_record_digests: vec![digest("a"), digest("b")],
            pending_outcomes: 0,
            censored_outcomes: 0,
            dataset_digest: digest("content"),
            authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
        },
        producer: principal,
        correction_cut_digest: digest("correction"),
        revocation_cut_digest: digest("revocation"),
        inclusion_policy_digest: digest("policy"),
    };
    let wire = DatasetSnapshotV1::from_dataset_receipt(
        &receipt,
        digest("schema"),
        digest("split"),
    );
    assert_eq!(wire.deletion_cutoff_digest, digest("revocation"));
    assert_eq!(wire.content_digest, digest("content"));
    assert_eq!(wire.row_count, 2);
}
