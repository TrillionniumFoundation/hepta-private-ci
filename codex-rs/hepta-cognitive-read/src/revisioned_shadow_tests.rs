use super::*;

use std::collections::BTreeSet;

use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::build_snapshot;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf::MemoryEventV1;
use codex_hepta_cognitive_types::hnmf::MemoryLifecycleV1;
use codex_hepta_cognitive_types::hnmf::MemoryScopeV1;
use codex_hepta_cognitive_types::hnmf::MemoryVerificationStateV1;
use codex_hepta_cognitive_types::hnmf::ModalityKindV1;
use codex_hepta_cognitive_types::hnmf::ModalitySpanRefV1;
use codex_hepta_cognitive_types::hnmf::ObservedIntervalV1;
use codex_hepta_cognitive_types::hnmf::PrivacyClassV1;
use codex_hepta_cognitive_types::hnmf::ProvenanceRefV1;
use codex_hepta_cognitive_types::hnmf::RetentionPolicyV1;
use codex_hepta_cognitive_types::hnmf::SpanRangeV1;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
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

fn vector() -> LaneCGenerationVectorV1 {
    let static_digest = digest("static-profile");
    LaneCGenerationVectorV1 {
        scope_id: id("scope:one"),
        purpose_id: id("purpose:read"),
        memory_ledger_frontier: 10,
        source_ledger_frontier: 9,
        tombstone_frontier: 4,
        knowledge_fact_frontier: 8,
        knowledge_graph_generation: generation(2),
        compact_checkpoint_generation: generation(1),
        prompt_registry_revision: revision(3),
        retrieval_profile_digest: static_digest,
        encoder_preprocessor_digest: static_digest,
        authority_epoch: 7,
        model_digest: static_digest,
        tokenizer_digest: static_digest,
        template_digest: static_digest,
        tool_schema_digest: static_digest,
    }
}

fn authoritative_read() -> AuthoritativeReadResultV1 {
    let record = MemoryRecord {
        record_id: id("memory:one"),
        revision: revision(1),
        kind: MemoryKind::Fact,
        content_digest: digest("content"),
        predecessor_digest: None,
        citations: vec![Citation {
            source_id: id("source:one"),
            source_digest: digest("source-digest:one"),
        }],
        state: RecordState::Live,
    };
    let snapshot = build_snapshot(generation(1), vec![record]).expect("valid snapshot");
    let envelope = AuthoritativeSnapshotV1::new(
        id("provider:one"),
        CognitiveSnapshotKeyV1::new(vector()).expect("valid vector"),
        snapshot,
        5,
        50,
    )
    .expect("valid authoritative snapshot");
    let provider = FixtureProvider { envelope };
    let snapshot_digest = provider.envelope.snapshot().snapshot_digest;
    read_authoritative(
        &provider,
        10,
        SnapshotAcquisitionRequestV1 {
            request_id: id("request:one"),
            scope_id: id("scope:one"),
            purpose_id: id("purpose:read"),
            minimum_memory_frontier: 10,
            minimum_tombstone_frontier: 4,
            authority_epoch: 7,
            deadline_unix_ms: 40,
        },
        ReadRequestV2 {
            read_request: ReadRequest {
                snapshot_digest,
                allowed_kinds: Vec::new(),
                maximum_results: 8,
                include_tombstones: false,
            },
            maximum_encoded_bytes: MAX_ENCODED_READ_RESULT_BYTES_V2,
        },
    )
    .expect("authoritative read")
}

#[derive(Clone)]
struct FixtureProvider {
    envelope: AuthoritativeSnapshotV1,
}

impl AuthoritativeCognitiveSnapshotProvider for FixtureProvider {
    fn acquire(
        &self,
        _request: &SnapshotAcquisitionRequestV1,
    ) -> Result<AuthoritativeSnapshotV1, SnapshotProviderError> {
        Ok(self.envelope.clone())
    }
}

fn contract_id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).expect("valid contract id")
}

fn contract_digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(digest(value)).expect("valid contract digest")
}

fn canonical_event(source_revision: u64) -> MemoryEventV1 {
    MemoryEventV1 {
        event_id: contract_id("event:one"),
        episode_id: contract_id("episode:one"),
        scope: MemoryScopeV1::AgentPrivate {
            agent_id: contract_id("agent:one"),
        },
        observed_interval: ObservedIntervalV1 {
            start_unix_ms: 1,
            end_unix_ms: None,
        },
        modality_spans: vec![ModalitySpanRefV1 {
            span_id: contract_id("span:one"),
            modality: ModalityKindV1::Text,
            asset_sha256: contract_digest("asset"),
            range: SpanRangeV1::ByteRange { start: 0, end: 4 },
            preprocessor_manifest_sha256: contract_digest("preprocessor"),
            feature_blob_sha256: None,
            symbolic_projection_sha256: None,
            uncertainty_ppm: 0,
            privacy_class: PrivacyClassV1::AgentPrivate,
            redaction_mask_sha256: None,
        }],
        cross_modal_bindings: Vec::new(),
        semantic_keys: BTreeSet::from(["door".to_string()]),
        provenance: vec![ProvenanceRefV1 {
            source_id: contract_id("source:one"),
            source_revision,
            source_sha256: contract_digest("source-digest:one"),
            observed_at_unix_ms: 1,
        }],
        verification: MemoryVerificationStateV1::Verified,
        retention_policy: RetentionPolicyV1::Persistent {
            retain_until_unix_ms: None,
        },
        objective_digest: contract_digest("objective"),
        ndu_state_digest: contract_digest("ndu"),
        causal_parents: BTreeSet::new(),
        temporal_neighbors: BTreeSet::new(),
        behavior_propensity_ppm: None,
        lifecycle: MemoryLifecycleV1::Active,
    }
}

fn binding(
    read: &AuthoritativeReadResultV1,
    source_revision: u64,
) -> CanonicalReadRecordBindingV2 {
    let record = &read.read_result.records()[0];
    CanonicalReadRecordBindingV2 {
        legacy_record_id: record.record_id.clone(),
        legacy_record_revision: record.revision,
        legacy_record_digest: record.record_digest(),
        source_revisions: vec![CanonicalSourceRevisionBindingV2 {
            source_id: id("source:one"),
            source_revision,
            source_digest: digest("source-digest:one"),
        }],
        event: canonical_event(1),
    }
}

#[test]
fn revision_bound_shadow_accepts_exact_owner_revision_bridge() {
    let read = authoritative_read();
    let shadow = adapt_authoritative_read_to_revision_bound_canonical_shadow_v2(
        &read,
        vec![binding(&read, 1)],
    )
    .expect("revision-bound shadow");

    assert_eq!(shadow.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(shadow.rows.len(), 1);
    assert_eq!(shadow.rows[0].source_revisions[0].source_revision, 1);
    shadow.validate().expect("valid revision-bound shadow");
}

#[test]
fn revision_bound_shadow_rejects_missing_wrong_or_duplicate_source_revision() {
    let read = authoritative_read();

    let mut missing = binding(&read, 1);
    missing.source_revisions.clear();
    assert!(matches!(
        adapt_authoritative_read_to_revision_bound_canonical_shadow_v2(&read, vec![missing]),
        Err(CanonicalReadShadowV2Error::MissingSourceRevisionBinding(_))
    ));

    assert!(matches!(
        adapt_authoritative_read_to_revision_bound_canonical_shadow_v2(
            &read,
            vec![binding(&read, 2)],
        ),
        Err(CanonicalReadShadowV2Error::SourceRevisionMismatch(_))
    ));

    let mut wrong_digest = binding(&read, 1);
    wrong_digest.source_revisions[0].source_digest = digest("other-source-digest");
    assert!(matches!(
        adapt_authoritative_read_to_revision_bound_canonical_shadow_v2(
            &read,
            vec![wrong_digest],
        ),
        Err(CanonicalReadShadowV2Error::CitationProvenanceMismatch(_))
    ));

    let mut duplicate = binding(&read, 1);
    duplicate
        .source_revisions
        .push(duplicate.source_revisions[0].clone());
    assert!(matches!(
        adapt_authoritative_read_to_revision_bound_canonical_shadow_v2(&read, vec![duplicate]),
        Err(CanonicalReadShadowV2Error::DuplicateSourceRevisionBinding(_))
    ));
}

#[test]
fn revision_bound_shadow_validation_detects_revision_or_receipt_tamper() {
    let read = authoritative_read();
    let mut shadow = adapt_authoritative_read_to_revision_bound_canonical_shadow_v2(
        &read,
        vec![binding(&read, 1)],
    )
    .expect("revision-bound shadow");

    shadow.rows[0].source_revisions[0].source_revision = 2;
    assert!(matches!(
        shadow.validate(),
        Err(CanonicalReadShadowV2Error::SourceRevisionMismatch(_))
    ));

    let mut shadow = adapt_authoritative_read_to_revision_bound_canonical_shadow_v2(
        &read,
        vec![binding(&read, 1)],
    )
    .expect("revision-bound shadow");
    shadow.binding_digest = digest("tampered-shadow-binding");
    assert_eq!(
        shadow.validate(),
        Err(CanonicalReadShadowV2Error::BindingDigestMismatch)
    );
}
