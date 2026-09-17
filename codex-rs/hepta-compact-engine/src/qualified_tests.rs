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
    }
}

fn policy(
    snapshot: &CognitiveSnapshotKeyV1,
    maximum: u32,
    protected: Vec<StableId>,
    maximum_payload_bytes: u64,
    maximum_payload_tokens: u64,
) -> CompactionPolicyV2 {
    CompactionPolicyV2 {
        policy_id: id("policy:compact"),
        algorithm_digest: digest("selection-algorithm"),
        semantic_compaction_digest: digest("semantic-algorithm"),
        compatibility_digest: digest("compatibility"),
        tokenizer_digest: snapshot.vector.tokenizer_digest,
        maximum_retained_records: maximum,
        maximum_payload_bytes,
        maximum_payload_tokens,
        protected_record_ids: protected,
    }
}

fn semantic_artifact(
    snapshot: &CognitiveSnapshotKeyV1,
    encoded_bytes: u64,
    token_count: u64,
) -> SemanticCompactionArtifactV1 {
    SemanticCompactionArtifactV1::new(
        id("artifact:compact"),
        id("producer:semantic-compactor"),
        snapshot.vector_digest,
        digest("semantic-payload"),
        digest("semantic-algorithm"),
        snapshot.vector.model_digest,
        snapshot.vector.tokenizer_digest,
        encoded_bytes,
        token_count,
    )
    .unwrap_or_else(|error| panic!("valid semantic artifact: {error}"))
}

fn qualification() -> CompactionQualificationV2 {
    CompactionQualificationV2 {
        evaluator_id: id("evaluator:independent"),
        evaluator_implementation_digest: digest("evaluator-implementation"),
        evaluation_artifact_digest: digest("evaluation-artifact"),
        attestation_digest: digest("attestation"),
        attestation_key_digest: digest("attestation-key"),
        signature_digest: digest("attestation-signature"),
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
    let snapshot = snapshot_key();
    let protected = record("memory:protected", 1, None, RecordState::Live);
    let optional = record("memory:optional", 1, None, RecordState::Live);
    let candidate = build_qualified_candidate(
        snapshot.clone(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(&snapshot, 1, vec![id("memory:protected")], 4096, 512),
        semantic_artifact(&snapshot, 1024, 128),
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
    assert_eq!(
        candidate.checkpoint.payload_digest,
        candidate.semantic_artifact.payload_digest
    );
}

#[test]
fn tombstoned_head_is_never_replayed_or_retained() {
    let snapshot = snapshot_key();
    let live = record("memory:deleted", 1, None, RecordState::Live);
    let tombstone = record(
        "memory:deleted",
        2,
        Some(live.record_digest()),
        RecordState::Tombstone,
    );
    let candidate = build_qualified_candidate(
        snapshot.clone(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(&snapshot, 4, vec![id("memory:deleted")], 4096, 512),
        semantic_artifact(&snapshot, 1024, 128),
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
    let snapshot = snapshot_key();
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
            snapshot.clone(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(&snapshot, 4, Vec::new(), 4096, 512),
            semantic_artifact(&snapshot, 1024, 128),
            vec![input(live, 1), input(tombstone, 1), input(resurrected, 1)],
        ),
        Err(QualifiedCompactionError::ResurrectionDenied(
            "memory:resurrected".to_string()
        ))
    );
}

#[test]
fn candidate_is_order_independent() {
    let snapshot = snapshot_key();
    let inputs = vec![
        input(record("memory:a", 1, None, RecordState::Live), 3),
        input(record("memory:b", 1, None, RecordState::Live), 2),
        input(record("memory:c", 1, None, RecordState::Live), 1),
    ];
    let mut reversed = inputs.clone();
    reversed.reverse();
    let policy = policy(&snapshot, 2, Vec::new(), 4096, 512);
    let left = build_qualified_candidate(
        snapshot.clone(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy,
        semantic_artifact(&snapshot, 1024, 128),
        inputs,
    )
    .unwrap_or_else(|error| panic!("valid left candidate: {error}"));
    let right = build_qualified_candidate(
        snapshot.clone(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy,
        semantic_artifact(&snapshot, 1024, 128),
        reversed,
    )
    .unwrap_or_else(|error| panic!("valid right candidate: {error}"));
    assert_eq!(left, right);
}

#[test]
fn proof_binds_evaluator_attestation_and_all_obligations() {
    let snapshot = snapshot_key();
    let candidate = build_qualified_candidate(
        snapshot.clone(),
        generation(2),
        Some(digest("predecessor-checkpoint")),
        &policy(&snapshot, 2, Vec::new(), 4096, 512),
        semantic_artifact(&snapshot, 1024, 128),
        vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
    )
    .unwrap_or_else(|error| panic!("valid candidate: {error}"));
    let qualification = qualification();
    let mut proof = prove_compaction(&candidate, qualification.clone())
        .unwrap_or_else(|error| panic!("valid proof: {error}"));
    assert_eq!(
        proof.base_proof.checkpoint_digest,
        candidate.checkpoint.checkpoint_digest
    );
    assert_eq!(proof.evaluator_evidence.evaluator_id, id("evaluator:independent"));
    assert!(!proof.authority.grants_any());

    proof.evaluator_evidence.signature_digest = digest("tampered-signature");
    assert_eq!(
        proof.validate(),
        Err(QualifiedCompactionError::DigestMismatch("evaluator_evidence"))
    );

    let mut failed = qualification;
    failed.deletion_non_resurrection_passed = false;
    assert_eq!(
        prove_compaction(&candidate, failed),
        Err(QualifiedCompactionError::DeletionNonResurrectionFailed)
    );
}

#[test]
fn protected_set_cannot_exceed_checkpoint_capacity() {
    let snapshot = snapshot_key();
    let first = record("memory:a", 1, None, RecordState::Live);
    let second = record("memory:b", 1, None, RecordState::Live);
    assert_eq!(
        build_qualified_candidate(
            snapshot.clone(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(
                &snapshot,
                1,
                vec![id("memory:a"), id("memory:b")],
                4096,
                512,
            ),
            semantic_artifact(&snapshot, 1024, 128),
            vec![input(first, 1), input(second, 1)],
        ),
        Err(QualifiedCompactionError::ProtectedReferencesExceedCapacity)
    );
}

#[test]
fn protected_reference_missing_from_snapshot_is_rejected() {
    let snapshot = snapshot_key();
    assert_eq!(
        build_qualified_candidate(
            snapshot.clone(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(&snapshot, 2, vec![id("memory:missing")], 4096, 512),
            semantic_artifact(&snapshot, 1024, 128),
            vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
        ),
        Err(QualifiedCompactionError::ProtectedReferenceMissing(
            "memory:missing".to_string()
        ))
    );
}

#[test]
fn semantic_payload_must_fit_byte_and_token_budgets() {
    let snapshot = snapshot_key();
    let inputs = vec![input(record("memory:a", 1, None, RecordState::Live), 1)];
    assert_eq!(
        build_qualified_candidate(
            snapshot.clone(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(&snapshot, 2, Vec::new(), 512, 512),
            semantic_artifact(&snapshot, 1024, 128),
            inputs.clone(),
        ),
        Err(QualifiedCompactionError::SemanticArtifactTooLarge)
    );
    assert_eq!(
        build_qualified_candidate(
            snapshot.clone(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(&snapshot, 2, Vec::new(), 4096, 64),
            semantic_artifact(&snapshot, 1024, 128),
            inputs,
        ),
        Err(QualifiedCompactionError::SemanticArtifactTooManyTokens)
    );
}

#[test]
fn semantic_payload_is_bound_to_snapshot_model_and_tokenizer() {
    let snapshot = snapshot_key();
    let mut artifact = semantic_artifact(&snapshot, 1024, 128);
    artifact.tokenizer_digest = digest("other-tokenizer");
    artifact.artifact_digest = artifact.compute_artifact_digest();
    assert_eq!(
        build_qualified_candidate(
            snapshot.clone(),
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(&snapshot, 2, Vec::new(), 4096, 512),
            artifact,
            vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
        ),
        Err(QualifiedCompactionError::TokenizerMismatch)
    );
}
