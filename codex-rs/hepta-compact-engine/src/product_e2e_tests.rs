use std::collections::BTreeMap;

use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_cognitive_types::{
    CognitiveSnapshot, MemoryKind, MemoryRecord, RecordState, build_snapshot,
};
use codex_hepta_types::{Digest32, Generation, Revision, StableId};
use ed25519_dalek::{Signer, SigningKey};
use tempfile::TempDir;

use crate::*;

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
    signing_key: &SigningKey,
) -> TrustEnrollmentV1 {
    TrustEnrollmentV1 {
        schema_version: COMPACTION_TRUST_SCHEMA_VERSION,
        role,
        key_id: id(key_id),
        trust_epoch: 1,
        valid_from_unix_seconds: NOW - 100,
        valid_until_unix_seconds: NOW + 10_000,
        revoked_at_unix_seconds: None,
        predecessor_key_digest: None,
        implementation_digest: digest(&format!("{key_id}:implementation")),
        attestation_digest: digest(&format!("{key_id}:attestation")),
        verifying_key: signing_key.verifying_key().to_bytes(),
    }
}

struct ProductTrustFixture {
    root: SigningKey,
    selector_key: SigningKey,
    generator_key: SigningKey,
    tokenizer_key: SigningKey,
    evaluator_key: SigningKey,
    selector: TrustedRetentionSelectorV1,
    generator: TrustedSemanticGeneratorV1,
    tokenizer: TrustedTokenizerV1,
    evaluator: TrustedCompactionEvaluatorV1,
    registry: VerifiedCompactionTrustRegistryV1,
    manifest_bytes: Vec<u8>,
}

impl ProductTrustFixture {
    fn new(owner_id: &StableId) -> Self {
        let root = SigningKey::from_bytes(&[29_u8; 32]);
        let selector_key = SigningKey::from_bytes(&[31_u8; 32]);
        let generator_key = SigningKey::from_bytes(&[37_u8; 32]);
        let tokenizer_key = SigningKey::from_bytes(&[41_u8; 32]);
        let evaluator_key = SigningKey::from_bytes(&[43_u8; 32]);
        let selector = TrustedRetentionSelectorV1 {
            enrollment: enrollment(
                CompactionTrustRoleV1::RetentionSelector,
                "selector:e2e:key",
                &selector_key,
            ),
        };
        let generator = TrustedSemanticGeneratorV1 {
            enrollment: enrollment(
                CompactionTrustRoleV1::SemanticGenerator,
                "generator:e2e:key",
                &generator_key,
            ),
        };
        let tokenizer = TrustedTokenizerV1 {
            enrollment: enrollment(
                CompactionTrustRoleV1::Tokenizer,
                "tokenizer:e2e:key",
                &tokenizer_key,
            ),
            tokenizer_digest: digest("tokenizer:e2e"),
        };
        let evaluator = TrustedCompactionEvaluatorV1 {
            enrollment: enrollment(
                CompactionTrustRoleV1::Evaluator,
                "evaluator:e2e:key",
                &evaluator_key,
            ),
            evaluator_id: id("evaluator:e2e:independent"),
        };
        let mut manifest = SignedCompactionTrustManifestV1 {
            schema_version: 1,
            owner_id: owner_id.clone(),
            sequence: 1,
            predecessor_manifest_digest: None,
            valid_from_unix_seconds: NOW - 100,
            valid_until_unix_seconds: NOW + 10_000,
            entries: vec![
                CompactionTrustedPrincipalV1 {
                    enrollment: selector.enrollment.clone(),
                    principal_id: id("principal:e2e:selector"),
                    subject_id: id("subject:e2e:selector"),
                    artifact_digest: selector.enrollment.implementation_digest,
                },
                CompactionTrustedPrincipalV1 {
                    enrollment: generator.enrollment.clone(),
                    principal_id: id("principal:e2e:generator"),
                    subject_id: id("subject:e2e:generator"),
                    artifact_digest: digest("model:e2e"),
                },
                CompactionTrustedPrincipalV1 {
                    enrollment: tokenizer.enrollment.clone(),
                    principal_id: id("principal:e2e:tokenizer"),
                    subject_id: id("subject:e2e:tokenizer"),
                    artifact_digest: tokenizer.tokenizer_digest,
                },
                CompactionTrustedPrincipalV1 {
                    enrollment: evaluator.enrollment.clone(),
                    principal_id: id("principal:e2e:evaluator"),
                    subject_id: evaluator.evaluator_id.clone(),
                    artifact_digest: digest("evaluation-profile:e2e"),
                },
            ],
            signature: [0_u8; 64],
        };
        manifest.signature = root
            .sign(&manifest.signing_bytes().expect("manifest signing bytes"))
            .to_bytes();
        let manifest_bytes = manifest.encode().expect("canonical manifest");
        let registry = VerifiedCompactionTrustRegistryV1::verify(
            root.verifying_key().to_bytes(),
            &manifest_bytes,
        )
        .expect("verified registry");
        Self {
            root,
            selector_key,
            generator_key,
            tokenizer_key,
            evaluator_key,
            selector,
            generator,
            tokenizer,
            evaluator,
            registry,
            manifest_bytes,
        }
    }
}

fn snapshot_key(
    compact_generation: u64,
    frontier: u64,
) -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:e2e"),
        purpose_id: id("purpose:e2e"),
        memory_ledger_frontier: frontier,
        knowledge_fact_frontier: frontier,
        tombstone_frontier: frontier.saturating_sub(1),
        source_ledger_frontier: frontier,
        knowledge_graph_generation: generation(frontier),
        compact_checkpoint_generation: generation(compact_generation),
        prompt_registry_revision: revision(frontier),
        retrieval_profile_digest: digest("retrieval:e2e"),
        encoder_preprocessor_digest: digest("encoder:e2e"),
        authority_epoch: frontier,
        model_digest: digest("model:e2e"),
        tokenizer_digest: digest("tokenizer:e2e"),
        template_digest: digest("template:e2e"),
        tool_schema_digest: digest("tools:e2e"),
    })
    .expect("snapshot key")
}

fn record(record_id: &str, revision_value: u64) -> MemoryRecord {
    MemoryRecord {
        record_id: id(record_id),
        revision: revision(revision_value),
        kind: MemoryKind::Fact,
        content_digest: digest(&format!("{record_id}:content:{revision_value}")),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    }
}

fn tokenization_receipt(
    fixture: &ProductTrustFixture,
    subject_digest: Digest32,
    encoded_bytes: u64,
    token_count: u64,
) -> TokenizationReceiptV1 {
    let mut receipt = TokenizationReceiptV1 {
        subject_digest,
        tokenizer_digest: fixture.tokenizer.tokenizer_digest,
        tokenizer_implementation_digest: fixture
            .tokenizer
            .enrollment
            .implementation_digest,
        encoded_bytes,
        token_count,
        signature: [0_u8; 64],
    };
    receipt.signature = fixture
        .tokenizer_key
        .sign(&receipt.signing_bytes())
        .to_bytes();
    receipt
}

fn sealed_publication(
    fixture: &ProductTrustFixture,
    record_ids: &[&str],
    compact_generation: u64,
    checkpoint_generation: u64,
    predecessor: Option<Digest32>,
    nonce_label: &str,
) -> VerifiedCompactionPublicationV1 {
    let source_snapshot = snapshot_key(compact_generation, checkpoint_generation + 20);
    let mut inputs = Vec::with_capacity(record_ids.len());
    let mut heads = BTreeMap::<StableId, MemoryRecord>::new();
    for (index, record_id) in record_ids.iter().enumerate() {
        let record = record(record_id, 1);
        heads.insert(record.record_id.clone(), record.clone());
        inputs.push(CompactionInputRecordV2 {
            tokenization_receipt: tokenization_receipt(
                fixture,
                record.record_digest(),
                64,
                8,
            ),
            retention_reason_digest: digest(&format!("reason:{record_id}")),
            record,
            retention_priority: u32::try_from(record_ids.len() - index)
                .expect("priority"),
            encoded_bytes: 64,
            token_count: 8,
        });
    }
    let source_memory_snapshot: CognitiveSnapshot = build_snapshot(
        generation(checkpoint_generation + 20),
        heads.into_values().collect(),
    )
    .expect("source memory snapshot");
    let policy = CompactionPolicyV2 {
        policy_id: id("policy:e2e"),
        algorithm_digest: digest("algorithm:e2e"),
        compatibility_digest: digest("compatibility:e2e"),
        tokenizer_digest: fixture.tokenizer.tokenizer_digest,
        tokenizer_implementation_digest: fixture
            .tokenizer
            .enrollment
            .implementation_digest,
        maximum_retained_records: u32::try_from(record_ids.len())
            .expect("record limit"),
        maximum_retained_bytes: u64::try_from(record_ids.len()).expect("records") * 64,
        maximum_retained_tokens: u64::try_from(record_ids.len()).expect("records") * 8,
        maximum_payload_bytes: 4_096,
        maximum_payload_tokens: 512,
        protected_record_ids: vec![id(record_ids[0])],
    };
    let mut selection_receipt = SignedRetentionSelectionReceiptV1 {
        schema_version: COMPACTION_TRUST_SCHEMA_VERSION,
        key_id: fixture.selector.enrollment.key_id.clone(),
        trust_epoch: 1,
        issued_at_unix_seconds: NOW - 10,
        expires_at_unix_seconds: NOW + 1_000,
        nonce: digest(&format!("{nonce_label}:selection")),
        source_snapshot_digest: source_snapshot.vector_digest,
        source_memory_snapshot_digest: source_memory_snapshot.snapshot_digest,
        policy_digest: policy.digest(),
        input_manifest_digest: compaction_input_manifest_digest(&inputs),
        tokenizer_key_id: fixture.tokenizer.enrollment.key_id.clone(),
        tokenizer_trust_epoch: 1,
        tokenizer_key_digest: fixture.tokenizer.enrollment.key_digest(),
        signature: [0_u8; 64],
    };
    selection_receipt.signature = fixture
        .selector_key
        .sign(&selection_receipt.signing_bytes())
        .to_bytes();

    let payload = format!("checkpoint:{nonce_label}:{}", record_ids.join(","))
        .into_bytes();
    let payload_digest = Digest32::of_bytes(&payload);
    let payload_tokenization_receipt = tokenization_receipt(
        fixture,
        payload_digest,
        u64::try_from(payload.len()).expect("payload bytes"),
        u64::try_from(payload.len()).expect("payload tokens"),
    );
    let mut semantic_payload = CompactionSemanticPayloadV2 {
        source_snapshot_digest: source_snapshot.vector_digest,
        source_memory_snapshot_digest: source_memory_snapshot.snapshot_digest,
        payload_digest,
        payload,
        generator_implementation_digest: fixture
            .generator
            .enrollment
            .implementation_digest,
        generator_receipt_digest: digest("placeholder"),
        tokenizer_digest: fixture.tokenizer.tokenizer_digest,
        encoded_bytes: payload_tokenization_receipt.encoded_bytes,
        token_count: payload_tokenization_receipt.token_count,
        tokenization_receipt: payload_tokenization_receipt,
    };
    let mut generation_receipt = SignedSemanticGenerationReceiptV1 {
        schema_version: COMPACTION_TRUST_SCHEMA_VERSION,
        key_id: fixture.generator.enrollment.key_id.clone(),
        trust_epoch: 1,
        issued_at_unix_seconds: NOW - 9,
        expires_at_unix_seconds: NOW + 1_000,
        nonce: digest(&format!("{nonce_label}:generation")),
        source_snapshot_digest: source_snapshot.vector_digest,
        source_memory_snapshot_digest: source_memory_snapshot.snapshot_digest,
        policy_digest: policy.digest(),
        selection_receipt_digest: selection_receipt.receipt_digest(),
        payload_digest,
        tokenizer_key_id: fixture.tokenizer.enrollment.key_id.clone(),
        tokenizer_trust_epoch: 1,
        tokenizer_key_digest: fixture.tokenizer.enrollment.key_digest(),
        tokenization_receipt_digest: semantic_payload
            .tokenization_receipt
            .receipt_digest(),
        signature: [0_u8; 64],
    };
    generation_receipt.signature = fixture
        .generator_key
        .sign(&generation_receipt.signing_bytes())
        .to_bytes();
    semantic_payload.generator_receipt_digest = generation_receipt.receipt_digest();

    let candidate = build_qualified_candidate(QualifiedCandidateBuildRequestV1 {
        source_snapshot: source_snapshot.clone(),
        source_memory_snapshot: &source_memory_snapshot,
        generation: generation(checkpoint_generation),
        predecessor_checkpoint_digest: predecessor,
        policy: &policy,
        semantic_payload: &semantic_payload,
        selector: &fixture.selector,
        selection_receipt: &selection_receipt,
        generator: &fixture.generator,
        generation_receipt: &generation_receipt,
        tokenizer: &fixture.tokenizer,
        inputs: inputs.clone(),
        verification_time_unix_seconds: NOW,
    })
    .expect("qualified candidate");
    let mut qualification = CompactionQualificationV2 {
        tokenizer_implementation_digest: fixture
            .tokenizer
            .enrollment
            .implementation_digest,
        tokenizer_attestation_digest: fixture
            .tokenizer
            .enrollment
            .attestation_digest,
        tokenizer_key_digest: fixture.tokenizer.enrollment.key_digest(),
        evaluator_id: fixture.evaluator.evaluator_id.clone(),
        evaluator_implementation_digest: fixture
            .evaluator
            .enrollment
            .implementation_digest,
        evaluation_artifact_digest: digest(&format!("{nonce_label}:evaluation")),
        attestation_digest: fixture.evaluator.enrollment.attestation_digest,
        retained_query_suite_digest: digest(&format!("{nonce_label}:queries")),
        reconstruction_obligation_digest: digest(&format!("{nonce_label}:reconstruction")),
        contradiction_holdout_digest: digest(&format!("{nonce_label}:contradiction")),
        retained_queries_passed: true,
        reconstruction_passed: true,
        contradictions_preserved: true,
        deletion_non_resurrection_passed: true,
        signature: [0_u8; 64],
    };
    qualification.signature = fixture
        .evaluator_key
        .sign(&qualification.signing_bytes(candidate.candidate_digest()))
        .to_bytes();
    let mut evaluation_receipt = SignedCompactionEvaluationReceiptV1 {
        schema_version: COMPACTION_TRUST_SCHEMA_VERSION,
        key_id: fixture.evaluator.enrollment.key_id.clone(),
        trust_epoch: 1,
        issued_at_unix_seconds: NOW - 5,
        expires_at_unix_seconds: NOW + 1_000,
        nonce: digest(&format!("{nonce_label}:evaluation-receipt")),
        candidate_digest: candidate.candidate_digest(),
        qualification_digest: compaction_qualification_digest(
            candidate.candidate_digest(),
            &qualification,
        ),
        signature: [0_u8; 64],
    };
    evaluation_receipt.signature = fixture
        .evaluator_key
        .sign(&evaluation_receipt.signing_bytes())
        .to_bytes();
    let proof = prove_compaction(TrustedCompactionProofRequestV1 {
        candidate: &candidate,
        evaluator: &fixture.evaluator,
        qualification: qualification.clone(),
        evaluation_receipt: &evaluation_receipt,
        verification_time_unix_seconds: NOW,
    })
    .expect("qualified proof");
    proof
        .witness
        .verify_proof(&proof.proof)
        .expect("proof reconstruction");

    let mut token_accounting_receipt = SignedCompactionTokenAccountingV1 {
        schema_version: 1,
        key_id: fixture.tokenizer.enrollment.key_id.clone(),
        trust_epoch: 1,
        issued_at_unix_seconds: NOW - 4,
        expires_at_unix_seconds: NOW + 1_000,
        nonce: digest(&format!("{nonce_label}:token-batch")),
        source_snapshot_digest: source_snapshot.vector_digest,
        source_memory_snapshot_digest: source_memory_snapshot.snapshot_digest,
        policy_digest: policy.digest(),
        input_manifest_digest: compaction_input_manifest_digest(&inputs),
        payload_digest,
        payload_tokenization_receipt_digest: semantic_payload
            .tokenization_receipt
            .receipt_digest(),
        signature: [0_u8; 64],
    };
    token_accounting_receipt.signature = fixture
        .tokenizer_key
        .sign(
            &token_accounting_receipt
                .signing_bytes()
                .expect("token batch signing bytes"),
        )
        .to_bytes();

    VerifiedCompactionPublicationV1::verify(
        CompactionPublicationRequestV1 {
            source_snapshot,
            source_memory_snapshot,
            generation: generation(checkpoint_generation),
            predecessor_checkpoint_digest: predecessor,
            evidence: CompactionPublicationEvidenceV1 {
                policy,
                semantic_payload,
                inputs,
                selection_receipt,
                generation_receipt,
                token_accounting_receipt,
                qualification,
                evaluation_receipt,
            },
        },
        &fixture.registry,
        NOW,
    )
    .expect("sealed publication")
}

fn database_url(temp: &TempDir) -> String {
    format!("sqlite://{}", temp.path().join("product-e2e.db").display())
}

#[tokio::test]
async fn public_v2_path_publishes_restarts_reconstructs_and_advances() {
    let owner = id("agent:e2e:owner");
    let fixture = ProductTrustFixture::new(&owner);
    let temp = TempDir::new().expect("temp dir");
    let url = database_url(&temp);

    let first = sealed_publication(&fixture, &["memory:e2e:a"], 1, 1, None, "first");
    let first_checkpoint = first.candidate().checkpoint().checkpoint_digest;
    let coordinator = MemoryCheckpointCoordinatorV2::open(
        &url,
        owner.as_str(),
        fixture.root.verifying_key().to_bytes(),
        &fixture.manifest_bytes,
        "lease:e2e:one",
        1,
        NOW + 600,
        NOW,
    )
    .await
    .expect("open product owner");
    let first_receipt = coordinator
        .publish_verified_checkpoint("operation:e2e:first", &first, NOW + 500, NOW)
        .await
        .expect("publish first checkpoint");
    assert_eq!(first_receipt.disposition, DurableCompactionDisposition::Inserted);
    drop(coordinator);

    let reopened = MemoryCheckpointCoordinatorV2::open(
        &url,
        owner.as_str(),
        fixture.root.verifying_key().to_bytes(),
        &fixture.manifest_bytes,
        "lease:e2e:one",
        1,
        NOW + 700,
        NOW + 1,
    )
    .await
    .expect("reopen product owner");
    let recovered = reopened
        .recover_current_checkpoint("scope:e2e", "purpose:e2e", NOW + 1)
        .await
        .expect("recover first checkpoint")
        .expect("first checkpoint exists");
    assert_eq!(recovered.generation(), 1);
    assert_eq!(recovered.checkpoint_digest(), first_checkpoint);
    recovered
        .publication()
        .proof()
        .witness
        .verify_proof(&recovered.publication().proof().proof)
        .expect("reconstructed first proof");

    let second = sealed_publication(
        &fixture,
        &["memory:e2e:a", "memory:e2e:b"],
        2,
        2,
        Some(first_checkpoint),
        "second",
    );
    let second_checkpoint = second.candidate().checkpoint().checkpoint_digest;
    reopened
        .publish_verified_checkpoint("operation:e2e:second", &second, NOW + 600, NOW + 2)
        .await
        .expect("publish incremental checkpoint");
    let latest = reopened
        .recover_current_checkpoint("scope:e2e", "purpose:e2e", NOW + 2)
        .await
        .expect("recover latest checkpoint")
        .expect("latest checkpoint exists");
    assert_eq!(latest.generation(), 2);
    assert_eq!(latest.checkpoint_digest(), second_checkpoint);
    assert_eq!(
        latest
            .publication()
            .candidate()
            .checkpoint()
            .predecessor_digest,
        Some(first_checkpoint)
    );
    assert!(
        latest
            .publication()
            .candidate()
            .semantic_payload()
            .payload
            .windows(b"memory:e2e:b".len())
            .any(|window| window == b"memory:e2e:b")
    );
}
