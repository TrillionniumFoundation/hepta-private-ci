use super::*;

use codex_hepta_cognitive_types::MemoryKind;
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
        serialized_bytes: 64,
        token_count: 16,
    }
}

fn input_cost(
    record: MemoryRecord,
    priority: u32,
    serialized_bytes: u64,
    token_count: u64,
) -> CompactionInputRecordV2 {
    let mut value = input(record, priority);
    value.serialized_bytes = serialized_bytes;
    value.token_count = token_count;
    value
}

fn policy(maximum: u32, protected: Vec<StableId>) -> CompactionPolicyV2 {
    CompactionPolicyV2 {
        policy_id: id("policy:compact"),
        algorithm_digest: digest("algorithm"),
        compatibility_digest: digest("compatibility"),
        tokenizer_digest: snapshot_key().vector.tokenizer_digest,
        maximum_retained_records: maximum,
        maximum_retained_bytes: 4096,
        maximum_retained_tokens: 1024,
        protected_record_ids: protected,
    }
}

fn qualification() -> CompactionQualificationV2 {
    CompactionQualificationV2 {
        evaluator_id: id("evaluator:independent"),
        evaluation_artifact_digest: digest("evaluation-artifact"),
        evaluator_implementation_digest: digest("evaluator-implementation"),
        attestation_digest: digest("attestation"),
        signature_digest: digest("signature"),
        retained_query_suite_digest: digest("queries"),
        reconstruction_obligation_digest: digest("reconstruction"),
        contradiction_holdout_digest: digest("contradictions"),
        retained_queries_passed: true,
        reconstruction_passed: true,
        contradictions_preserved: true,
        deletion_non_resurrection_passed: true,
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
fn live_tombstone_live_resurrection_is_rejected_on_the_only_public_builder() {
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
fn byte_and_token_budgets_omit_optional_records_deterministically() {
    let mut bounded = policy(4, Vec::new());
    bounded.maximum_retained_bytes = 100;
    bounded.maximum_retained_tokens = 25;
    let candidate = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &bounded,
        vec![
            input_cost(record("memory:a", 1, None, RecordState::Live), 3, 60, 15),
            input_cost(record("memory:b", 1, None, RecordState::Live), 2, 60, 15),
            input_cost(record("memory:c", 1, None, RecordState::Live), 1, 30, 8),
        ],
    )
    .expect("bounded candidate");
    assert_eq!(candidate.retained_records.len(), 2);
    assert_eq!(candidate.retained_records[0].record_id, id("memory:a"));
    assert_eq!(candidate.retained_records[1].record_id, id("memory:c"));
    assert_eq!(candidate.loss_report.retained_bytes, 90);
    assert_eq!(candidate.loss_report.retained_tokens, 23);
    assert_eq!(candidate.loss_report.omitted_live_records, 1);
}

#[test]
fn protected_reference_must_fit_byte_and_token_budgets() {
    let protected = record("memory:protected", 1, None, RecordState::Live);
    let mut bounded = policy(2, vec![id("memory:protected")]);
    bounded.maximum_retained_bytes = 32;
    assert_eq!(
        build_qualified_candidate(
            snapshot_key(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &bounded,
            vec![input_cost(protected.clone(), 1, 64, 16)],
        ),
        Err(QualifiedCompactionError::ProtectedReferencesExceedByteCapacity)
    );
    bounded.maximum_retained_bytes = 128;
    bounded.maximum_retained_tokens = 8;
    assert_eq!(
        build_qualified_candidate(
            snapshot_key(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &bounded,
            vec![input_cost(protected, 1, 64, 16)],
        ),
        Err(QualifiedCompactionError::ProtectedReferencesExceedTokenCapacity)
    );
}

#[test]
fn tokenizer_mismatch_is_rejected() {
    let mut mismatched = policy(2, Vec::new());
    mismatched.tokenizer_digest = digest("other-tokenizer");
    assert_eq!(
        build_qualified_candidate(
            snapshot_key(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &mismatched,
            vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
        ),
        Err(QualifiedCompactionError::TokenizerMismatch)
    );
}

#[test]
fn candidate_validation_cross_checks_payload_and_omission_digests() {
    let mut candidate = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(1, Vec::new()),
        vec![
            input(record("memory:a", 1, None, RecordState::Live), 2),
            input(record("memory:b", 1, None, RecordState::Live), 1),
        ],
    )
    .expect("candidate");
    candidate.checkpoint.payload_digest = digest("tampered-payload");
    candidate.checkpoint.checkpoint_digest = candidate.checkpoint.compute_checkpoint_digest();
    candidate.candidate_digest = candidate.compute_candidate_digest();
    assert_eq!(
        candidate.validate(),
        Err(QualifiedCompactionError::DigestMismatch("payload"))
    );
}

#[test]
fn proof_binds_independent_evaluator_and_attestation_material() {
    let candidate = build_qualified_candidate(
        snapshot_key(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(2, Vec::new()),
        vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
    )
    .unwrap_or_else(|error| panic!("valid candidate: {error}"));
    let qualification = qualification();
    let proof = prove_compaction(&candidate, qualification.clone())
        .unwrap_or_else(|error| panic!("valid proof: {error}"));
    assert_eq!(proof.evaluator_id, qualification.evaluator_id);
    assert_eq!(
        proof.evaluation_artifact_digest,
        qualification.evaluation_artifact_digest
    );
    assert_eq!(
        proof.evaluator_implementation_digest,
        qualification.evaluator_implementation_digest
    );
    assert_eq!(proof.attestation_digest, qualification.attestation_digest);
    assert_eq!(proof.signature_digest, qualification.signature_digest);
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
