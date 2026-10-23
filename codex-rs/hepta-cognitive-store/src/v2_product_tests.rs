//! Structural regressions for the real product binding type. Durable owner
//! execution is covered separately by Agentd's cognitive_store_product_writer.

use super::*;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::MemoryLifecycleV1;
use codex_hepta_cognitive_types::hnmf::MemoryScopeV1;
use codex_hepta_cognitive_types::hnmf::ModalityKindV1;
use codex_hepta_cognitive_types::hnmf::ModalitySpanRefV1;
use codex_hepta_cognitive_types::hnmf::ObservedIntervalV1;
use codex_hepta_cognitive_types::hnmf::PrivacyClassV1;
use codex_hepta_cognitive_types::hnmf::ProvenanceRefV1;
use codex_hepta_cognitive_types::hnmf::RetentionPolicyV1;
use codex_hepta_cognitive_types::hnmf::SpanRangeV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;

fn id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).expect("fixture identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn contract_digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(digest(value)).expect("nonzero fixture digest")
}

fn product_binding() -> CanonicalProductMemoryEventBindingV1 {
    let event = MemoryEventV1 {
        event_id: id("event:product-profile"),
        episode_id: id("episode:product-profile"),
        scope: MemoryScopeV1::AgentPrivate {
            agent_id: id("agent:product-profile"),
        },
        observed_interval: ObservedIntervalV1 {
            start_unix_ms: 1,
            end_unix_ms: None,
        },
        modality_spans: vec![ModalitySpanRefV1 {
            span_id: id("span:product-profile"),
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
        semantic_keys: BTreeSet::from(["profile".to_string()]),
        provenance: vec![ProvenanceRefV1 {
            source_id: id("source:product-profile"),
            source_revision: 1,
            source_sha256: contract_digest("source"),
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
    };
    let mut durable_binding = CanonicalDurableMemoryEventBindingV1 {
        event_id: event.event_id.clone(),
        event_digest: canonical_contract_digest_bound_v1(&event).expect("bound digest"),
        production_receipt_digest: digest("receipt"),
        operation_digest: digest("operation"),
        source_revision: 1,
        binding_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    durable_binding.binding_digest = durable_binding.compute_binding_digest();
    let consumer_binding = bind_memory_event_consumer_v1(
        id(&format!("operation:{}", durable_binding.operation_digest)),
        CanonicalConsumerV1::CognitiveStore,
        &event,
        durable_binding.production_receipt_digest,
        durable_binding.operation_digest,
        Some(durable_binding.binding_digest),
        CanonicalMigrationPostureV1::CompatibilityBound,
    )
    .expect("consumer binding");
    CanonicalProductMemoryEventBindingV1 {
        durable_binding,
        consumer_binding,
        canonical_event: Validated::new(event).expect("checked event"),
    }
}

#[test]
fn product_binding_keeps_distinct_digest_profiles_for_one_checked_payload() {
    let binding = product_binding();
    assert_ne!(
        binding.durable_binding.event_digest,
        binding.consumer_binding.canonical_payload_sha256.digest()
    );
    binding
        .validate()
        .expect("different domains are not a semantic mismatch");
    assert_eq!(
        canonical_contract_digest_v1(binding.canonical_event().as_inner()).expect("frozen digest"),
        binding.consumer_binding.canonical_payload_sha256.digest()
    );
}

#[test]
fn product_binding_rejects_cross_profile_substitution_after_resealing() {
    let mut binding = product_binding();
    binding.consumer_binding.canonical_payload_sha256 =
        ContractDigestV1::from_digest(binding.durable_binding.event_digest).expect("digest");
    binding.consumer_binding.binding_sha256 = binding
        .consumer_binding
        .compute_binding_sha256()
        .expect("recomputed structural hash");
    assert_eq!(
        binding.validate(),
        Err(CognitiveStoreV2Error::CanonicalProductBindingMismatch)
    );
}

#[test]
fn product_binding_rejects_different_payload_even_with_equal_event_identity() {
    let mut binding = product_binding();
    let mut changed = binding.canonical_event().as_inner().clone();
    changed.objective_digest = contract_digest("other objective");
    binding.canonical_event = Validated::new(changed).expect("individually valid event");
    assert_eq!(
        binding.validate(),
        Err(CognitiveStoreV2Error::CanonicalProductBindingMismatch)
    );
}

#[test]
fn product_binding_rejects_resealed_operation_consumer_source_and_snapshot_substitution() {
    for field in 0..5 {
        let mut binding = product_binding();
        match field {
            0 => binding.consumer_binding.operation_id = id("operation:other"),
            1 => binding.consumer_binding.consumer = CanonicalConsumerV1::CognitiveRead,
            2 => binding.consumer_binding.source_identity_sha256 = contract_digest("other source"),
            3 => binding.consumer_binding.source_snapshot_sha256 = contract_digest("other cut"),
            _ => {
                binding.consumer_binding.compatibility_payload_sha256 =
                    Some(contract_digest("other compatibility payload"));
            }
        }
        binding.consumer_binding.binding_sha256 = binding
            .consumer_binding
            .compute_binding_sha256()
            .expect("recomputed structural hash");
        binding
            .consumer_binding
            .validate()
            .expect("valid raw binding");
        assert_eq!(
            binding.validate(),
            Err(CognitiveStoreV2Error::CanonicalProductBindingMismatch),
            "substitution field {field}"
        );
    }
}

fn empty_store() -> AdmittedCognitiveStoreV2 {
    let key = CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
        scope_id: StableId::new("scope:lease").expect("scope"),
        purpose_id: StableId::new("purpose:lease").expect("purpose"),
        memory_ledger_frontier: 1,
        knowledge_fact_frontier: 0,
        tombstone_frontier: 0,
        source_ledger_frontier: 1,
        knowledge_graph_generation: Generation::new(1).expect("generation"),
        compact_checkpoint_generation: Generation::new(1).expect("generation"),
        prompt_registry_revision: Revision::new(1).expect("revision"),
        retrieval_profile_digest: digest("retrieval"),
        encoder_preprocessor_digest: digest("encoder"),
        authority_epoch: 1,
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
    })
    .expect("snapshot key");
    AdmittedCognitiveStoreV2::new(key, digest("fence"), 2).expect("store")
}

#[test]
fn existing_store_snapshots_reject_use_before_open_and_at_expiry() {
    let store = empty_store();
    let vector = &store.snapshot_key().vector;
    let snapshot = store
        .open_snapshot(
            100,
            SnapshotOpenRequestV2 {
                request_id: StableId::new("request:lease").expect("request"),
                scope_id: vector.scope_id.clone(),
                purpose_id: vector.purpose_id.clone(),
                minimum_memory_frontier: 1,
                minimum_tombstone_frontier: 0,
                authority_epoch: 1,
                deadline_unix_ms: 200,
                lease_duration_ms: 10,
            },
        )
        .expect("existing owner snapshot");
    snapshot.validate(100).expect("open boundary is inclusive");
    snapshot.validate(109).expect("valid final millisecond");
    for now in [99, 110] {
        assert_eq!(
            snapshot.validate(now),
            Err(CognitiveStoreV2Error::SnapshotLeaseExpired)
        );
    }
    let page = store
        .open_snapshot_page(
            100,
            SnapshotPageOpenRequestV2 {
                request_id: StableId::new("request:page").expect("request"),
                scope_id: vector.scope_id.clone(),
                purpose_id: vector.purpose_id.clone(),
                minimum_memory_frontier: 1,
                minimum_tombstone_frontier: 0,
                authority_epoch: 1,
                deadline_unix_ms: 200,
                lease_duration_ms: 10,
                maximum_records: 1,
                after: None,
            },
        )
        .expect("existing owner page");
    page.validate(100).expect("valid page");
    for now in [99, 110] {
        assert_eq!(
            page.validate(now),
            Err(CognitiveStoreV2Error::SnapshotLeaseExpired)
        );
    }
}
