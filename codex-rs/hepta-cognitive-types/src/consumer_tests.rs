use super::consumer::*;
use super::hnmf::*;
use super::hnmf_learning::*;
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
fn payload_consumer_matrix_fails_closed() {
    assert!(
        bind_recall_packet_consumer_v1(
            id("operation:bad"),
            CanonicalConsumerV1::CompactEngine,
            &recall(),
            digest('5').digest(),
            digest('6').digest(),
            None,
            CanonicalMigrationPostureV1::Native,
        )
        .is_err()
    );
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
