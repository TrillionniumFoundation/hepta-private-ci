use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::*;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid test id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    result.unwrap_or_else(|error| panic!("unexpected error: {error:?}"))
}

fn decision_v2() -> AuthenticatedDecisionV2 {
    let mut candidate_ids = vec![id("candidate-a"), id("abstain")];
    candidate_ids.sort();
    AuthenticatedDecisionV2 {
        decision: EpisodeDecision {
            record_id: id("decision-record"),
            episode_id: id("episode"),
            objective_digest: digest("objective"),
            policy_id: id("generator"),
            candidate_ids: candidate_ids.clone(),
            selected_candidate_id: id("candidate-a"),
            selected_propensity: ProbabilityQ32::from_raw(1_u64 << 31).expect("probability"),
            completeness: CandidateSetCompleteness::Complete,
            support_digest: digest("decision-support"),
        },
        generator_credential_chain_digest: digest("generator-credential"),
        generator_signing_key_digest: digest("generator-key"),
        generator_controller_id: id("generator-controller"),
        generator_scope_digest: digest("scope"),
        generator_authority_epoch: 7,
        candidate_set_digest: crate::ledger::candidate_ids_digest(&candidate_ids),
        candidate_count: 2,
        omitted_count_bound: 0,
        candidate_receipt_digest: digest("candidate-receipt"),
        evidence_digest: digest("generator-evidence"),
    }
}

fn outcome_v2(
    record: &str,
    outcome: &str,
    predecessor: Option<&str>,
    value: i64,
) -> AuthenticatedOutcomeV2 {
    AuthenticatedOutcomeV2 {
        record_id: id(record),
        outcome_id: id(outcome),
        episode_id: id("episode"),
        observer_id: id("observer"),
        observer_credential_chain_digest: digest("observer-credential"),
        observer_signing_key_digest: digest("observer-key"),
        observer_controller_id: id("observer-controller"),
        observer_scope_digest: digest("scope"),
        observer_authority_epoch: 7,
        observed_at: Some(40),
        value: Some(FixedQ32::from_raw(value)),
        unit_profile_digest: digest("reward-unit"),
        support_digest: digest("outcome-support"),
        latest_observable_at: 45,
        expected_delay_profile_digest: digest("delay-profile"),
        terminality: DurableOutcomeTerminalityV2::Terminal,
        censoring_reason: None,
        correction_predecessor: predecessor.map(id),
        finalized_at: Some(46),
        evidence_digest: digest("observer-evidence"),
    }
}

fn credit_batch(value: i64, residual: i64) -> CreditAllocationBatchV2 {
    CreditAllocationBatchV2 {
        record_id: id("credit-record"),
        batch_id: id("credit-batch"),
        episode_id: id("episode"),
        outcome_id: id("outcome-1"),
        allocator_id: id("allocator"),
        allocator_credential_chain_digest: digest("allocator-credential"),
        allocator_signing_key_digest: digest("allocator-key"),
        allocator_controller_id: id("allocator-controller"),
        allocator_scope_digest: digest("scope"),
        allocator_authority_epoch: 7,
        terminal_outcome: FixedQ32::from_raw(value),
        allocations: vec![
            DurableCreditAllocationV1 {
                target_id: id("artifact-a"),
                credit: FixedQ32::from_raw(60),
            },
            DurableCreditAllocationV1 {
                target_id: id("artifact-b"),
                credit: FixedQ32::from_raw(30),
            },
        ],
        conservation_residual: FixedQ32::from_raw(residual),
        parent_credit_id: None,
        rule_digest: digest("rule"),
        support_digest: digest("credit-support"),
        evidence_digest: digest("allocator-evidence"),
    }
}

#[test]
fn authenticated_episode_rejects_weak_v1_outcome() {
    let mut ledger = LearningLedger::new();
    must(ledger.append(LedgerEvent::DecisionV2(decision_v2())));
    let weak = OutcomeObservation {
        record_id: id("weak-outcome-record"),
        outcome_id: id("weak-outcome"),
        episode_id: id("episode"),
        observer_id: id("observer"),
        value: FixedQ32::from_raw(1),
        finality: OutcomeFinality::Terminal,
        support_digest: digest("weak-support"),
    };
    assert_eq!(
        ledger.append(LedgerEvent::Outcome(weak)),
        Err(LedgerError::WeakV1WriteDenied)
    );
}

#[test]
fn correction_graph_requires_current_same_episode_head() {
    let mut ledger = LearningLedger::new();
    must(ledger.append(LedgerEvent::DecisionV2(decision_v2())));
    must(ledger.append(LedgerEvent::OutcomeV2(outcome_v2(
        "outcome-record-0",
        "outcome-0",
        None,
        100,
    ))));
    must(ledger.append(LedgerEvent::OutcomeV2(outcome_v2(
        "outcome-record-1",
        "outcome-1",
        Some("outcome-0"),
        110,
    ))));
    let fork = outcome_v2(
        "outcome-record-fork",
        "outcome-fork",
        Some("outcome-0"),
        120,
    );
    assert_eq!(
        ledger.append(LedgerEvent::OutcomeV2(fork)),
        Err(LedgerError::CorrectionNotHead)
    );
}

#[test]
fn credit_batch_is_one_conserved_durable_fact() {
    let mut ledger = LearningLedger::new();
    must(ledger.append(LedgerEvent::DecisionV2(decision_v2())));
    must(ledger.append(LedgerEvent::OutcomeV2(outcome_v2(
        "outcome-record-1",
        "outcome-1",
        None,
        100,
    ))));

    let mut invalid = credit_batch(100, 9);
    invalid.record_id = id("bad-credit-record");
    invalid.batch_id = id("bad-credit-batch");
    assert_eq!(
        ledger.append(LedgerEvent::CreditBatchV2(invalid)),
        Err(LedgerError::CreditConservation)
    );

    must(ledger.append(LedgerEvent::CreditBatchV2(credit_batch(100, 10))));
    assert_eq!(ledger.records().len(), 3);
}

#[test]
fn unlearning_lineage_revokes_sources_without_rewriting_history() {
    let mut ledger = LearningLedger::new();
    must(ledger.append(LedgerEvent::DecisionV2(decision_v2())));
    must(ledger.append(LedgerEvent::OutcomeV2(outcome_v2(
        "outcome-record-1",
        "outcome-1",
        None,
        100,
    ))));
    let lineage = UnlearningLineageEventV1 {
        record_id: id("unlearning-record-1"),
        lineage_id: id("unlearning-1"),
        scope_digest: digest("scope"),
        authority_id: id("privacy-authority"),
        authority_credential_chain_digest: digest("privacy-credential"),
        authority_signing_key_digest: digest("privacy-key"),
        authority_controller_id: id("privacy-controller"),
        authority_epoch: 7,
        reason_digest: digest("forget-request"),
        source_record_ids: vec![id("decision-record")],
        dataset_ids: vec![id("dataset-1")],
        artifact_ids: vec![id("artifact-1")],
        predecessor_lineage_id: None,
        evidence_digest: digest("privacy-evidence"),
    };
    must(ledger.append(LedgerEvent::UnlearningV1(lineage)));
    assert!(ledger.dataset_is_invalidated(&id("dataset-1")));
    assert!(ledger.artifact_is_invalidated(&id("artifact-1")));
    assert!(
        ledger
            .active_records()
            .iter()
            .all(|record| matches!(record.event, LedgerEvent::UnlearningV1(_)))
    );

    let second = UnlearningLineageEventV1 {
        record_id: id("unlearning-record-2"),
        lineage_id: id("unlearning-2"),
        scope_digest: digest("scope"),
        authority_id: id("privacy-authority"),
        authority_credential_chain_digest: digest("privacy-credential"),
        authority_signing_key_digest: digest("privacy-key"),
        authority_controller_id: id("privacy-controller"),
        authority_epoch: 7,
        reason_digest: digest("second-request"),
        source_record_ids: vec![id("outcome-record-1")],
        dataset_ids: vec![],
        artifact_ids: vec![],
        predecessor_lineage_id: None,
        evidence_digest: digest("privacy-evidence-2"),
    };
    assert_eq!(
        ledger.append(LedgerEvent::UnlearningV1(second)),
        Err(LedgerError::LineagePredecessorMismatch)
    );
}

#[test]
fn snapshot_replay_preserves_new_event_invariants() {
    let mut ledger = LearningLedger::new();
    must(ledger.append(LedgerEvent::DecisionV2(decision_v2())));
    must(ledger.append(LedgerEvent::OutcomeV2(outcome_v2(
        "outcome-record-1",
        "outcome-1",
        None,
        100,
    ))));
    must(ledger.append(LedgerEvent::CreditBatchV2(credit_batch(100, 10))));
    let snapshot = ledger.snapshot();
    let restored = must(LearningLedger::from_snapshot(snapshot.clone()));
    assert_eq!(restored.snapshot(), snapshot);
    let checkpoint = must(generate_index_checkpoint(&snapshot));
    must(verify_index_checkpoint(&snapshot, &checkpoint));
}

#[test]
fn checkpoint_rebuilds_long_history() {
    let mut ledger = LearningLedger::new();
    for index in 0..10_000_u64 {
        must(ledger.append(LedgerEvent::Decision(EpisodeDecision {
            record_id: id(&format!("record-{index:05}")),
            episode_id: id(&format!("episode-{index:05}")),
            objective_digest: digest("capacity-objective"),
            policy_id: id("legacy-capacity-policy"),
            candidate_ids: vec![id("abstain"), id("candidate")],
            selected_candidate_id: id("abstain"),
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompleteness::Complete,
            support_digest: digest("capacity-support"),
        })));
    }
    let snapshot = ledger.snapshot();
    let checkpoint = must(generate_index_checkpoint(&snapshot));
    assert_eq!(checkpoint.record_count, 10_000);
    assert_eq!(checkpoint.active_record_count, 10_000);
    must(verify_index_checkpoint(&snapshot, &checkpoint));
}
