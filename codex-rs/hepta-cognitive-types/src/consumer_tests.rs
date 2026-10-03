use super::consumer::*;
use super::consumer_adapters::*;
use super::hnmf::*;
use super::hnmf_learning::*;
use super::wire::ContractDigestProfileV1;
use std::collections::BTreeSet;

fn id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).expect("valid id")
}

fn digest(character: char) -> ContractDigestV1 {
    ContractDigestV1::parse(&std::iter::repeat_n(character, 64).collect::<String>())
        .expect("valid digest")
}

fn event() -> MemoryEventV1 {
    MemoryEventV1 {
        event_id: id("event:consumer"),
        episode_id: id("episode:consumer"),
        scope: MemoryScopeV1::AgentPrivate {
            agent_id: id("agent:consumer"),
        },
        observed_interval: ObservedIntervalV1 {
            start_unix_ms: 1,
            end_unix_ms: None,
        },
        modality_spans: vec![ModalitySpanRefV1 {
            span_id: id("span:consumer"),
            modality: ModalityKindV1::Text,
            asset_sha256: digest('a'),
            range: SpanRangeV1::ByteRange { start: 0, end: 1 },
            preprocessor_manifest_sha256: digest('b'),
            feature_blob_sha256: None,
            symbolic_projection_sha256: None,
            uncertainty_ppm: 0,
            privacy_class: PrivacyClassV1::AgentPrivate,
            redaction_mask_sha256: None,
        }],
        cross_modal_bindings: Vec::new(),
        semantic_keys: BTreeSet::from(["consumer".to_string()]),
        provenance: vec![ProvenanceRefV1 {
            source_id: id("source:consumer"),
            source_revision: 1,
            source_sha256: digest('c'),
            observed_at_unix_ms: 1,
        }],
        verification: MemoryVerificationStateV1::Verified,
        retention_policy: RetentionPolicyV1::Persistent {
            retain_until_unix_ms: None,
        },
        objective_digest: digest('d'),
        ndu_state_digest: digest('e'),
        causal_parents: BTreeSet::new(),
        temporal_neighbors: BTreeSet::new(),
        behavior_propensity_ppm: None,
        lifecycle: MemoryLifecycleV1::Active,
    }
}

fn recall() -> RecallPacketV1 {
    RecallPacketV1 {
        cue_digest: digest('1'),
        event_snapshot_digest: digest('2'),
        engram_snapshot_digest: digest('3'),
        selected_events: vec![SelectedEventRefV1 {
            event_id: id("event:consumer"),
            revision: 1,
            event_digest: digest('4'),
        }],
        active_nodes: Vec::new(),
        activation_paths: Vec::new(),
        contradictions: Vec::new(),
        coverage_ppm: 1_000_000,
        confidence_ppm: 900_000,
        ood_ppm: 0,
        abstain: None,
        resource_receipt: RecallResourceReceiptV1 {
            candidate_event_count: 1,
            node_count: 0,
            synapse_count: 0,
            active_node_count: 0,
            settling_steps: 0,
        },
    }
}

#[test]
fn compatibility_binding_is_exact_and_currentness_required() {
    let binding = bind_memory_event_consumer_v1(
        id("operation:read"),
        CanonicalConsumerV1::CognitiveRead,
        &event(),
        digest('5').digest(),
        digest('6').digest(),
        Some(digest('7').digest()),
        CanonicalMigrationPostureV1::CompatibilityBound,
    )
    .expect("binding");
    binding.validate().expect("valid binding");

    let mut drifted = binding;
    drifted.currentness_revalidation_required = false;
    assert_eq!(
        drifted.validate(),
        Err(CanonicalConsumerBindingError::CurrentnessRevalidationRequired)
    );
}

#[test]
fn every_registered_consumer_requires_registry_authorized_migration_posture() {
    for consumer in CanonicalConsumerV1::ALL {
        let registration = registered_consumer_v1(consumer.as_str()).expect("registered consumer");
        assert!(matches!(
            registration.state,
            ConsumerConvergenceStateV1::CanonicalShadow
                | ConsumerConvergenceStateV1::RegisteredPendingCutover
        ));
        authorize_migration_posture_v1(consumer, CanonicalMigrationPostureV1::CompatibilityBound)
            .expect("compatibility-bound migration remains authorized");
        assert_eq!(
            authorize_migration_posture_v1(consumer, CanonicalMigrationPostureV1::Native),
            Err(
                CanonicalConsumerBindingError::MigrationPostureNotAuthorized {
                    consumer,
                    posture: CanonicalMigrationPostureV1::Native,
                    state: registration.state,
                }
            )
        );
        assert_eq!(
            authorize_migration_posture_v1(consumer, CanonicalMigrationPostureV1::LegacyRetired,),
            Err(
                CanonicalConsumerBindingError::MigrationPostureNotAuthorized {
                    consumer,
                    posture: CanonicalMigrationPostureV1::LegacyRetired,
                    state: registration.state,
                }
            )
        );
    }
}

#[test]
fn binding_constructor_cannot_self_promote_a_pending_consumer() {
    assert_eq!(
        bind_recall_packet_consumer_v1(
            id("operation:self-promote"),
            CanonicalConsumerV1::MemoryRetrieval,
            &recall(),
            digest('5').digest(),
            digest('6').digest(),
            None,
            CanonicalMigrationPostureV1::Native,
        ),
        Err(
            CanonicalConsumerBindingError::MigrationPostureNotAuthorized {
                consumer: CanonicalConsumerV1::MemoryRetrieval,
                posture: CanonicalMigrationPostureV1::Native,
                state: ConsumerConvergenceStateV1::RegisteredPendingCutover,
            }
        )
    );
}

#[test]
fn payload_consumer_matrix_fails_closed() {
    assert!(
        bind_recall_packet_consumer_v1(
            id("operation:bad-recall"),
            CanonicalConsumerV1::CompactEngine,
            &recall(),
            digest('5').digest(),
            digest('6').digest(),
            Some(digest('7').digest()),
            CanonicalMigrationPostureV1::CompatibilityBound,
        )
        .is_err()
    );
    for consumer in [
        CanonicalConsumerV1::MemoryRetrieval,
        CanonicalConsumerV1::IntelligenceControl,
    ] {
        assert_eq!(
            bind_memory_event_consumer_v1(
                id("operation:bad-event"),
                consumer,
                &event(),
                digest('5').digest(),
                digest('6').digest(),
                Some(digest('7').digest()),
                CanonicalMigrationPostureV1::CompatibilityBound,
            ),
            Err(CanonicalConsumerBindingError::ConsumerPayloadMismatch {
                consumer,
                payload: CanonicalPayloadKindV1::MemoryEvent,
            })
        );
    }
}

#[test]
fn compatibility_posture_cannot_omit_or_hide_legacy_digest() {
    assert!(
        bind_memory_event_consumer_v1(
            id("operation:missing"),
            CanonicalConsumerV1::CognitiveStore,
            &event(),
            digest('5').digest(),
            digest('6').digest(),
            None,
            CanonicalMigrationPostureV1::CompatibilityBound,
        )
        .is_err()
    );
    assert!(
        bind_memory_event_consumer_v1(
            id("operation:unexpected"),
            CanonicalConsumerV1::CognitiveStore,
            &event(),
            digest('5').digest(),
            digest('6').digest(),
            Some(digest('7').digest()),
            CanonicalMigrationPostureV1::Native,
        )
        .is_err()
    );
}

#[test]
fn raw_shadow_digest_equality_is_diagnostic_not_cutover_evidence() {
    let same = digest('8').digest();
    let comparison = CanonicalShadowComparisonV1::new(&COGNITIVE_STORE_CONSUMER_V1, same, same)
        .expect("shadow diagnostic");

    comparison.validate().expect("valid shadow diagnostic");
    assert!(comparison.matched());
    assert_eq!(
        comparison.comparison_profile(),
        RAW_SHADOW_DIGEST_COMPARISON_PROFILE_V1
    );
    assert!(!comparison.is_cutover_evidence());
}

#[test]
fn consumer_registration_schemas_match_runtime_adapters() {
    assert_eq!(
        COGNITIVE_READ_CONSUMER_V1.canonical_schema,
        "hepta.hnmf.memory-event.v1"
    );
    assert_eq!(
        COGNITIVE_STORE_CONSUMER_V1.canonical_schema,
        "hepta.hnmf.memory-event.v1"
    );
    assert_eq!(
        MEMORY_RETRIEVAL_CONSUMER_V1.canonical_schema,
        "hepta.hnmf.recall-packet.v1"
    );
    assert_eq!(
        COMPACT_ENGINE_CONSUMER_V1.canonical_schema,
        "hepta.hnmf.memory-event.v1"
    );
    assert_eq!(
        INTELLIGENCE_CONTROL_CONSUMER_V1.canonical_schema,
        "hepta.hnmf.recall-packet.v1"
    );
}

#[test]
fn historical_validation_preserves_retired_compatibility_evidence() {
    let binding = bind_memory_event_consumer_v1(
        id("operation:historical"),
        CanonicalConsumerV1::CognitiveRead,
        &event(),
        digest('5').digest(),
        digest('6').digest(),
        Some(digest('7').digest()),
        CanonicalMigrationPostureV1::CompatibilityBound,
    )
    .expect("current compatibility binding");

    assert_eq!(
        binding.payload_digest_profile(),
        ContractDigestProfileV1::FrozenCanonicalJsonV1
    );
    binding
        .validate_historical()
        .expect("frozen historical evidence remains structurally valid");
    assert!(!migration_posture_authorized_for_state_v1(
        ConsumerConvergenceStateV1::LegacyRetired,
        CanonicalMigrationPostureV1::CompatibilityBound,
    ));
    assert!(migration_posture_authorized_for_state_v1(
        ConsumerConvergenceStateV1::LegacyRetired,
        CanonicalMigrationPostureV1::Native,
    ));

    let mut tampered = binding;
    tampered.source_snapshot_sha256 = digest('9');
    assert_eq!(
        tampered.validate_historical(),
        Err(CanonicalConsumerBindingError::BindingDigestMismatch)
    );
}
