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
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_types::Generation;
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

fn vector() -> LaneCGenerationVectorV1 {
    LaneCGenerationVectorV1 {
        scope_id: id("scope:one"),
        purpose_id: id("purpose:read"),
        memory_ledger_frontier: 10,
        knowledge_fact_frontier: 8,
        tombstone_frontier: 4,
        source_ledger_frontier: 9,
        knowledge_graph_generation: generation(2),
        compact_checkpoint_generation: generation(1),
        prompt_registry_revision: revision(3),
        retrieval_profile_digest: digest("retrieval"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 7,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
    }
}

fn envelope() -> AuthoritativeSnapshotV1 {
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
    let snapshot = build_snapshot(generation(1), vec![record])
        .unwrap_or_else(|error| panic!("valid snapshot: {error}"));
    let key =
        CognitiveSnapshotKeyV1::new(vector()).unwrap_or_else(|error| panic!("valid key: {error}"));
    AuthoritativeSnapshotV1::new(id("provider:one"), key, snapshot, 5, 50)
        .unwrap_or_else(|error| panic!("valid envelope: {error}"))
}

fn contract_id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).unwrap_or_else(|error| panic!("valid contract id: {error}"))
}

fn contract_digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(digest(value))
        .unwrap_or_else(|error| panic!("valid contract digest: {error}"))
}

fn canonical_event() -> MemoryEventV1 {
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
            source_revision: 1,
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

fn authoritative_read_result() -> AuthoritativeReadResultV1 {
    let envelope = envelope();
    let provider = FixtureProvider {
        envelope: envelope.clone(),
    };
    let request = ReadRequestV2 {
        read_request: crate::ReadRequest {
            snapshot_digest: envelope.snapshot().snapshot_digest,
            allowed_kinds: Vec::new(),
            maximum_results: 8,
            include_tombstones: false,
        },
        maximum_encoded_bytes: crate::MAX_ENCODED_READ_RESULT_BYTES_V2,
    };
    read_authoritative(&provider, 10, acquisition_request(), request)
        .unwrap_or_else(|error| panic!("authoritative read: {error}"))
}

fn acquisition_request() -> SnapshotAcquisitionRequestV1 {
    SnapshotAcquisitionRequestV1 {
        request_id: id("request:one"),
        scope_id: id("scope:one"),
        purpose_id: id("purpose:read"),
        minimum_memory_frontier: 10,
        minimum_tombstone_frontier: 4,
        authority_epoch: 7,
        deadline_unix_ms: 40,
    }
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

#[test]
fn authoritative_read_binds_provider_vector_and_query() {
    let envelope = envelope();
    let provider = FixtureProvider {
        envelope: envelope.clone(),
    };
    let request = ReadRequestV2 {
        read_request: crate::ReadRequest {
            snapshot_digest: envelope.snapshot().snapshot_digest,
            allowed_kinds: Vec::new(),
            maximum_results: 8,
            include_tombstones: false,
        },
        maximum_encoded_bytes: crate::MAX_ENCODED_READ_RESULT_BYTES_V2,
    };
    let result = read_authoritative(&provider, 10, acquisition_request(), request)
        .unwrap_or_else(|error| panic!("authoritative read: {error}"));
    assert_eq!(result.read_result.records().len(), 1);
    assert_eq!(
        result.generation_vector_digest,
        envelope.snapshot_key().vector_digest
    );
    result
        .validate()
        .unwrap_or_else(|error| panic!("valid result: {error}"));
}

#[test]
fn provider_rejects_scope_frontier_and_epoch_drift() {
    let envelope = envelope();

    let mut request = acquisition_request();
    request.scope_id = id("scope:other");
    assert_eq!(
        envelope.validate_for_request(10, &request),
        Err(SnapshotProviderError::ScopeMismatch)
    );

    let mut request = acquisition_request();
    request.minimum_tombstone_frontier += 1;
    assert_eq!(
        envelope.validate_for_request(10, &request),
        Err(SnapshotProviderError::StaleTombstoneFrontier)
    );

    let mut request = acquisition_request();
    request.authority_epoch += 1;
    assert_eq!(
        envelope.validate_for_request(10, &request),
        Err(SnapshotProviderError::AuthorityEpochMismatch)
    );
}

#[test]
fn provider_rejects_expired_deadline_and_wrong_read_snapshot() {
    let envelope = envelope();
    assert_eq!(
        envelope.validate_for_request(50, &acquisition_request()),
        Err(SnapshotProviderError::DeadlineExpired)
    );

    let provider = FixtureProvider { envelope };
    let request = ReadRequestV2 {
        read_request: crate::ReadRequest {
            snapshot_digest: digest("wrong-snapshot"),
            allowed_kinds: Vec::new(),
            maximum_results: 1,
            include_tombstones: false,
        },
        maximum_encoded_bytes: crate::MAX_ENCODED_READ_RESULT_BYTES_V2,
    };
    assert_eq!(
        read_authoritative(&provider, 10, acquisition_request(), request),
        Err(SnapshotProviderError::ReadSnapshotMismatch)
    );
}

#[test]
fn canonical_shadow_read_binds_exact_authoritative_cut_and_record() {
    let read = authoritative_read_result();
    let record = read.read_result.records()[0].clone();
    let event = canonical_event();
    let shadow = adapt_authoritative_read_to_canonical_shadow_v1(
        &read,
        vec![CanonicalReadRecordBindingV1 {
            legacy_record_id: record.record_id.clone(),
            legacy_record_revision: record.revision,
            legacy_record_digest: record.record_digest(),
            event: event.clone(),
        }],
    )
    .unwrap_or_else(|error| panic!("canonical shadow read: {error}"));

    shadow
        .validate()
        .unwrap_or_else(|error| panic!("canonical shadow validation: {error}"));
    assert_eq!(shadow.snapshot_receipt_digest, read.snapshot_receipt_digest);
    assert_eq!(
        shadow.generation_vector_digest,
        read.generation_vector_digest
    );
    assert_eq!(
        shadow.read_receipt_digest,
        read.read_result.receipt_digest()
    );
    assert_eq!(shadow.rows.len(), 1);
    assert_eq!(shadow.rows[0].event_id, event.event_id);
    assert_ne!(shadow.rows[0].event_digest, record.record_digest());
    assert!(!shadow.authority.grants_any());
}

#[test]
fn canonical_product_read_binds_every_event_to_exact_legacy_cut() {
    let read = authoritative_read_result();
    let record = read.read_result.records()[0].clone();
    let product = adapt_authoritative_read_to_canonical_v1(
        contract_id("operation:canonical-read"),
        &read,
        vec![CanonicalReadRecordBindingV1 {
            legacy_record_id: record.record_id.clone(),
            legacy_record_revision: record.revision,
            legacy_record_digest: record.record_digest(),
            event: canonical_event(),
        }],
    )
    .unwrap_or_else(|error| panic!("canonical product read: {error}"));
    product
        .validate()
        .unwrap_or_else(|error| panic!("canonical product validation: {error}"));
    assert_eq!(product.consumer_bindings.len(), 1);
    assert!(product.consumer_bindings[0].currentness_revalidation_required);
    assert_eq!(
        product.consumer_bindings[0]
            .compatibility_payload_sha256
            .expect("legacy digest")
            .digest(),
        record.record_digest()
    );
}

#[test]
fn canonical_shadow_read_rejects_identity_provenance_and_lifecycle_drift() {
    let read = authoritative_read_result();
    let record = read.read_result.records()[0].clone();

    let mut wrong_record = CanonicalReadRecordBindingV1 {
        legacy_record_id: record.record_id.clone(),
        legacy_record_revision: record.revision,
        legacy_record_digest: digest("wrong-record"),
        event: canonical_event(),
    };
    assert_eq!(
        adapt_authoritative_read_to_canonical_shadow_v1(&read, vec![wrong_record.clone()]),
        Err(CanonicalReadShadowError::MissingExactRecordBinding(
            "memory:one".to_string()
        ))
    );

    wrong_record.legacy_record_digest = record.record_digest();
    wrong_record.event.provenance[0].source_sha256 = contract_digest("wrong-source");
    assert_eq!(
        adapt_authoritative_read_to_canonical_shadow_v1(&read, vec![wrong_record.clone()]),
        Err(CanonicalReadShadowError::CitationProvenanceMismatch(
            "memory:one".to_string()
        ))
    );

    wrong_record.event = canonical_event();
    wrong_record.event.lifecycle = MemoryLifecycleV1::Tombstoned {
        reason_sha256: contract_digest("reason"),
    };
    assert_eq!(
        adapt_authoritative_read_to_canonical_shadow_v1(&read, vec![wrong_record]),
        Err(CanonicalReadShadowError::LifecycleMismatch(
            "memory:one".to_string()
        ))
    );
}

#[test]
fn canonical_shadow_read_tamper_fails_closed() {
    let read = authoritative_read_result();
    let record = read.read_result.records()[0].clone();
    let mut shadow = adapt_authoritative_read_to_canonical_shadow_v1(
        &read,
        vec![CanonicalReadRecordBindingV1 {
            legacy_record_id: record.record_id.clone(),
            legacy_record_revision: record.revision,
            legacy_record_digest: record.record_digest(),
            event: canonical_event(),
        }],
    )
    .unwrap_or_else(|error| panic!("canonical shadow read: {error}"));

    shadow.rows[0].legacy_record_digest = digest("tampered");
    assert_eq!(
        shadow.validate(),
        Err(CanonicalReadShadowError::BindingDigestMismatch)
    );

    let mut event_tampered = adapt_authoritative_read_to_canonical_shadow_v1(
        &read,
        vec![CanonicalReadRecordBindingV1 {
            legacy_record_id: record.record_id.clone(),
            legacy_record_revision: record.revision,
            legacy_record_digest: record.record_digest(),
            event: canonical_event(),
        }],
    )
    .unwrap_or_else(|error| panic!("canonical shadow read: {error}"));
    event_tampered.rows[0]
        .event
        .semantic_keys
        .insert("window".to_string());
    assert_eq!(
        event_tampered.validate(),
        Err(CanonicalReadShadowError::EventDigestMismatch(
            "memory:one".to_string()
        ))
    );
}

#[test]
fn canonical_read_rejects_duplicate_event_even_with_recomputed_integrity() {
    let read = authoritative_read_result();
    let record = read.read_result.records()[0].clone();
    let mut shadow = adapt_authoritative_read_to_canonical_shadow_v1(
        &read,
        vec![CanonicalReadRecordBindingV1 {
            legacy_record_id: record.record_id.clone(),
            legacy_record_revision: record.revision,
            legacy_record_digest: record.record_digest(),
            event: canonical_event(),
        }],
    )
    .expect("initial canonical read");
    let mut duplicate = shadow.rows[0].clone();
    duplicate.legacy_record_id = id("memory:other");
    shadow.rows.push(duplicate);
    shadow.binding_digest = shadow.compute_binding_digest();
    assert_eq!(
        shadow.validate(),
        Err(CanonicalReadShadowError::DuplicateCanonicalEvent)
    );
}
