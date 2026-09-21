use super::*;

use std::collections::BTreeMap;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Revision;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

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

fn tokenizer() -> (TrustedTokenizerV1, SigningKey) {
    let signing_key = SigningKey::from_bytes(&[5_u8; 32]);
    let trusted = TrustedTokenizerV1 {
        tokenizer_digest: digest("tokenizer"),
        implementation_digest: digest("tokenizer-implementation"),
        attestation_digest: digest("tokenizer-attestation"),
        verifying_key: signing_key.verifying_key().to_bytes(),
    };
    (trusted, signing_key)
}

fn tokenization_receipt(
    subject_digest: Digest32,
    encoded_bytes: u64,
    token_count: u64,
) -> TokenizationReceiptV1 {
    let (trusted, signing_key) = tokenizer();
    let mut receipt = TokenizationReceiptV1 {
        subject_digest,
        tokenizer_digest: trusted.tokenizer_digest,
        tokenizer_implementation_digest: trusted.implementation_digest,
        encoded_bytes,
        token_count,
        signature: [0_u8; 64],
    };
    receipt.signature = signing_key.sign(&receipt.signing_bytes()).to_bytes();
    receipt
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
    let receipt = tokenization_receipt(record.record_digest(), encoded_bytes, token_count);
    CompactionInputRecordV2 {
        retention_reason_digest: digest(&format!("reason:{}", record.record_id)),
        record,
        retention_priority: priority,
        encoded_bytes,
        token_count,
        tokenization_receipt: receipt,
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
        tokenizer_digest: digest("tokenizer"),
        tokenizer_implementation_digest: digest("tokenizer-implementation"),
        maximum_retained_records: maximum,
        maximum_retained_bytes: 4096,
        maximum_retained_tokens: 512,
        maximum_payload_bytes: 2048,
        maximum_payload_tokens: 256,
        protected_record_ids: protected,
    }
}

fn semantic_payload(
    snapshot: &CognitiveSnapshotKeyV1,
    source_memory_snapshot: &CognitiveSnapshot,
) -> CompactionSemanticPayloadV2 {
    let payload = vec![0x5a; 256];
    let payload_digest = Digest32::of_bytes(&payload);
    CompactionSemanticPayloadV2 {
        source_snapshot_digest: snapshot.vector_digest,
        source_memory_snapshot_digest: source_memory_snapshot.snapshot_digest,
        payload_digest,
        payload,
        generator_implementation_digest: digest("semantic-generator"),
        generator_receipt_digest: digest("semantic-generator-receipt"),
        tokenizer_digest: snapshot.vector.tokenizer_digest,
        encoded_bytes: 256,
        token_count: 32,
        tokenization_receipt: tokenization_receipt(payload_digest, 256, 32),
    }
}

fn source_memory_snapshot(inputs: &[CompactionInputRecordV2]) -> CognitiveSnapshot {
    let mut heads = BTreeMap::<StableId, MemoryRecord>::new();
    for input in inputs {
        heads
            .entry(input.record.record_id.clone())
            .and_modify(|record| {
                if input.record.revision > record.revision {
                    *record = input.record.clone();
                }
            })
            .or_insert_with(|| input.record.clone());
    }
    build_snapshot(generation(21), heads.into_values().collect())
        .unwrap_or_else(|error| panic!("valid source memory snapshot: {error}"))
}

fn build(
    policy: &CompactionPolicyV2,
    inputs: Vec<CompactionInputRecordV2>,
) -> Result<QualifiedCompactionCandidateV2, QualifiedCompactionError> {
    let snapshot = snapshot_key();
    let source_memory_snapshot = source_memory_snapshot(&inputs);
    let semantic = semantic_payload(&snapshot, &source_memory_snapshot);
    let (trusted_tokenizer, _) = tokenizer();
    build_qualified_candidate(
        snapshot,
        &source_memory_snapshot,
        generation(2),
        Some(digest("predecessor-checkpoint")),
        policy,
        &semantic,
        &trusted_tokenizer,
        inputs,
    )
}

fn evaluator() -> (TrustedCompactionEvaluatorV1, SigningKey) {
    let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
    let evaluator = TrustedCompactionEvaluatorV1 {
        evaluator_id: id("evaluator:independent"),
        implementation_digest: digest("evaluator-implementation"),
        attestation_digest: digest("attestation"),
        verifying_key: signing_key.verifying_key().to_bytes(),
    };
    (evaluator, signing_key)
}

fn signed_qualification(
    candidate: &QualifiedCompactionCandidateV2,
    evaluator: &TrustedCompactionEvaluatorV1,
    signing_key: &SigningKey,
) -> CompactionQualificationV2 {
    let mut qualification = CompactionQualificationV2 {
        tokenizer_implementation_digest: candidate.policy.tokenizer_implementation_digest,
        tokenizer_attestation_digest: candidate.tokenizer_attestation_digest,
        tokenizer_key_digest: candidate.tokenizer_key_digest,
        evaluator_id: evaluator.evaluator_id.clone(),
        evaluator_implementation_digest: evaluator.implementation_digest,
        evaluation_artifact_digest: digest("evaluation-artifact"),
        attestation_digest: evaluator.attestation_digest,
        retained_query_suite_digest: digest("queries"),
        reconstruction_obligation_digest: digest("reconstruction"),
        contradiction_holdout_digest: digest("contradictions"),
        retained_queries_passed: true,
        reconstruction_passed: true,
        contradictions_preserved: true,
        deletion_non_resurrection_passed: true,
        signature: [0_u8; 64],
    };
    qualification.signature = signing_key
        .sign(&qualification.signing_bytes(candidate.candidate_digest()))
        .to_bytes();
    qualification
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
    assert_eq!(candidate.retained_records().len(), 1);
    assert_eq!(
        candidate.retained_records()[0].record_id,
        id("memory:protected")
    );
    assert_eq!(candidate.loss_report().protected_retained_records, 1);
    assert_eq!(candidate.loss_report().omitted_live_records, 1);
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
    assert!(candidate.retained_records().is_empty());
    assert_eq!(candidate.loss_report().deleted_records, 1);
    assert_eq!(candidate.loss_report().protected_deleted_records, 1);
    assert_eq!(candidate.checkpoint().tombstone_cutoff, 6);
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
fn candidate_is_order_independent() {
    let inputs = vec![
        input(record("memory:a", 1, None, RecordState::Live), 3),
        input(record("memory:b", 1, None, RecordState::Live), 2),
        input(record("memory:c", 1, None, RecordState::Live), 1),
    ];
    let mut reversed = inputs.clone();
    reversed.reverse();
    let left = build(&policy(2, Vec::new()), inputs).expect("left candidate");
    let right = build(&policy(2, Vec::new()), reversed).expect("right candidate");
    assert_eq!(left, right);
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
    .expect("budgeted candidate");
    assert_eq!(
        candidate
            .retained_records()
            .iter()
            .map(|record| record.record_id.as_str())
            .collect::<Vec<_>>(),
        vec!["memory:a", "memory:c"]
    );
    assert_eq!(candidate.loss_report().retained_bytes, 80);
    assert_eq!(candidate.loss_report().retained_tokens, 8);
}

#[test]
fn forged_input_tokenization_receipt_is_rejected() {
    let mut value = input(record("memory:a", 1, None, RecordState::Live), 1);
    value.token_count = 9;
    value.tokenization_receipt.token_count = 9;
    assert_eq!(
        build(&policy(2, Vec::new()), vec![value]),
        Err(QualifiedCompactionError::InvalidTokenizerSignature)
    );
}

#[test]
fn policy_tokenizer_must_equal_source_snapshot_tokenizer() {
    let mut profile = policy(2, Vec::new());
    profile.tokenizer_digest = digest("other-tokenizer");
    assert_eq!(
        build(
            &profile,
            vec![input(record("memory:a", 1, None, RecordState::Live), 1)]
        ),
        Err(QualifiedCompactionError::TokenizerMismatch)
    );
}

#[test]
fn semantic_payload_is_snapshot_tokenizer_and_bytes_bound() {
    let snapshot = snapshot_key();
    let inputs = vec![input(record("memory:a", 1, None, RecordState::Live), 1)];
    let source_memory_snapshot = source_memory_snapshot(&inputs);
    let mut semantic = semantic_payload(&snapshot, &source_memory_snapshot);
    semantic.payload[0] ^= 1;
    let (trusted_tokenizer, _) = tokenizer();
    assert_eq!(
        build_qualified_candidate(
            snapshot,
            &source_memory_snapshot,
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(2, Vec::new()),
            &semantic,
            &trusted_tokenizer,
            inputs,
        ),
        Err(QualifiedCompactionError::SemanticPayloadDigestMismatch)
    );
}

#[test]
fn source_snapshot_coverage_must_match_input_heads() {
    let snapshot = snapshot_key();
    let source_inputs = vec![input(record("memory:a", 1, None, RecordState::Live), 1)];
    let source_memory_snapshot = source_memory_snapshot(&source_inputs);
    let semantic = semantic_payload(&snapshot, &source_memory_snapshot);
    let inputs = vec![
        input(record("memory:a", 1, None, RecordState::Live), 1),
        input(record("memory:b", 1, None, RecordState::Live), 1),
    ];
    let (trusted_tokenizer, _) = tokenizer();
    assert_eq!(
        build_qualified_candidate(
            snapshot,
            &source_memory_snapshot,
            generation(2),
            Some(digest("predecessor-checkpoint")),
            &policy(2, Vec::new()),
            &semantic,
            &trusted_tokenizer,
            inputs,
        ),
        Err(QualifiedCompactionError::SourceSnapshotCoverageMismatch)
    );
}

#[test]
fn proof_requires_host_trusted_ed25519_evaluator() {
    let candidate = build(
        &policy(2, Vec::new()),
        vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
    )
    .expect("candidate");
    let (evaluator, signing_key) = evaluator();
    let qualification = signed_qualification(&candidate, &evaluator, &signing_key);
    let proof = prove_compaction(&candidate, &evaluator, qualification.clone())
        .expect("valid signed proof");
    assert_eq!(
        proof.checkpoint_digest,
        candidate.checkpoint().checkpoint_digest
    );
    assert_eq!(proof.candidate_digest, candidate.candidate_digest());
    assert_eq!(proof.evaluator_id, evaluator.evaluator_id);
    assert_eq!(
        proof.attestation_signature_digest,
        Digest32::of_bytes(&qualification.signature)
    );
    assert!(!proof.signature_verification_receipt_digest.is_zero());
}

#[test]
fn tampered_evaluator_qualification_signature_is_rejected() {
    let candidate = build(
        &policy(2, Vec::new()),
        vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
    )
    .expect("candidate");
    let (evaluator, signing_key) = evaluator();
    let mut qualification = signed_qualification(&candidate, &evaluator, &signing_key);
    qualification.evaluation_artifact_digest = digest("tampered");
    assert_eq!(
        prove_compaction(&candidate, &evaluator, qualification),
        Err(QualifiedCompactionError::InvalidEvaluatorSignature)
    );
}

#[test]
fn failing_deletion_obligation_never_produces_proof() {
    let candidate = build(
        &policy(2, Vec::new()),
        vec![input(record("memory:a", 1, None, RecordState::Live), 1)],
    )
    .expect("candidate");
    let (evaluator, signing_key) = evaluator();
    let mut qualification = signed_qualification(&candidate, &evaluator, &signing_key);
    qualification.deletion_non_resurrection_passed = false;
    qualification.signature = signing_key
        .sign(&qualification.signing_bytes(candidate.candidate_digest()))
        .to_bytes();
    assert_eq!(
        prove_compaction(&candidate, &evaluator, qualification),
        Err(QualifiedCompactionError::DeletionNonResurrectionFailed)
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

    let mut profile = policy(RETAINED_RECORDS, Vec::new());
    profile.policy_id = id("policy:compact:large");
    profile.algorithm_digest = digest("algorithm:large");
    profile.compatibility_digest = digest("compatibility:large");
    profile.maximum_retained_bytes = u64::from(RETAINED_RECORDS) * RECORD_BYTES;
    profile.maximum_retained_tokens = u64::from(RETAINED_RECORDS) * RECORD_TOKENS;

    let left = build(&profile, inputs).expect("large candidate");
    let right = build(&profile, reversed).expect("order-independent large candidate");
    assert_eq!(left, right);
    assert_eq!(
        left.loss_report().retained_records,
        u64::from(RETAINED_RECORDS)
    );
    assert_eq!(
        left.loss_report().retained_bytes,
        u64::from(RETAINED_RECORDS) * RECORD_BYTES
    );
}
