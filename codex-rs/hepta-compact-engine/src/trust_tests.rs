use super::*;

use std::collections::BTreeMap;

use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Revision;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::qualified::CompactionInputRecordV2;
use crate::qualified::CompactionPolicyV2;
use crate::qualified::CompactionQualificationV2;
use crate::qualified::CompactionSemanticPayloadV2;
use crate::qualified::QualifiedCompactionCandidateV2;
use crate::qualified::TokenizationReceiptV1;

const NOW: u64 = 1_800_000_000;

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

fn enrollment(
    role: CompactionTrustRoleV1,
    key_id: &str,
    epoch: u64,
    signing_key: &SigningKey,
) -> TrustEnrollmentV1 {
    TrustEnrollmentV1 {
        schema_version: COMPACTION_TRUST_SCHEMA_VERSION,
        role,
        key_id: id(key_id),
        trust_epoch: epoch,
        valid_from_unix_seconds: NOW - 100,
        valid_until_unix_seconds: NOW + 1_000,
        revoked_at_unix_seconds: None,
        predecessor_key_digest: None,
        implementation_digest: digest(&format!("{key_id}:implementation")),
        attestation_digest: digest(&format!("{key_id}:attestation")),
        verifying_key: signing_key.verifying_key().to_bytes(),
    }
}

fn snapshot_key() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:trust"),
        purpose_id: id("purpose:compaction"),
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
    .unwrap_or_else(|error| panic!("valid snapshot: {error}"))
}

fn record(record_id: &str, state: RecordState) -> MemoryRecord {
    MemoryRecord {
        record_id: id(record_id),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest(&format!("{record_id}:{state:?}")),
        predecessor_digest: None,
        citations: Vec::new(),
        state,
    }
}

fn tokenization_receipt(
    tokenizer: &TrustedTokenizerV1,
    signing_key: &SigningKey,
    subject_digest: Digest32,
    encoded_bytes: u64,
    token_count: u64,
) -> TokenizationReceiptV1 {
    let mut receipt = TokenizationReceiptV1 {
        subject_digest,
        tokenizer_digest: tokenizer.tokenizer_digest,
        tokenizer_implementation_digest: tokenizer.enrollment.implementation_digest,
        encoded_bytes,
        token_count,
        signature: [0_u8; 64],
    };
    receipt.signature = signing_key.sign(&receipt.signing_bytes()).to_bytes();
    receipt
}

fn input(
    tokenizer: &TrustedTokenizerV1,
    signing_key: &SigningKey,
    record_id: &str,
    priority: u32,
) -> CompactionInputRecordV2 {
    let record = record(record_id, RecordState::Live);
    CompactionInputRecordV2 {
        tokenization_receipt: tokenization_receipt(
            tokenizer,
            signing_key,
            record.record_digest(),
            64,
            8,
        ),
        retention_reason_digest: digest(&format!("reason:{record_id}")),
        record,
        retention_priority: priority,
        encoded_bytes: 64,
        token_count: 8,
    }
}

fn source_memory_snapshot(inputs: &[CompactionInputRecordV2]) -> CognitiveSnapshot {
    let mut heads = BTreeMap::<StableId, MemoryRecord>::new();
    for input in inputs {
        heads.insert(input.record.record_id.clone(), input.record.clone());
    }
    build_snapshot(generation(21), heads.into_values().collect())
        .unwrap_or_else(|error| panic!("valid memory snapshot: {error}"))
}

struct Fixture {
    source_snapshot: CognitiveSnapshotKeyV1,
    source_memory_snapshot: CognitiveSnapshot,
    policy: CompactionPolicyV2,
    semantic_payload: CompactionSemanticPayloadV2,
    inputs: Vec<CompactionInputRecordV2>,
    selector: TrustedRetentionSelectorV1,
    selection_receipt: SignedRetentionSelectionReceiptV1,
    generator: TrustedSemanticGeneratorV1,
    generation_receipt: SignedSemanticGenerationReceiptV1,
    tokenizer: TrustedTokenizerV1,
    evaluator: TrustedCompactionEvaluatorV1,
    evaluator_signing_key: SigningKey,
}

fn fixture() -> Fixture {
    let selector_signing_key = SigningKey::from_bytes(&[1_u8; 32]);
    let generator_signing_key = SigningKey::from_bytes(&[2_u8; 32]);
    let tokenizer_signing_key = SigningKey::from_bytes(&[3_u8; 32]);
    let evaluator_signing_key = SigningKey::from_bytes(&[4_u8; 32]);

    let selector = TrustedRetentionSelectorV1 {
        enrollment: enrollment(
            CompactionTrustRoleV1::RetentionSelector,
            "selector:key:1",
            1,
            &selector_signing_key,
        ),
    };
    let generator = TrustedSemanticGeneratorV1 {
        enrollment: enrollment(
            CompactionTrustRoleV1::SemanticGenerator,
            "generator:key:1",
            1,
            &generator_signing_key,
        ),
    };
    let tokenizer = TrustedTokenizerV1 {
        enrollment: enrollment(
            CompactionTrustRoleV1::Tokenizer,
            "tokenizer:key:1",
            1,
            &tokenizer_signing_key,
        ),
        tokenizer_digest: digest("tokenizer"),
    };
    let evaluator = TrustedCompactionEvaluatorV1 {
        enrollment: enrollment(
            CompactionTrustRoleV1::Evaluator,
            "evaluator:key:1",
            1,
            &evaluator_signing_key,
        ),
        evaluator_id: id("evaluator:independent"),
    };

    let source_snapshot = snapshot_key();
    let inputs = vec![
        input(&tokenizer, &tokenizer_signing_key, "memory:a", 3),
        input(&tokenizer, &tokenizer_signing_key, "memory:b", 2),
        input(&tokenizer, &tokenizer_signing_key, "memory:c", 1),
    ];
    let source_memory_snapshot = source_memory_snapshot(&inputs);
    let policy = CompactionPolicyV2 {
        policy_id: id("policy:trusted"),
        algorithm_digest: digest("algorithm"),
        compatibility_digest: digest("compatibility"),
        tokenizer_digest: tokenizer.tokenizer_digest,
        tokenizer_implementation_digest: tokenizer.enrollment.implementation_digest,
        maximum_retained_records: 2,
        maximum_retained_bytes: 128,
        maximum_retained_tokens: 16,
        maximum_payload_bytes: 2_048,
        maximum_payload_tokens: 256,
        protected_record_ids: vec![id("memory:a")],
    };

    let mut selection_receipt = SignedRetentionSelectionReceiptV1 {
        schema_version: COMPACTION_TRUST_SCHEMA_VERSION,
        key_id: selector.enrollment.key_id.clone(),
        trust_epoch: selector.enrollment.trust_epoch,
        issued_at_unix_seconds: NOW - 10,
        expires_at_unix_seconds: NOW + 100,
        nonce: digest("selection:nonce"),
        source_snapshot_digest: source_snapshot.vector_digest,
        source_memory_snapshot_digest: source_memory_snapshot.snapshot_digest,
        policy_digest: policy.digest(),
        input_manifest_digest: compaction_input_manifest_digest(&inputs),
        tokenizer_key_id: tokenizer.enrollment.key_id.clone(),
        tokenizer_trust_epoch: tokenizer.enrollment.trust_epoch,
        tokenizer_key_digest: tokenizer.enrollment.key_digest(),
        signature: [0_u8; 64],
    };
    selection_receipt.signature = selector_signing_key
        .sign(&selection_receipt.signing_bytes())
        .to_bytes();

    let payload = vec![0x5a; 256];
    let payload_digest = Digest32::of_bytes(&payload);
    let payload_tokenization_receipt = tokenization_receipt(
        &tokenizer,
        &tokenizer_signing_key,
        payload_digest,
        256,
        32,
    );
    let mut semantic_payload = CompactionSemanticPayloadV2 {
        source_snapshot_digest: source_snapshot.vector_digest,
        source_memory_snapshot_digest: source_memory_snapshot.snapshot_digest,
        payload_digest,
        payload,
        generator_implementation_digest: generator.enrollment.implementation_digest,
        generator_receipt_digest: digest("placeholder"),
        tokenizer_digest: tokenizer.tokenizer_digest,
        encoded_bytes: 256,
        token_count: 32,
        tokenization_receipt: payload_tokenization_receipt,
    };
    let mut generation_receipt = SignedSemanticGenerationReceiptV1 {
        schema_version: COMPACTION_TRUST_SCHEMA_VERSION,
        key_id: generator.enrollment.key_id.clone(),
        trust_epoch: generator.enrollment.trust_epoch,
        issued_at_unix_seconds: NOW - 9,
        expires_at_unix_seconds: NOW + 100,
        nonce: digest("generation:nonce"),
        source_snapshot_digest: source_snapshot.vector_digest,
        source_memory_snapshot_digest: source_memory_snapshot.snapshot_digest,
        policy_digest: policy.digest(),
        selection_receipt_digest: selection_receipt.receipt_digest(),
        payload_digest,
        tokenizer_key_id: tokenizer.enrollment.key_id.clone(),
        tokenizer_trust_epoch: tokenizer.enrollment.trust_epoch,
        tokenizer_key_digest: tokenizer.enrollment.key_digest(),
        tokenization_receipt_digest: semantic_payload
            .tokenization_receipt
            .receipt_digest(),
        signature: [0_u8; 64],
    };
    generation_receipt.signature = generator_signing_key
        .sign(&generation_receipt.signing_bytes())
        .to_bytes();
    semantic_payload.generator_receipt_digest = generation_receipt.receipt_digest();

    Fixture {
        source_snapshot,
        source_memory_snapshot,
        policy,
        semantic_payload,
        inputs,
        selector,
        selection_receipt,
        generator,
        generation_receipt,
        tokenizer,
        evaluator,
        evaluator_signing_key,
    }
}

fn build(fixture: &Fixture) -> Result<QualifiedCompactionCandidateV2, TrustedCompactionError> {
    build_qualified_candidate(QualifiedCandidateBuildRequestV1 {
        source_snapshot: fixture.source_snapshot.clone(),
        source_memory_snapshot: &fixture.source_memory_snapshot,
        generation: generation(2),
        predecessor_checkpoint_digest: Some(digest("predecessor")),
        policy: &fixture.policy,
        semantic_payload: &fixture.semantic_payload,
        selector: &fixture.selector,
        selection_receipt: &fixture.selection_receipt,
        generator: &fixture.generator,
        generation_receipt: &fixture.generation_receipt,
        tokenizer: &fixture.tokenizer,
        inputs: fixture.inputs.clone(),
        verification_time_unix_seconds: NOW,
    })
}

fn qualification(
    fixture: &Fixture,
    candidate: &QualifiedCompactionCandidateV2,
) -> CompactionQualificationV2 {
    let mut value = CompactionQualificationV2 {
        tokenizer_implementation_digest: fixture.tokenizer.enrollment.implementation_digest,
        tokenizer_attestation_digest: fixture.tokenizer.enrollment.attestation_digest,
        tokenizer_key_digest: fixture.tokenizer.enrollment.key_digest(),
        evaluator_id: fixture.evaluator.evaluator_id.clone(),
        evaluator_implementation_digest: fixture.evaluator.enrollment.implementation_digest,
        evaluation_artifact_digest: digest("evaluation-artifact"),
        attestation_digest: fixture.evaluator.enrollment.attestation_digest,
        retained_query_suite_digest: digest("retained-queries"),
        reconstruction_obligation_digest: digest("reconstruction"),
        contradiction_holdout_digest: digest("contradiction-holdout"),
        retained_queries_passed: true,
        reconstruction_passed: true,
        contradictions_preserved: true,
        deletion_non_resurrection_passed: true,
        signature: [0_u8; 64],
    };
    value.signature = fixture
        .evaluator_signing_key
        .sign(&value.signing_bytes(candidate.candidate_digest()))
        .to_bytes();
    value
}

fn evaluation_receipt(
    fixture: &Fixture,
    candidate: &QualifiedCompactionCandidateV2,
    qualification: &CompactionQualificationV2,
) -> SignedCompactionEvaluationReceiptV1 {
    let mut receipt = SignedCompactionEvaluationReceiptV1 {
        schema_version: COMPACTION_TRUST_SCHEMA_VERSION,
        key_id: fixture.evaluator.enrollment.key_id.clone(),
        trust_epoch: fixture.evaluator.enrollment.trust_epoch,
        issued_at_unix_seconds: NOW - 5,
        expires_at_unix_seconds: NOW + 100,
        nonce: digest("evaluation:nonce"),
        candidate_digest: candidate.candidate_digest(),
        qualification_digest: compaction_qualification_digest(
            candidate.candidate_digest(),
            qualification,
        ),
        signature: [0_u8; 64],
    };
    receipt.signature = fixture
        .evaluator_signing_key
        .sign(&receipt.signing_bytes())
        .to_bytes();
    receipt
}

#[test]
fn canonical_public_path_requires_all_four_trusted_roles() {
    let fixture = fixture();
    let candidate = build(&fixture).expect("trusted candidate");
    let qualification = qualification(&fixture, &candidate);
    let receipt = evaluation_receipt(&fixture, &candidate, &qualification);
    let output = prove_compaction(TrustedCompactionProofRequestV1 {
        candidate: &candidate,
        evaluator: &fixture.evaluator,
        qualification,
        evaluation_receipt: &receipt,
        verification_time_unix_seconds: NOW,
    })
    .expect("trusted proof");

    assert_eq!(output.proof.candidate_digest, candidate.candidate_digest());
    assert_eq!(
        output.evaluation_receipt_digest,
        receipt.receipt_digest()
    );
    assert_eq!(
        output.evaluator_key_id,
        fixture.evaluator.enrollment.key_id
    );
    output
        .witness
        .verify_proof(&output.proof)
        .expect("reopen witness");
}

#[test]
fn selector_receipt_tampering_is_rejected_before_kernel_entry() {
    let mut fixture = fixture();
    fixture.selection_receipt.policy_digest = digest("tampered-policy");
    assert_eq!(
        build(&fixture),
        Err(TrustedCompactionError::BindingMismatch(
            "retention selection"
        ))
    );
}

#[test]
fn semantic_generator_receipt_must_bind_exact_payload_and_tokenizer() {
    let mut fixture = fixture();
    fixture.semantic_payload.generator_receipt_digest = digest("forged-receipt");
    assert_eq!(
        build(&fixture),
        Err(TrustedCompactionError::BindingMismatch(
            "semantic generation"
        ))
    );
}

#[test]
fn zero_nonce_is_rejected_as_replayable() {
    let mut fixture = fixture();
    fixture.selection_receipt.nonce = Digest32::ZERO;
    assert_eq!(
        build(&fixture),
        Err(TrustedCompactionError::InvalidReplayNonce)
    );
}

#[test]
fn evaluator_admission_tampering_is_rejected() {
    let fixture = fixture();
    let candidate = build(&fixture).expect("trusted candidate");
    let qualification = qualification(&fixture, &candidate);
    let mut receipt = evaluation_receipt(&fixture, &candidate, &qualification);
    receipt.qualification_digest = digest("tampered-qualification");

    assert_eq!(
        prove_compaction(TrustedCompactionProofRequestV1 {
            candidate: &candidate,
            evaluator: &fixture.evaluator,
            qualification,
            evaluation_receipt: &receipt,
            verification_time_unix_seconds: NOW,
        }),
        Err(TrustedCompactionError::BindingMismatch(
            "compaction evaluation"
        ))
    );
}

#[test]
fn revoked_key_is_denied_for_current_use_but_preserves_prior_historical_acceptance() {
    let mut fixture = fixture();
    fixture.selector.enrollment.revoked_at_unix_seconds = Some(NOW - 1);
    assert_eq!(
        build(&fixture),
        Err(TrustedCompactionError::TrustRevoked)
    );

    fixture
        .selection_receipt
        .verify_historical(
            &fixture.selector,
            &fixture.tokenizer,
            &fixture.source_snapshot,
            &fixture.source_memory_snapshot,
            &fixture.policy,
            &fixture.inputs,
            NOW - 2,
        )
        .expect("receipt accepted before revocation remains historically verifiable");
}

#[test]
fn rotation_requires_monotonic_epoch_and_predecessor_key_digest() {
    let old_key = SigningKey::from_bytes(&[8_u8; 32]);
    let new_key = SigningKey::from_bytes(&[9_u8; 32]);
    let old = enrollment(
        CompactionTrustRoleV1::SemanticGenerator,
        "generator:key:old",
        4,
        &old_key,
    );
    let mut new = enrollment(
        CompactionTrustRoleV1::SemanticGenerator,
        "generator:key:new",
        5,
        &new_key,
    );
    new.predecessor_key_digest = Some(old.key_digest());
    new.validate_rotation_from(&old)
        .expect("valid rotation");

    new.predecessor_key_digest = Some(digest("wrong-predecessor"));
    assert_eq!(
        new.validate_rotation_from(&old),
        Err(TrustedCompactionError::InvalidTrustRotation)
    );
}

#[test]
fn trusted_selection_is_order_independent() {
    let fixture = fixture();
    let left = build(&fixture).expect("left");

    let mut reversed = fixture.inputs.clone();
    reversed.reverse();
    let right = build_qualified_candidate(QualifiedCandidateBuildRequestV1 {
        source_snapshot: fixture.source_snapshot.clone(),
        source_memory_snapshot: &fixture.source_memory_snapshot,
        generation: generation(2),
        predecessor_checkpoint_digest: Some(digest("predecessor")),
        policy: &fixture.policy,
        semantic_payload: &fixture.semantic_payload,
        selector: &fixture.selector,
        selection_receipt: &fixture.selection_receipt,
        generator: &fixture.generator,
        generation_receipt: &fixture.generation_receipt,
        tokenizer: &fixture.tokenizer,
        inputs: reversed,
        verification_time_unix_seconds: NOW,
    })
    .expect("right");

    assert_eq!(left, right);
}
