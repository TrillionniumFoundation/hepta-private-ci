use super::*;

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
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

fn snapshot() -> CognitiveSnapshotKeyV1 {
    CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: id("scope:compact:e2e"),
        purpose_id: id("purpose:consolidation:e2e"),
        memory_ledger_frontier: 20,
        knowledge_fact_frontier: 14,
        tombstone_frontier: 6,
        source_ledger_frontier: 21,
        knowledge_graph_generation: generation(3),
        compact_checkpoint_generation: generation(1),
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

fn request() -> AgentdCompactionCheckpointRequest {
    let source_snapshot = snapshot();
    let record = MemoryRecord {
        record_id: id("memory:e2e"),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest("content:e2e"),
        predecessor_digest: None,
        citations: Vec::new(),
        state: RecordState::Live,
    };
    AgentdCompactionCheckpointRequest {
        source_snapshot: source_snapshot.clone(),
        generation: generation(2),
        predecessor_checkpoint_digest: Some(digest("checkpoint:bootstrap:e2e")),
        policy: CompactionPolicyV2 {
            policy_id: id("policy:compact:e2e"),
            algorithm_digest: digest("algorithm:e2e"),
            compatibility_digest: digest("compatibility:e2e"),
            maximum_retained_records: 8,
            maximum_retained_bytes: 4_096,
            maximum_retained_tokens: 512,
            maximum_payload_bytes: 2_048,
            maximum_payload_tokens: 256,
            protected_record_ids: vec![id("memory:e2e")],
        },
        semantic_payload: CompactionSemanticPayloadV2 {
            source_snapshot_digest: source_snapshot.vector_digest,
            payload_digest: digest("semantic-payload:e2e"),
            generator_implementation_digest: digest("semantic-generator:e2e"),
            generator_receipt_digest: digest("semantic-generator-receipt:e2e"),
            tokenizer_digest: source_snapshot.vector.tokenizer_digest,
            encoded_bytes: 256,
            token_count: 32,
        },
        inputs: vec![CompactionInputRecordV2 {
            retention_reason_digest: digest("retention-reason:e2e"),
            record,
            retention_priority: 100,
            encoded_bytes: 64,
            token_count: 8,
        }],
        qualification: CompactionQualificationV2 {
            evaluator_id: id("evaluator:independent:e2e"),
            evaluator_implementation_digest: digest("evaluator-implementation:e2e"),
            evaluation_artifact_digest: digest("evaluation-artifact:e2e"),
            attestation_digest: digest("attestation:e2e"),
            attestation_signature_digest: digest("attestation-signature:e2e"),
            signature_verification_receipt_digest: digest("signature-verification:e2e"),
            retained_query_suite_digest: digest("retained-queries:e2e"),
            reconstruction_obligation_digest: digest("reconstruction:e2e"),
            contradiction_holdout_digest: digest("contradictions:e2e"),
            retained_queries_passed: true,
            reconstruction_passed: true,
            contradictions_preserved: true,
            deletion_non_resurrection_passed: true,
        },
    }
}

fn now_unix_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock")
        .as_secs()
}

#[tokio::test]
async fn agentd_compaction_checkpoint_round_trips_through_authorized_writer() {
    let temp = TempDir::new().expect("temporary directory");
    let fleet_root = temp.path().join("fleet");
    std::fs::create_dir_all(&fleet_root).expect("fleet root");
    let fleet = HeptaFleetRoot::parse(fleet_root.canonicalize().expect("canonical fleet root"))
        .expect("valid fleet root");
    let owner =
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c44").expect("valid owner agent");
    let layout = fleet.layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await.expect("open cognitive store");

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
    let host = AgentdProductionWriterHost::open_with_store(
        store.clone(),
        authority,
        &verifier,
        "production:compact:e2e",
        1,
    )
    .await
    .expect("open authorized product writer");

    let publication = host
        .publish_compaction_checkpoint(request())
        .await
        .expect("publish canonical compact checkpoint");
    assert_eq!(publication.checkpoint.generation, generation(2));
    assert_eq!(
        publication.proof.checkpoint_digest,
        publication.checkpoint.checkpoint_digest
    );
    assert_eq!(publication.proof.evaluator_id, id("evaluator:independent:e2e"));

    let latest = store
        .latest_qualified_compact_checkpoint(
            &id("scope:compact:e2e"),
            &id("purpose:consolidation:e2e"),
        )
        .await
        .expect("read latest checkpoint")
        .expect("checkpoint exists");
    assert_eq!(
        latest.checkpoint.checkpoint_digest,
        publication.checkpoint.checkpoint_digest
    );
    assert_eq!(latest.proof.proof_digest, publication.proof.proof_digest);

    drop(host);
    drop(store);
    let reopened = CognitiveStore::open(&layout)
        .await
        .expect("restart must reopen the qualified checkpoint store");
    let restored = reopened
        .latest_qualified_compact_checkpoint(
            &id("scope:compact:e2e"),
            &id("purpose:consolidation:e2e"),
        )
        .await
        .expect("reload latest checkpoint")
        .expect("reloaded checkpoint exists");
    assert_eq!(restored.checkpoint, publication.checkpoint);
    assert_eq!(restored.proof, publication.proof);
}
