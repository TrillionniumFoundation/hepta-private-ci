use super::*;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf_learning::OutcomeSignalV1;
use codex_hepta_cognitive_types::hnmf_learning::ReplayResourceReceiptV1;
use codex_hepta_cognitive_types::hnmf_learning::ReplaySelectionReceiptV1;
use codex_hepta_cognitive_types::hnmf_learning::SourceBucketCountV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn revision(value: u64) -> Revision {
    Revision::new(value).unwrap_or_else(|error| panic!("valid revision: {error}"))
}

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:compact"),
        purpose_id: id("purpose:consolidation"),
        memory_ledger_frontier: 20,
        knowledge_fact_frontier: 14,
        tombstone_frontier: 6,
        source_ledger_frontier: 21,
        knowledge_graph_generation: generation(3),
        compact_checkpoint_generation: generation(1),
        prompt_registry_revision: revision(4),
        retrieval_profile_digest: digest("retrieval"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 8,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    })
    .unwrap_or_else(|error| panic!("valid snapshot key: {error}"))
}

fn record(
    record_id: &str,
    revision_value: u64,
    predecessor_digest: Option<Digest32>,
    state: RecordState,
) -> MemoryRecord {
    MemoryRecord {
        record_id: id(record_id),
        revision: revision(revision_value),
        kind: MemoryKind::Fact,
        content_digest: digest(&format!("{record_id}:{revision_value}:{state:?}")),
        predecessor_digest,
        citations: Vec::new(),
        state,
    }
}

fn input(record: MemoryRecord, priority: u32) -> CompactionInputRecordV2 {
    CompactionInputRecordV2 {
        retention_reason_digest: digest(&format!("reason:{}", record.record_id)),
        record,
        retention_priority: priority,
    }
}

fn policy(maximum: u32, protected: Vec<StableId>) -> CompactionPolicyV2 {
    CompactionPolicyV2 {
        policy_id: id("policy:compact"),
        algorithm_digest: digest("algorithm"),
        compatibility_digest: digest("compatibility"),
        maximum_retained_records: maximum,
        protected_record_ids: protected,
    }
}

fn contract_id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).unwrap_or_else(|error| panic!("valid contract id: {error}"))
}

fn contract_digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(digest(value))
        .unwrap_or_else(|error| panic!("valid contract digest: {error}"))
}

fn shadow_candidate() -> QualifiedCompactionCandidateV2 {
    let retained = record("memory:retained", 1, None, RecordState::Live);
    build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(1, vec![id("memory:retained")]),
        vec![input(retained, 10)],
    )
    .unwrap_or_else(|error| panic!("valid shadow candidate: {error}"))
}

fn replay_receipt(event_ids: Vec<ContractIdV1>) -> ReplaySelectionReceiptV1 {
    let selected_count =
        u16::try_from(event_ids.len()).unwrap_or_else(|_| panic!("bounded replay fixture"));
    ReplaySelectionReceiptV1 {
        candidate_set_digest: contract_digest("candidate-set"),
        selected_event_ids: event_ids,
        source_bucket_counts: if selected_count == 0 {
            Vec::new()
        } else {
            vec![SourceBucketCountV1 {
                source_bucket: 1,
                selected_count,
            }]
        },
        selection_policy_digest: contract_digest("selection-policy"),
        resource_receipt: ReplayResourceReceiptV1 {
            candidate_count: selected_count.max(1),
            selected_count,
            maximum_per_source_bucket: selected_count.max(1),
        },
    }
}

fn outcome_signal() -> OutcomeSignalV1 {
    OutcomeSignalV1 {
        episode_id: contract_id("episode:1"),
        utility_delta_ppm: 10_000,
        prediction_error_ppm: 20_000,
        novelty_ppm: 30_000,
        risk_ppm: 40_000,
        ood_ppm: 50_000,
        observer_digest: contract_digest("observer"),
    }
}

fn replay_binding(event_id: &str, record: &MemoryRecord) -> CanonicalReplayRecordBindingV1 {
    CanonicalReplayRecordBindingV1 {
        event_id: contract_id(event_id),
        legacy_record_id: record.record_id.clone(),
        legacy_record_revision: record.revision,
        legacy_record_digest: record.record_digest(),
    }
}

#[test]
fn protected_live_reference_is_retained_before_higher_priority_optional_record() {
    let protected = record("memory:protected", 1, None, RecordState::Live);
    let optional = record("memory:optional", 1, None, RecordState::Live);
    let candidate = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(1, vec![id("memory:protected")]),
        vec![input(optional, 100), input(protected, 1)],
    )
    .unwrap_or_else(|error| panic!("valid candidate: {error}"));
    assert_eq!(candidate.retained_records.len(), 1);
    assert_eq!(
        candidate.retained_records[0].record_id,
        id("memory:protected")
    );
    assert_eq!(candidate.loss_report.protected_retained_records, 1);
    assert_eq!(candidate.loss_report.omitted_live_records, 1);
}

#[test]
fn tombstoned_head_is_never_replayed_or_retained() {
    let live = record("memory:deleted", 1, None, RecordState::Live);
    let tombstone = record(
        "memory:deleted",
        2,
        Some(live.record_digest()),
        RecordState::Tombstone,
    );
    let candidate = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(4, vec![id("memory:deleted")]),
        vec![input(live, 10), input(tombstone, 10)],
    )
    .unwrap_or_else(|error| panic!("valid deleted candidate: {error}"));
    assert!(candidate.retained_records.is_empty());
    assert_eq!(candidate.loss_report.deleted_records, 1);
    assert_eq!(candidate.loss_report.protected_deleted_records, 1);
    assert_eq!(candidate.checkpoint.tombstone_cutoff, 6);
}

#[test]
fn explicit_resurrection_after_tombstone_is_rejected() {
    let live = record("memory:resurrected", 1, None, RecordState::Live);
    let tombstone = record(
        "memory:resurrected",
        2,
        Some(live.record_digest()),
        RecordState::Tombstone,
    );
    let resurrected = record(
        "memory:resurrected",
        3,
        Some(tombstone.record_digest()),
        RecordState::Live,
    );
    assert_eq!(
        build_qualified_candidate(
            snapshot_key(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(4, Vec::new()),
            vec![input(live, 1), input(tombstone, 1), input(resurrected, 1)],
        ),
        Err(QualifiedCompactionError::ResurrectionDenied(
            "memory:resurrected".to_string()
        ))
    );
}

#[test]
fn candidate_is_order_independent() {
    let inputs = vec![
        input(record("memory:a", 1, None, RecordState::Live), 3),
        input(record("memory:b", 1, None, RecordState::Live), 2),
        input(record("memory:c", 1, None, RecordState::Live), 1),
    ];
    let mut reversed = inputs.clone();
    reversed.reverse();
    let left = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(2, Vec::new()),
        inputs,
    )
    .unwrap_or_else(|error| panic!("valid left candidate: {error}"));
    let right = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(2, Vec::new()),
        reversed,
    )
    .unwrap_or_else(|error| panic!("valid right candidate: {error}"));
    assert_eq!(left, right);
}

#[test]
fn proof_requires_all_loss_and_deletion_obligations() {
    let candidate = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(2, Vec::new()),
        vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
    )
    .unwrap_or_else(|error| panic!("valid candidate: {error}"));
    let qualification = CompactionQualificationV2 {
        evaluator_id: id("evaluator:independent"),
        retained_query_suite_digest: digest("queries"),
        reconstruction_obligation_digest: digest("reconstruction"),
        contradiction_holdout_digest: digest("contradictions"),
        retained_queries_passed: true,
        reconstruction_passed: true,
        contradictions_preserved: true,
        deletion_non_resurrection_passed: true,
    };
    let proof = prove_compaction(&candidate, qualification.clone())
        .unwrap_or_else(|error| panic!("valid proof: {error}"));
    assert_eq!(
        proof.checkpoint_digest,
        candidate.checkpoint.checkpoint_digest
    );
    assert_eq!(proof.authority, AuthorityPosture::DENY_ALL);

    let mut failed = qualification;
    failed.deletion_non_resurrection_passed = false;
    assert_eq!(
        prove_compaction(&candidate, failed),
        Err(QualifiedCompactionError::DeletionNonResurrectionFailed)
    );
}

#[test]
fn protected_set_cannot_exceed_checkpoint_capacity() {
    let first = record("memory:a", 1, None, RecordState::Live);
    let second = record("memory:b", 1, None, RecordState::Live);
    assert_eq!(
        build_qualified_candidate(
            snapshot_key(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(1, vec![id("memory:a"), id("memory:b")]),
            vec![input(first, 1), input(second, 1)],
        ),
        Err(QualifiedCompactionError::ProtectedReferencesExceedCapacity)
    );
}

#[test]
fn canonical_replay_shadow_binds_selected_event_to_retained_record() {
    let candidate = shadow_candidate();
    let retained = candidate.retained_records[0].clone();
    let replay = replay_receipt(vec![contract_id("event:retained")]);
    let shadow = bind_canonical_replay_outcome_shadow_v1(
        &candidate,
        replay,
        outcome_signal(),
        vec![replay_binding("event:retained", &retained)],
    )
    .unwrap_or_else(|error| panic!("canonical replay shadow: {error}"));

    shadow
        .validate()
        .unwrap_or_else(|error| panic!("canonical replay shadow validation: {error}"));
    assert_eq!(shadow.candidate.candidate_digest, candidate.candidate_digest);
    assert_eq!(shadow.selected_bindings.len(), 1);
    assert!(!shadow.authority.grants_any());
}

#[test]
fn canonical_replay_shadow_rejects_nonretained_or_collapsed_identity() {
    let candidate = shadow_candidate();
    let retained = candidate.retained_records[0].clone();
    let replay = replay_receipt(vec![contract_id("event:retained")]);

    let mut missing = replay_binding("event:retained", &retained);
    missing.legacy_record_id = id("memory:not-retained");
    assert_eq!(
        bind_canonical_replay_outcome_shadow_v1(
            &candidate,
            replay,
            outcome_signal(),
            vec![missing],
        ),
        Err(QualifiedCompactionError::CanonicalReplayBindingMismatch)
    );

    let replay = replay_receipt(vec![contract_id("event:a"), contract_id("event:b")]);
    assert_eq!(
        bind_canonical_replay_outcome_shadow_v1(
            &candidate,
            replay,
            outcome_signal(),
            vec![
                replay_binding("event:b", &retained),
                replay_binding("event:a", &retained),
            ],
        ),
        Err(QualifiedCompactionError::CanonicalReplayBindingMismatch)
    );
}

#[test]
fn canonical_replay_shadow_revalidates_embedded_evidence() {
    let candidate = shadow_candidate();
    let retained = candidate.retained_records[0].clone();
    let mut shadow = bind_canonical_replay_outcome_shadow_v1(
        &candidate,
        replay_receipt(vec![contract_id("event:retained")]),
        outcome_signal(),
        vec![replay_binding("event:retained", &retained)],
    )
    .unwrap_or_else(|error| panic!("canonical replay shadow: {error}"));

    shadow.outcome_signal.risk_ppm = 41_000;
    assert_eq!(
        shadow.validate(),
        Err(QualifiedCompactionError::CanonicalShadowDigestMismatch)
    );
}
