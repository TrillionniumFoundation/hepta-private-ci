use super::*;

use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_read::AuthoritativeCognitiveSnapshotProvider;
use codex_hepta_cognitive_read::AuthoritativeSnapshotV1;
use codex_hepta_cognitive_read::SnapshotAcquisitionRequestV1;
use codex_hepta_cognitive_read::SnapshotProviderError;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_compact_engine::TokenizationReceiptV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

fn revision(value: u64) -> Revision {
    Revision::new(value).expect("valid revision")
}

fn snapshot(compact_generation: u64) -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:compact:e2e"),
        purpose_id: id("purpose:consolidation:e2e"),
        memory_ledger_frontier: 20,
        knowledge_fact_frontier: 14,
        tombstone_frontier: 6,
        source_ledger_frontier: 21,
        knowledge_graph_generation: generation(3),
        compact_checkpoint_generation: generation(compact_generation),
        prompt_registry_revision: revision(4),
        retrieval_profile_digest: digest("retrieval:e2e"),
        encoder_preprocessor_digest: digest("encoder:e2e"),
        authority_epoch: 9,
        model_digest: digest("model:e2e"),
        tokenizer_digest: digest("tokenizer:e2e"),
        template_digest: digest("template:e2e"),
        tool_schema_digest: digest("tool-schema:e2e"),
    })
    .expect("valid snapshot")
}

fn tokenizer() -> (TrustedTokenizerV1, SigningKey) {
    let signing_key = SigningKey::from_bytes(&[5_u8; 32]);
    (
        TrustedTokenizerV1 {
            tokenizer_digest: digest("tokenizer:e2e"),
            implementation_digest: digest("tokenizer-implementation:e2e"),
            attestation_digest: digest("tokenizer-attestation:e2e"),
            verifying_key: signing_key.verifying_key().to_bytes(),
        },
        signing_key,
    )
}

fn tokenization_receipt(
    signing_key: &SigningKey,
    subject_digest: Digest32,
    encoded_bytes: u64,
    token_count: u64,
) -> TokenizationReceiptV1 {
    let mut receipt = TokenizationReceiptV1 {
        subject_digest,
        tokenizer_digest: digest("tokenizer:e2e"),
        tokenizer_implementation_digest: digest("tokenizer-implementation:e2e"),
        encoded_bytes,
        token_count,
        signature: [0_u8; 64],
    };
    receipt.signature = signing_key.sign(&receipt.signing_bytes()).to_bytes();
    receipt
}

fn evaluator() -> (TrustedCompactionEvaluatorV1, SigningKey) {
    let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
    (
        TrustedCompactionEvaluatorV1 {
            evaluator_id: id("evaluator:independent:e2e"),
            implementation_digest: digest("evaluator-implementation:e2e"),
            attestation_digest: digest("attestation:e2e"),
            verifying_key: signing_key.verifying_key().to_bytes(),
        },
        signing_key,
    )
}

fn source_memory() -> (MemoryRecord, codex_hepta_cognitive_types::CognitiveSnapshot) {
    let record = MemoryRecord {
        record_id: id("memory:e2e"),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest("content:e2e"),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    };
    let snapshot =
        build_snapshot(generation(21), vec![record.clone()]).expect("source memory snapshot");
    (record, snapshot)
}

fn authoritative(
    compact_generation: u64,
    memory: codex_hepta_cognitive_types::CognitiveSnapshot,
) -> (AuthoritativeSnapshotV1, SnapshotAcquisitionRequestV1) {
    let source_snapshot_key = snapshot(compact_generation);
    let now = now_unix_millis();
    let source_snapshot = AuthoritativeSnapshotV1::new(
        id("provider:cognitive:e2e"),
        source_snapshot_key.clone(),
        memory,
        now.saturating_sub(1_000).max(1),
        now.saturating_add(3_600_000),
    )
    .expect("authoritative source snapshot");
    let request = SnapshotAcquisitionRequestV1 {
        request_id: id(&format!("request:compact:e2e:{compact_generation}")),
        scope_id: source_snapshot_key.vector.scope_id.clone(),
        purpose_id: source_snapshot_key.vector.purpose_id.clone(),
        minimum_memory_frontier: source_snapshot_key.vector.memory_ledger_frontier,
        minimum_tombstone_frontier: source_snapshot_key.vector.tombstone_frontier,
        authority_epoch: source_snapshot_key.vector.authority_epoch,
        deadline_unix_ms: now.saturating_add(3_600_000),
    };
    (source_snapshot, request)
}

#[derive(Clone)]
struct FixtureSnapshotProvider {
    snapshots: Vec<(StableId, AuthoritativeSnapshotV1)>,
}

impl FixtureSnapshotProvider {
    fn new(snapshots: Vec<(StableId, AuthoritativeSnapshotV1)>) -> Self {
        Self { snapshots }
    }
}

impl AuthoritativeCognitiveSnapshotProvider for FixtureSnapshotProvider {
    fn acquire(
        &self,
        request: &SnapshotAcquisitionRequestV1,
    ) -> Result<AuthoritativeSnapshotV1, SnapshotProviderError> {
        self.snapshots
            .iter()
            .find(|(request_id, _)| request_id == &request.request_id)
            .map(|(_, snapshot)| snapshot.clone())
            .ok_or(SnapshotProviderError::Unavailable)
    }
}

fn request_and_trust() -> (
    AgentdCompactionCheckpointRequest,
    AgentdCompactionTrustV1,
    Vec<u8>,
    AuthoritativeSnapshotV1,
) {
    let (record, source_memory_snapshot) = source_memory();
    let (source_snapshot, snapshot_acquisition_request) =
        authoritative(1, source_memory_snapshot.clone());
    let (trusted_tokenizer, tokenizer_signing_key) = tokenizer();
    let (trusted_evaluator, evaluator_signing_key) = evaluator();

    let policy = CompactionPolicyV2 {
        policy_id: id("policy:compact:e2e"),
        algorithm_digest: digest("algorithm:e2e"),
        compatibility_digest: digest("compatibility:e2e"),
        tokenizer_digest: source_snapshot.snapshot_key().vector.tokenizer_digest,
        tokenizer_implementation_digest: trusted_tokenizer.implementation_digest,
        maximum_retained_records: 8,
        maximum_retained_bytes: 4_096,
        maximum_retained_tokens: 512,
        maximum_payload_bytes: 2_048,
        maximum_payload_tokens: 256,
        protected_record_ids: vec![id("memory:e2e")],
    };
    let input = CompactionInputRecordV2 {
        retention_reason_digest: digest("retention-reason:e2e"),
        tokenization_receipt: tokenization_receipt(
            &tokenizer_signing_key,
            record.record_digest(),
            64,
            8,
        ),
        record,
        retention_priority: 100,
        encoded_bytes: 64,
        token_count: 8,
    };
    let payload = b"semantic compact payload bytes for e2e".to_vec();
    let payload_digest = Digest32::of_bytes(&payload);
    let semantic_payload = CompactionSemanticPayloadV2 {
        source_snapshot_digest: source_snapshot.snapshot_key().vector_digest,
        source_memory_snapshot_digest: source_memory_snapshot.snapshot_digest,
        payload_digest,
        payload: payload.clone(),
        generator_implementation_digest: digest("semantic-generator:e2e"),
        generator_receipt_digest: digest("semantic-generator-receipt:e2e"),
        tokenizer_digest: source_snapshot.snapshot_key().vector.tokenizer_digest,
        encoded_bytes: u64::try_from(payload.len()).expect("bounded payload"),
        token_count: 7,
        tokenization_receipt: tokenization_receipt(
            &tokenizer_signing_key,
            payload_digest,
            u64::try_from(payload.len()).expect("bounded payload"),
            7,
        ),
    };
    let candidate = build_qualified_candidate(
        source_snapshot.snapshot_key().clone(),
        &source_memory_snapshot,
        generation(2),
        Some(digest("checkpoint:bootstrap:e2e")),
        &policy,
        &semantic_payload,
        &trusted_tokenizer,
        vec![input.clone()],
    )
    .expect("candidate used to sign evaluator evidence");
    let mut qualification = CompactionQualificationV2 {
        tokenizer_implementation_digest: trusted_tokenizer.implementation_digest,
        tokenizer_attestation_digest: trusted_tokenizer.attestation_digest,
        tokenizer_key_digest: trusted_tokenizer.key_digest(),
        evaluator_id: trusted_evaluator.evaluator_id.clone(),
        evaluator_implementation_digest: trusted_evaluator.implementation_digest,
        evaluation_artifact_digest: digest("evaluation-artifact:e2e"),
        attestation_digest: trusted_evaluator.attestation_digest,
        retained_query_suite_digest: digest("retained-queries:e2e"),
        reconstruction_obligation_digest: digest("reconstruction:e2e"),
        contradiction_holdout_digest: digest("contradictions:e2e"),
        retained_queries_passed: true,
        reconstruction_passed: true,
        contradictions_preserved: true,
        deletion_non_resurrection_passed: true,
        signature: [0_u8; 64],
    };
    qualification.signature = evaluator_signing_key
        .sign(&qualification.signing_bytes(candidate.candidate_digest()))
        .to_bytes();

    (
        AgentdCompactionCheckpointRequest {
            snapshot_acquisition_request,
            generation: generation(2),
            predecessor_checkpoint_digest: Some(digest("checkpoint:bootstrap:e2e")),
            policy,
            semantic_payload,
            inputs: vec![input],
            qualification,
        },
        AgentdCompactionTrustV1::new(trusted_tokenizer, trusted_evaluator),
        payload,
        source_snapshot,
    )
}

fn now_unix_millis() -> u64 {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock")
        .as_millis();
    u64::try_from(millis).expect("timestamp fits u64")
}

fn now_unix_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock")
        .as_secs()
}

#[tokio::test]
async fn agentd_compaction_full_path_publishes_resolves_and_re_admits() {
    let temp = TempDir::new().expect("temporary directory");
    let fleet_root = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet_root).expect("fleet root");
    let fleet = HeptaFleetRoot::parse(fleet_root.canonicalize().expect("canonical fleet root"))
        .expect("valid fleet root");
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c44").expect("valid owner agent");
    let layout = fleet.layout().agent(&owner);
    let store = CognitiveStore::open(&layout)
        .await
        .expect("open cognitive store");

    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"compact-e2e-signed-grant"),
        9,
        4,
        now_unix_seconds().saturating_add(3_600),
        ProductionAuthorityToken::from_verified_bytes(b"compact-e2e-opaque-token".to_vec())
            .expect("verified authority token"),
    )
    .expect("verified authority lease");
    let verifier = |authority: &ProductionAuthorityLease, expected_agent: &AgentId| {
        if &authority.agent_id == expected_agent && authority.authority_epoch == 9 {
            Ok(())
        } else {
            Err("unexpected compact test authority".to_string())
        }
    };
    let (request, trust, expected_payload, source_snapshot) = request_and_trust();
    let original_trust = trust.clone();
    let (_, current_memory) = source_memory();
    let (current_snapshot, current_request) = authoritative(2, current_memory);
    let provider = Arc::new(FixtureSnapshotProvider::new(vec![
        (
            request.snapshot_acquisition_request.request_id.clone(),
            source_snapshot,
        ),
        (current_request.request_id.clone(), current_snapshot),
    ]));
    let host = AgentdProductionWriterHost::open_with_store(
        store.clone(),
        authority,
        &verifier,
        "production:compact:e2e",
        1,
    )
    .await
    .expect("open authorized product writer")
    .attach_compaction_trust(trust)
    .attach_snapshot_provider(provider);
    assert!(host.has_compaction_trust());
    assert!(host.has_snapshot_provider());

    let publication = host
        .publish_compaction_checkpoint(request)
        .await
        .expect("publish canonical compact checkpoint");
    assert_eq!(publication.checkpoint.generation, generation(2));

    let selected = host
        .select_current_compaction_checkpoint(&current_request, digest("compatibility:e2e"))
        .await
        .expect("re-admit current")
        .expect("selected");
    assert_eq!(selected.payload, expected_payload);

    let mut evaluator_rotated = original_trust.clone();
    evaluator_rotated.evaluator.verifying_key = SigningKey::from_bytes(&[8_u8; 32])
        .verifying_key()
        .to_bytes();
    let evaluator_rotated_host = host.clone().attach_compaction_trust(evaluator_rotated);
    assert!(matches!(
        evaluator_rotated_host
            .select_current_compaction_checkpoint(
                &current_request,
                digest("compatibility:e2e"),
            )
            .await,
        Err(AgentdCompactionCheckpointError::CompactionTrustDrift)
    ));

    let mut tokenizer_rotated = original_trust;
    tokenizer_rotated.tokenizer.verifying_key = SigningKey::from_bytes(&[6_u8; 32])
        .verifying_key()
        .to_bytes();
    let tokenizer_rotated_host = host.clone().attach_compaction_trust(tokenizer_rotated);
    assert!(matches!(
        tokenizer_rotated_host
            .select_current_compaction_checkpoint(
                &current_request,
                digest("compatibility:e2e"),
            )
            .await,
        Err(AgentdCompactionCheckpointError::CompactionTrustDrift)
    ));

    drop(host);
    drop(store);
    let reopened = CognitiveStore::open(&layout)
        .await
        .expect("restart must reopen the qualified checkpoint store");
    let restored = reopened
        .resolve_qualified_compact_payload(
            &id("scope:compact:e2e"),
            &id("purpose:consolidation:e2e"),
            publication.checkpoint.payload_digest,
        )
        .await
        .expect("resolve after restart")
        .expect("payload after restart");
    assert_eq!(restored, expected_payload);
}

#[tokio::test]
async fn product_path_fails_closed_without_host_trust_roots() {
    let temp = TempDir::new().expect("temporary directory");
    let fleet_root = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet_root).expect("fleet root");
    let fleet = HeptaFleetRoot::parse(fleet_root.canonicalize().expect("canonical fleet root"))
        .expect("valid fleet root");
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c45").expect("valid owner agent");
    let store = CognitiveStore::open(&fleet.layout().agent(&owner))
        .await
        .expect("open cognitive store");
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"compact-e2e-signed-grant-no-trust"),
        9,
        4,
        now_unix_seconds().saturating_add(3_600),
        ProductionAuthorityToken::from_verified_bytes(b"compact-e2e-token-no-trust".to_vec())
            .expect("verified authority token"),
    )
    .expect("verified authority lease");
    let verifier = |_authority: &ProductionAuthorityLease, _agent: &AgentId| Ok(());
    let host = AgentdProductionWriterHost::open_with_store(
        store,
        authority,
        &verifier,
        "production:compact:e2e:no-trust",
        1,
    )
    .await
    .expect("host");
    let (request, _trust, _, _) = request_and_trust();
    assert!(matches!(
        host.publish_compaction_checkpoint(request).await,
        Err(AgentdCompactionCheckpointError::CompactionTrustUnavailable)
    ));
}

#[tokio::test]
async fn product_path_fails_closed_without_authoritative_snapshot_provider() {
    let temp = TempDir::new().expect("temporary directory");
    let fleet_root = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet_root).expect("fleet root");
    let fleet = HeptaFleetRoot::parse(fleet_root.canonicalize().expect("canonical fleet root"))
        .expect("valid fleet root");
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c46").expect("valid owner agent");
    let store = CognitiveStore::open(&fleet.layout().agent(&owner))
        .await
        .expect("open cognitive store");
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"compact-e2e-signed-grant-no-provider"),
        9,
        4,
        now_unix_seconds().saturating_add(3_600),
        ProductionAuthorityToken::from_verified_bytes(b"compact-e2e-token-no-provider".to_vec())
            .expect("verified authority token"),
    )
    .expect("verified authority lease");
    let verifier = |_authority: &ProductionAuthorityLease, _agent: &AgentId| Ok(());
    let (request, trust, _, _) = request_and_trust();
    let host = AgentdProductionWriterHost::open_with_store(
        store,
        authority,
        &verifier,
        "production:compact:e2e:no-provider",
        1,
    )
    .await
    .expect("host")
    .attach_compaction_trust(trust);
    assert!(matches!(
        host.publish_compaction_checkpoint(request).await,
        Err(AgentdCompactionCheckpointError::SnapshotProviderUnavailable)
    ));
}
