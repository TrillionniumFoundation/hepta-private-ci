use super::*;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn decision() -> AuthenticatedDecisionRecordV2 {
    AuthenticatedDecisionRecordV2 {
        record_id: id("decision-record"),
        episode_id: id("episode"),
        run_snapshot_digest: digest("run-snapshot"),
        objective_digest: digest("objective"),
        policy_digest: digest("policy"),
        generator_id: id("generator"),
        generator_controller_id: id("generator-controller"),
        generator_credential_chain_digest: digest("generator-credential"),
        generator_signing_key_digest: digest("generator-key"),
        generator_scope_digest: digest("scope"),
        generator_authority_epoch: 7,
        candidate_ids: vec![id("action"), id("abstain")],
        selected_candidate_id: id("action"),
        selected_propensity: ProbabilityQ32::ONE,
        candidate_completeness_digest: digest("completeness"),
        support_digest: digest("decision-support"),
        authentication_digest: digest("decision-auth"),
    }
}

fn outcome() -> AuthenticatedOutcomeRecordV2 {
    AuthenticatedOutcomeRecordV2 {
        record_id: id("outcome-record"),
        outcome_id: id("outcome"),
        episode_id: id("episode"),
        observer_id: id("observer"),
        observer_controller_id: id("observer-controller"),
        observer_credential_chain_digest: digest("observer-credential"),
        observer_signing_key_digest: digest("observer-key"),
        observer_scope_digest: digest("scope"),
        observer_authority_epoch: 7,
        observed_at: Some(40),
        value: Some(FixedQ32::from_raw(120)),
        unit_profile_digest: digest("unit"),
        support_digest: digest("outcome-support"),
        latest_observable_at: 45,
        expected_delay_profile_digest: digest("delay"),
        terminality: AuthenticatedOutcomeTerminality::Terminal,
        censoring_reason: None,
        correction_predecessor: None,
        finalized_at: Some(46),
        authentication_digest: digest("outcome-auth"),
    }
}

fn batch() -> CreditAllocationBatchRecordV2 {
    CreditAllocationBatchRecordV2 {
        record_id: id("credit-record"),
        batch_id: id("credit-batch"),
        episode_id: id("episode"),
        outcome_id: id("outcome"),
        allocator_id: id("allocator"),
        allocator_controller_id: id("allocator-controller"),
        allocator_credential_chain_digest: digest("allocator-credential"),
        allocator_signing_key_digest: digest("allocator-key"),
        allocator_scope_digest: digest("scope"),
        allocator_authority_epoch: 7,
        terminal_outcome: FixedQ32::from_raw(120),
        allocations: vec![
            CreditAllocationRecordV2 {
                target_artifact_id: id("artifact-a"),
                credit: FixedQ32::from_raw(60),
            },
            CreditAllocationRecordV2 {
                target_artifact_id: id("artifact-b"),
                credit: FixedQ32::from_raw(50),
            },
        ],
        conservation_residual: FixedQ32::from_raw(10),
        support_digest: digest("credit-rule"),
        authentication_digest: digest("credit-auth"),
    }
}

fn snapshot() -> LedgerSnapshot {
    let mut ledger = LearningLedger::new();
    ledger
        .append(LedgerEvent::AuthenticatedDecisionV2(decision()))
        .unwrap();
    ledger
        .append(LedgerEvent::AuthenticatedOutcomeV2(outcome()))
        .unwrap();
    ledger
        .append(LedgerEvent::CreditBatchV2(batch()))
        .unwrap();
    ledger.snapshot()
}

#[test]
fn registered_decision_and_outcome_adapters_round_trip_canonical_json() {
    let decision_wire = LearningDecisionV1::from(&decision());
    let encoded = encode_learning_decision_v1(&decision_wire).unwrap();
    assert_eq!(
        decode_learning_decision_v1(&encoded).unwrap(),
        decision_wire
    );
    assert_eq!(decision_wire.propensity_ppm, 1_000_000);

    let outcome_wire = OutcomeReceiptV1::try_from(&outcome()).unwrap();
    let encoded = encode_outcome_receipt_v1(&outcome_wire).unwrap();
    assert_eq!(decode_outcome_receipt_v1(&encoded).unwrap(), outcome_wire);
}

#[test]
fn registered_protocols_reject_unknown_fields() {
    let invalid = br#"{
        "decisionId":"decision-record",
        "episodeId":"episode",
        "candidateSetDigest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "policyDigest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "chosenId":"action",
        "propensityPpm":1000000,
        "unexpected":true
    }"#;
    assert_eq!(
        decode_learning_decision_v1(invalid),
        Err(LearningProtocolError::Json)
    );
}

#[test]
fn credit_and_episode_views_bind_exact_snapshot_history() {
    let snapshot = snapshot();
    let credit = snapshot
        .records()
        .iter()
        .find_map(|record| match &record.event {
            LedgerEvent::CreditBatchV2(value) => Some(value),
            _ => None,
        })
        .unwrap();
    let credit_wire =
        CreditAssignmentReceiptV1::from_batch(credit, &snapshot).unwrap();
    let encoded = encode_credit_assignment_receipt_v1(&credit_wire).unwrap();
    assert_eq!(
        decode_credit_assignment_receipt_v1(&encoded).unwrap(),
        credit_wire
    );

    let episode = LearningEpisodeV1::from_snapshot(&snapshot, &id("episode")).unwrap();
    assert_eq!(episode.ordered_event_digests.len(), 3);
    assert_eq!(
        decode_learning_episode_v1(&encode_learning_episode_v1(&episode).unwrap()).unwrap(),
        episode
    );
}

#[test]
fn dataset_v3_has_deterministic_registered_v1_compatibility_view() {
    let producer = AuthenticatedPrincipalV1 {
        principal_id: id("dataset-owner"),
        credential_chain_digest: digest("credential"),
        signing_key_digest: digest("key"),
        scope_digest: digest("scope"),
        authority_epoch: 7,
        authenticated_at: 10,
        expires_at: 100,
    };
    let receipt = freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: id("dataset"),
            producer,
            ledger_head_digest: digest("ledger-head"),
            objective_digest: digest("objective"),
            eligible_frontier: 3,
            outcome_watermark: 45,
            correction_cut_digest: digest("correction-cut"),
            revocation_cut_digest: digest("revocation-cut"),
            inclusion_policy_digest: digest("split-policy"),
            source_record_digests: vec![digest("record-a"), digest("record-b")],
            pending_outcomes: 0,
            censored_outcomes: 0,
        },
        50,
    )
    .unwrap();
    let wire = DatasetSnapshotV1::try_from(&receipt).unwrap();
    let encoded = encode_dataset_snapshot_v1(&wire).unwrap();
    assert_eq!(decode_dataset_snapshot_v1(&encoded).unwrap(), wire);
    assert_eq!(wire.row_count, 2);
}
