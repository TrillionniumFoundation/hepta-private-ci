use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_cognitive_types::hnmf::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tempfile::TempDir;

use super::*;
use crate::CognitiveScope;
use crate::LedgerSourceKind;
use crate::MemoryLifecycleState;
use crate::MemoryVerification;

pub(super) struct Verifier(pub AtomicBool);
impl ProductionAuthorityVerifier for Verifier {
    fn verify(&self, authority: &ProductionAuthorityLease, owner: &AgentId) -> Result<(), String> {
        if self.0.load(Ordering::SeqCst) || authority.agent_id != *owner {
            Err("withdrawn".to_string())
        } else {
            Ok(())
        }
    }
}

pub(super) struct Fixture {
    pub temp: TempDir,
    pub writer: Arc<ProductionDurableWriter>,
    pub verifier: Arc<Verifier>,
    pub access: CognitiveAccess,
    pub query: MemoryCellQueryV1,
    pub claim: MemoryCellSourceClaimV1,
}

pub(super) async fn fixture() -> Fixture {
    let temp = TempDir::new().unwrap();
    let fleet = HeptaFleetRoot::parse(temp.path().to_path_buf()).unwrap();
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2cde").unwrap();
    let store = CognitiveStore::open(&fleet.layout().agent(&owner))
        .await
        .unwrap();
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"test-issued-grant"),
        1,
        1,
        now_unix_seconds().unwrap() + 3600,
        ProductionAuthorityToken::from_verified_bytes(b"test-issued-token".to_vec()).unwrap(),
    )
    .unwrap();
    let verifier = Arc::new(Verifier(AtomicBool::new(false)));
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            store,
            authority,
            verifier.clone(),
            "memory-cell-test",
            1,
        )
        .await
        .unwrap(),
    );
    let access = CognitiveAccess::agent_private(owner);
    let query = MemoryCellQueryV1 {
        request_id: StableId::new("read:1").unwrap(),
        key: MemoryCellKeyV1 {
            role: MemoryCellRoleV1::Semantic,
            entity: "pipeline-42".to_string(),
            relation: "recovery".to_string(),
        },
        deadline_unix_ms: now_unix_ms().unwrap() + 300_000,
    };
    let source = source(&query, "build-42", "retry-cache");
    let draft = MemoryDraft {
        stable_key: query.key.stable_key().unwrap(),
        revision: revision(&source),
    };
    let production = writer
        .cognitive_mutation_capability()
        .unwrap()
        .remember_with_kg(&access, &source, &draft, &KgFactSetDraft::default())
        .await
        .unwrap();
    let claim = claim(&query, production);
    Fixture {
        temp,
        writer,
        verifier,
        access,
        query,
        claim,
    }
}

pub(super) fn source(query: &MemoryCellQueryV1, event: &str, value: &str) -> SourceDraft {
    let content = serde_json::to_vec(&MemoryCellDocumentV1 {
        schema_version: 1,
        key: query.key.clone(),
        value: value.to_string(),
    })
    .unwrap();
    SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: event.to_string(),
        content,
        observed_at_unix_seconds: now_unix_seconds().unwrap() as i64,
    }
}

pub(super) fn revision(source: &SourceDraft) -> MemoryRevisionDraft {
    MemoryRevisionDraft {
        scope: source.scope.clone(),
        content: String::from_utf8(source.content.clone()).unwrap(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: source.observed_at_unix_seconds,
        valid_to_unix_seconds: None,
        citations: vec![],
    }
}

pub(super) fn claim(
    query: &MemoryCellQueryV1,
    production: ProductionCognitiveMutationReceiptV1,
) -> MemoryCellSourceClaimV1 {
    let id = |value: &str| ContractIdV1::new(value).unwrap();
    let digest =
        |value: &str| ContractDigestV1::from_digest(Digest32::of_bytes(value.as_bytes())).unwrap();
    let source_digest = ContractDigestV1::parse(production.source_content_sha256.as_str()).unwrap();
    let observed = production.source_observed_at_unix_seconds as u64 * 1000;
    let event = MemoryEventV1 {
        event_id: id("hnmf:memory-42"),
        episode_id: id("episode:42"),
        scope: MemoryScopeV1::AgentPrivate {
            agent_id: id(production.owner_agent_id.as_str()),
        },
        observed_interval: ObservedIntervalV1 {
            start_unix_ms: observed,
            end_unix_ms: None,
        },
        modality_spans: vec![ModalitySpanRefV1 {
            span_id: id("span:source"),
            modality: ModalityKindV1::Text,
            asset_sha256: source_digest,
            range: SpanRangeV1::ByteRange {
                start: 0,
                end: production.write.memory.content.len() as u64,
            },
            preprocessor_manifest_sha256: digest("typed-source-v1"),
            feature_blob_sha256: None,
            symbolic_projection_sha256: None,
            uncertainty_ppm: 0,
            privacy_class: PrivacyClassV1::AgentPrivate,
            redaction_mask_sha256: None,
        }],
        cross_modal_bindings: vec![],
        semantic_keys: BTreeSet::from([query.key.stable_key().unwrap()]),
        provenance: vec![ProvenanceRefV1 {
            source_id: id(production.write.source.source_id.as_str()),
            source_revision: production.write.source.revision,
            source_sha256: source_digest,
            observed_at_unix_ms: observed,
        }],
        verification: MemoryVerificationStateV1::Verified,
        retention_policy: RetentionPolicyV1::Persistent {
            retain_until_unix_ms: None,
        },
        objective_digest: digest("objective"),
        ndu_state_digest: digest("ndu"),
        causal_parents: BTreeSet::new(),
        temporal_neighbors: BTreeSet::new(),
        behavior_propensity_ppm: None,
        lifecycle: MemoryLifecycleV1::Active,
    };
    MemoryCellSourceClaimV1 { event, production }
}
