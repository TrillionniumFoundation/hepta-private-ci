use crate::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn principal(name: &str) -> AuthenticatedPrincipalV1 {
    AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(&format!("{name}-credential")),
        signing_key_digest: digest(&format!("{name}-key")),
        scope_digest: digest("scope"),
        authority_epoch: 1,
        authenticated_at: 1,
        expires_at: 100,
    }
}

fn decision(record: &str, episode: &str) -> LedgerEvent {
    LedgerEvent::Decision(EpisodeDecision {
        record_id: id(record),
        episode_id: id(episode),
        objective_digest: digest("objective"),
        policy_id: id("generator"),
        candidate_ids: vec![id("choice"), id("abstain")],
        selected_candidate_id: id("choice"),
        selected_propensity: ProbabilityQ32::from_raw(1 << 31).expect("probability"),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: digest("decision-support"),
    })
}

fn outcome(
    record: &str,
    outcome_id: &str,
    episode: &str,
    predecessor: Option<&str>,
    raw: i64,
) -> LedgerEvent {
    LedgerEvent::AuthenticatedOutcome(AuthenticatedOutcomeV1 {
        record_id: id(record),
        outcome_id: id(outcome_id),
        episode_id: id(episode),
        observer: principal("observer"),
        observed_at: Some(40),
        value: Some(FixedQ32::from_raw(raw)),
        unit_profile_digest: digest("unit"),
        support_digest: digest("outcome-support"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 40,
            expected_delay_profile_digest: digest("delay"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: predecessor.map(id),
            finalized_at: Some(41),
        },
    })
}

#[test]
fn correction_graph_rejects_forks_missing_predecessors_and_cross_episode_edges() {
    let mut ledger = LearningLedger::new();
    ledger.append(decision("decision-1", "episode-1")).expect("decision");
    ledger.append(decision("decision-2", "episode-2")).expect("decision");
    ledger
        .append(outcome("outcome-record-1", "outcome-1", "episode-1", None, 100))
        .expect("first outcome");
    let superseded_digest = ledger.records().last().expect("first outcome row").event_digest;
    ledger
        .append(outcome(
            "outcome-record-2",
            "outcome-2",
            "episode-1",
            Some("outcome-1"),
            100,
        ))
        .expect("correction");
    let current_digest = ledger.records().last().expect("current outcome row").event_digest;
    let source_digests = ledger.dataset_source_record_digests();
    assert!(!source_digests.contains(&superseded_digest));
    assert!(source_digests.contains(&current_digest));

    assert_eq!(
        ledger.append(outcome(
            "outcome-record-fork",
            "outcome-fork",
            "episode-1",
            Some("outcome-1"),
            100,
        )),
        Err(LedgerError::CorrectionNotHead("outcome-1".to_owned()))
    );
    assert_eq!(
        ledger.append(outcome(
            "outcome-record-missing",
            "outcome-missing",
            "episode-1",
            Some("does-not-exist"),
            100,
        )),
        Err(LedgerError::CorrectionPredecessorNotFound(
            "does-not-exist".to_owned()
        ))
    );
    assert_eq!(
        ledger.append(outcome(
            "outcome-record-cross",
            "outcome-cross",
            "episode-2",
            Some("outcome-2"),
            100,
        )),
        Err(LedgerError::CorrectionEpisodeMismatch)
    );
}

#[test]
fn conserved_credit_batch_is_one_ledger_record_and_rejects_drift() {
    let mut ledger = LearningLedger::new();
    ledger.append(decision("decision-1", "episode-1")).expect("decision");
    ledger
        .append(outcome("outcome-record-1", "outcome-1", "episode-1", None, 100))
        .expect("outcome");

    let batch = CreditAllocationBatchV1 {
        batch_id: id("batch-1"),
        episode_id: id("episode-1"),
        outcome_id: id("outcome-1"),
        allocator: principal("allocator"),
        terminal_outcome: FixedQ32::from_raw(100),
        allocations: vec![
            CreditAllocationV1 {
                target_id: id("artifact-b"),
                credit: FixedQ32::from_raw(30),
            },
            CreditAllocationV1 {
                target_id: id("artifact-a"),
                credit: FixedQ32::from_raw(60),
            },
        ],
        conservation_residual: FixedQ32::from_raw(10),
        support_digest: digest("credit-support"),
        finalized: true,
    };
    let before = ledger.records().len();
    ledger
        .append(LedgerEvent::CreditBatch(batch.clone()))
        .expect("conserved batch");
    assert_eq!(ledger.records().len(), before + 1);

    let mut drifted = batch;
    drifted.batch_id = id("batch-2");
    drifted.allocations[0].target_id = id("artifact-c");
    drifted.allocations[1].target_id = id("artifact-d");
    drifted.conservation_residual = FixedQ32::from_raw(9);
    assert_eq!(
        ledger.append(LedgerEvent::CreditBatch(drifted)),
        Err(LedgerError::CreditConservation)
    );
}

#[test]
fn unlearning_lineage_requires_revoked_source_and_linear_derived_head() {
    let mut ledger = LearningLedger::new();
    ledger.append(decision("decision-1", "episode-1")).expect("decision");

    let source_digest = ledger.records()[0].event_digest;
    let base = UnlearningLineageEventV1 {
        record_id: id("unlearn-1"),
        source_record_id: id("decision-1"),
        derived_id: id("dataset-1"),
        derived_kind: UnlearningDerivedKindV1::Dataset,
        predecessor: None,
        authority_id: id("privacy-owner"),
        reason_digest: digest("reason"),
        source_digest,
        derived_digest: digest("dataset"),
    };
    assert_eq!(
        ledger.append(LedgerEvent::UnlearningLineage(base.clone())),
        Err(LedgerError::UnlearningSourceNotRevoked(
            "decision-1".to_owned()
        ))
    );

    ledger
        .append(LedgerEvent::Revocation(Revocation {
            record_id: id("revoke-1"),
            target_record_id: id("decision-1"),
            authority_id: id("privacy-owner"),
            reason_digest: digest("reason"),
        }))
        .expect("revoke");
    ledger
        .append(LedgerEvent::UnlearningLineage(base.clone()))
        .expect("first lineage");

    let mut fork = base.clone();
    fork.record_id = id("unlearn-fork");
    assert_eq!(
        ledger.append(LedgerEvent::UnlearningLineage(fork)),
        Err(LedgerError::UnlearningPredecessorRequired(
            "unlearn-1".to_owned()
        ))
    );

    let mut successor = base;
    successor.record_id = id("unlearn-2");
    successor.predecessor = Some(id("unlearn-1"));
    successor.derived_digest = digest("dataset-successor");
    ledger
        .append(LedgerEvent::UnlearningLineage(successor))
        .expect("lineage successor");
}
