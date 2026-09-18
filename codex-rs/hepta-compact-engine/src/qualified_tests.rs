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

fn input_with_cost(
    record: MemoryRecord,
    priority: u32,
    encoded_bytes: u64,
    token_count: u64,
) -> CompactionInputRecordV2 {
    CompactionInputRecordV2 {
        retention_reason_digest: digest(&format!("reason:{}", record.record_id)),
        record,
        retention_priority: priority,
        encoded_bytes,
        token_count,
    }
}

fn input(record: MemoryRecord, priority: u32) -> CompactionInputRecordV2 {
    input_with_cost(record, priority, 64, 8)
}

fn policy(maximum: u32, protected: Vec<StableId>) -> CompactionPolicyV2 {
    CompactionPolicyV2 {
        policy_id: id("policy:compact"),
        algorithm_digest: digest("algorithm"),
        compatibility_digest: digest("compatibility"),
        maximum_retained_records: maximum,
        maximum_retained_bytes: 4096,
        maximum_retained_tokens: 512,
        maximum_payload_bytes: 2048,
        maximum_payload_tokens: 256,
        protected_record_ids: protected,
    }
}

fn semantic_payload(snapshot: &CognitiveSnapshotKeyV1) -> CompactionSemanticPayloadV2 {
    CompactionSemanticPayloadV2 {
        source_snapshot_digest: snapshot.vector_digest,
        payload_digest: digest("semantic-payload"),
        generator_implementation_digest: digest("semantic-generator"),
        generator_receipt_digest: digest("semantic-generator-receipt"),
        tokenizer_digest: snapshot.vector.tokenizer_digest,
        encoded_bytes: 256,
        token_count: 32,
    }
}

fn build(
    policy: &CompactionPolicyV2,
    inputs: Vec<CompactionInputRecordV2>,
) -> Result<QualifiedCompactionCandidateV2, QualifiedCompactionError> {
    let snapshot = snapshot_key();
    let semantic = semantic_payload(&snapshot);
    build_qualified_candidate(
        snapshot,
        generation(2),
        Some(digest("predecessor-checkpoint")),
        policy,
        &semantic,
        inputs,
    )
}

fn qualification() -> CompactionQualificationV2 {
    CompactionQualificationV2 {
        evaluator_id: id("evaluator:independent"),
        evaluator_implementation_digest: digest("evaluator-implementation"),
        evaluation_artifact_digest: digest("evaluation-artifact"),
        attestation_digest: digest("attestation"),
        attestation_signature_digest: digest("attestation-signature"),
        signature_verification_receipt_digest: digest("signature-verification-receipt"),
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
    let candidate = build(
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
    let candidate = build(
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
fn canonical_path_rejects_live_tombstone_live_resurrection() {
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
        build(
            &policy(4, Vec::new()),
            vec![input(live, 1), input(tombstone, 1), input(resurrected, 1)],
        ),
        Err(QualifiedCompactionError::ResurrectionDenied(
            "memory:resurrected".to_string()
        ))
    );
}

#[test]
fn checkpoint_generation_must_succeed_source_snapshot_generation() {
    let source_snapshot = snapshot_key();
    let semantic = semantic_payload(&source_snapshot);
    assert_eq!(
        build_qualified_candidate(
            source_snapshot,
            generation(3),
            Some(digest("skipped-predecessor")),
            &policy(2, Vec::new()),
            &semantic,
            vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
        ),
        Err(QualifiedCompactionError::CheckpointGenerationMismatch)
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
    let left = build(&policy(2, Vec::new()), inputs)
        .unwrap_or_else(|error| panic!("valid left candidate: {error}"));
    let right = build(&policy(2, Vec::new()), reversed)
        .unwrap_or_else(|error| panic!("valid right candidate: {error}"));
    assert_eq!(left, right);
}

#[test]
fn proof_binds_evaluator_attestation_and_candidate_identity() {
    let candidate = build(
        &policy(2, Vec::new()),
        vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
    )
    .unwrap_or_else(|error| panic!("valid candidate: {error}"));
    let qualification = qualification();
    let proof = prove_compaction(&candidate, qualification.clone())
        .unwrap_or_else(|error| panic!("valid proof: {error}"));
    assert_eq!(
        proof.checkpoint_digest,
        candidate.checkpoint.checkpoint_digest
    );
    assert_eq!(proof.candidate_digest, candidate.candidate_digest);
    assert_eq!(proof.evaluator_id, id("evaluator:independent"));
    assert_eq!(
        proof.attestation_signature_digest,
        qualification.attestation_signature_digest
    );
    assert_eq!(
        proof.signature_verification_receipt_digest,
        qualification.signature_verification_receipt_digest
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
        build(
            &policy(1, vec![id("memory:a"), id("memory:b")]),
            vec![input(first, 1), input(second, 1)],
        ),
        Err(QualifiedCompactionError::ProtectedReferencesExceedCapacity)
    );
}

#[test]
fn missing_protected_reference_fails_closed() {
    assert_eq!(
        build(
            &policy(2, vec![id("memory:missing")]),
            vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
        ),
        Err(QualifiedCompactionError::ProtectedReferenceMissing(
            "memory:missing".to_string()
        ))
    );
}

#[test]
fn retained_byte_and_token_budgets_are_enforced() {
    let mut bounded = policy(3, Vec::new());
    bounded.maximum_retained_bytes = 80;
    bounded.maximum_retained_tokens = 8;
    let candidate = build(
        &bounded,
        vec![
            input_with_cost(record("memory:a", 1, None, RecordState::Live), 3, 60, 6),
            input_with_cost(record("memory:b", 1, None, RecordState::Live), 2, 50, 5),
            input_with_cost(record("memory:c", 1, None, RecordState::Live), 1, 20, 2),
        ],
    )
    .unwrap_or_else(|error| panic!("budgeted candidate: {error}"));
    assert_eq!(
        candidate
            .retained_records
            .iter()
            .map(|record| record.record_id.as_str())
            .collect::<Vec<_>>(),
        vec!["memory:a", "memory:c"]
    );
    assert_eq!(candidate.loss_report.retained_bytes, 80);
    assert_eq!(candidate.loss_report.retained_tokens, 8);
    assert_eq!(candidate.loss_report.omitted_live_records, 1);
}

#[test]
fn protected_record_must_fit_combined_resource_budget() {
    let mut bounded = policy(2, vec![id("memory:protected")]);
    bounded.maximum_retained_bytes = 32;
    bounded.maximum_retained_tokens = 4;
    assert_eq!(
        build(
            &bounded,
            vec![input_with_cost(
                record("memory:protected", 1, None, RecordState::Live),
                1,
                64,
                8,
            )],
        ),
        Err(QualifiedCompactionError::ProtectedReferencesExceedCapacity)
    );
}

#[test]
fn semantic_payload_is_snapshot_and_tokenizer_bound() {
    let snapshot = snapshot_key();
    let mut semantic = semantic_payload(&snapshot);
    semantic.tokenizer_digest = digest("different-tokenizer");
    assert_eq!(
        build_qualified_candidate(
            snapshot,
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(2, Vec::new()),
            &semantic,
            vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
        ),
        Err(QualifiedCompactionError::TokenizerMismatch)
    );
}

#[test]
fn semantic_payload_output_budget_is_enforced() {
    let snapshot = snapshot_key();
    let mut bounded = policy(2, Vec::new());
    bounded.maximum_payload_bytes = 128;
    let semantic = semantic_payload(&snapshot);
    assert_eq!(
        build_qualified_candidate(
            snapshot,
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &bounded,
            &semantic,
            vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
        ),
        Err(QualifiedCompactionError::PayloadBudgetExceeded)
    );
}

#[test]
fn qualification_requires_signature_verification_receipt() {
    let candidate = build(
        &policy(2, Vec::new()),
        vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
    )
    .unwrap_or_else(|error| panic!("valid candidate: {error}"));
    let mut qualification = qualification();
    qualification.signature_verification_receipt_digest = Digest32::ZERO;
    assert_eq!(
        prove_compaction(&candidate, qualification),
        Err(QualifiedCompactionError::EmptyDigest(
            "signature_verification_receipt"
        ))
    );
}


#[test]
fn large_input_remains_deterministic_and_bounded() {
    const SOURCE_RECORDS: usize = 4_096;
    const RETAINED_RECORDS: u32 = 512;
    const RECORD_BYTES: u64 = 32;
    const RECORD_TOKENS: u64 = 4;

    let inputs = (0..SOURCE_RECORDS)
        .map(|index| {
            input_with_cost(
                record(
                    &format!("memory:bulk:{index:04}"),
                    1,
                    None,
                    RecordState::Live,
                ),
                u32::try_from(SOURCE_RECORDS - index).expect("bounded priority"),
                RECORD_BYTES,
                RECORD_TOKENS,
            )
        })
        .collect::<Vec<_>>();
    let mut reversed = inputs.clone();
    reversed.reverse();

    let policy = CompactionPolicyV2 {
        policy_id: id("policy:compact:large"),
        algorithm_digest: digest("algorithm:large"),
        compatibility_digest: digest("compatibility:large"),
        maximum_retained_records: RETAINED_RECORDS,
        maximum_retained_bytes: u64::from(RETAINED_RECORDS) * RECORD_BYTES,
        maximum_retained_tokens: u64::from(RETAINED_RECORDS) * RECORD_TOKENS,
        maximum_payload_bytes: 2_048,
        maximum_payload_tokens: 256,
        protected_record_ids: Vec::new(),
    };
    let left = build(&policy, inputs).expect("large candidate");
    let right = build(&policy, reversed).expect("order-independent large candidate");

    assert_eq!(left, right);
    let source_records = u64::try_from(SOURCE_RECORDS).expect("bounded source count");
    assert_eq!(left.loss_report.live_source_heads, source_records);
    assert_eq!(
        left.loss_report.retained_records,
        u64::from(RETAINED_RECORDS)
    );
    assert_eq!(
        left.loss_report.omitted_live_records,
        source_records - u64::from(RETAINED_RECORDS)
    );
    assert_eq!(
        left.loss_report.retained_bytes,
        u64::from(RETAINED_RECORDS) * RECORD_BYTES
    );
    assert_eq!(
        left.loss_report.retained_tokens,
        u64::from(RETAINED_RECORDS) * RECORD_TOKENS
    );
}
