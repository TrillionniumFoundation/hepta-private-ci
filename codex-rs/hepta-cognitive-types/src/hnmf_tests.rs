use super::*;
use crate::wire::contract_digest;
use std::collections::BTreeSet;

fn id(value: &str) -> CanonicalIdV1 {
    CanonicalIdV1::new(value)
        .unwrap_or_else(|error| panic!("valid canonical id required: {error}"))
}

fn digest(character: char) -> Sha256DigestV1 {
    Sha256DigestV1::new(std::iter::repeat_n(character, 64).collect::<String>())
        .unwrap_or_else(|error| panic!("valid digest required: {error}"))
}

fn generation(value: u64) -> GenerationV1 {
    GenerationV1::new(value).unwrap_or_else(|error| panic!("valid generation required: {error}"))
}

fn revision(value: u64) -> RevisionV1 {
    RevisionV1::new(value).unwrap_or_else(|error| panic!("valid revision required: {error}"))
}

fn text_span() -> ModalitySpanRefV1 {
    ModalitySpanRefV1 {
        span_id: id("span:1"),
        modality: ModalityV1::Text,
        asset_sha256: digest('a'),
        range: SpanRangeV1::ByteRange { start: 0, end: 4 },
        preprocessor_manifest_sha256: digest('b'),
        feature_blob_sha256: None,
        symbolic_projection_sha256: None,
        uncertainty_ppm: 0,
        privacy_class: PrivacyClassV1::AgentPrivate,
        redaction_mask_sha256: None,
    }
}

fn image_span() -> ModalitySpanRefV1 {
    ModalitySpanRefV1 {
        span_id: id("span:image"),
        modality: ModalityV1::Image,
        asset_sha256: digest('c'),
        range: SpanRangeV1::PixelRect {
            x: 0,
            y: 0,
            width: 8,
            height: 8,
        },
        preprocessor_manifest_sha256: digest('d'),
        feature_blob_sha256: None,
        symbolic_projection_sha256: None,
        uncertainty_ppm: 10,
        privacy_class: PrivacyClassV1::AgentPrivate,
        redaction_mask_sha256: None,
    }
}

fn event(lifecycle: MemoryLifecycleV1) -> MemoryEventV1 {
    MemoryEventV1 {
        event_id: id("event:2"),
        episode_id: id("episode:1"),
        scope: MemoryScopeV1::AgentPrivate {
            agent_id: id("agent:a"),
        },
        observed_interval: ObservedIntervalV1 {
            start_unix_ms: 1,
            end_unix_ms: None,
        },
        modality_spans: vec![text_span()],
        cross_modal_bindings: Vec::new(),
        semantic_keys: BTreeSet::from(["alpha".to_string()]),
        causal_parents: BTreeSet::from([id("event:1")]),
        temporal_neighbors: BTreeSet::new(),
        provenance: BTreeSet::from([ProvenanceRefV1 {
            source_id: id("source:1"),
            source_revision: revision(1),
            source_sha256: digest('e'),
            observed_at_unix_ms: 1,
        }]),
        verification: MemoryVerificationV1::Verified,
        retention_policy: RetentionPolicyV1 {
            policy_id: id("retention:default"),
            expires_unix_ms: None,
            legal_hold: false,
        },
        objective_digest: digest('f'),
        ndu_state_digest: digest('1'),
        lifecycle,
    }
}

#[test]
fn ctype_01_modality_units_are_not_interchangeable() {
    let mut span = text_span();
    span.range = SpanRangeV1::SampleRange {
        start: 0,
        end: 4,
        sample_rate_hz: 48_000,
    };
    assert_eq!(
        span.validate(),
        Err(CognitiveContractError::Invalid(
            "span range kind does not match modality"
        ))
    );
}

#[test]
fn ctype_02_asset_bounds_and_selectors_fail_closed() {
    let mut span = image_span();
    span.range = SpanRangeV1::PixelRect {
        x: 7,
        y: 0,
        width: 2,
        height: 8,
    };
    let manifest = AssetManifestV1 {
        asset_sha256: digest('c'),
        modality: ModalityV1::Image,
        extent: AssetExtentV1::Pixels {
            width: 8,
            height: 8,
        },
    };
    assert_eq!(
        span.validate_against_asset(&manifest),
        Err(CognitiveContractError::Invalid(
            "image rectangle outside asset"
        ))
    );

    let mut ast = text_span();
    ast.span_id = id("span:ast");
    ast.modality = ModalityV1::CodeAst;
    ast.range = SpanRangeV1::AstPath {
        path: String::new(),
    };
    assert_eq!(
        ast.validate(),
        Err(CognitiveContractError::Invalid("AST path"))
    );
}

#[test]
fn ctype_03_correction_and_tombstone_are_distinct_semantics() {
    let correction = event(MemoryLifecycleV1::Correction {
        predecessor_event_id: id("event:1"),
    });
    let tombstone = event(MemoryLifecycleV1::Tombstone {
        target_event_id: id("event:1"),
        reason_sha256: digest('2'),
    });
    correction
        .validate()
        .unwrap_or_else(|error| panic!("valid correction event: {error}"));
    tombstone
        .validate()
        .unwrap_or_else(|error| panic!("valid tombstone event: {error}"));
    let correction_digest = contract_digest(&correction)
        .unwrap_or_else(|error| panic!("correction digest: {error}"));
    let tombstone_digest =
        contract_digest(&tombstone).unwrap_or_else(|error| panic!("tombstone digest: {error}"));
    assert_ne!(correction_digest, tombstone_digest);
}

#[test]
fn cross_modal_binding_requires_distinct_modalities() {
    let text = text_span();
    let image = image_span();
    let mut value = event(MemoryLifecycleV1::Active);
    value.modality_spans = vec![text, image];
    value.cross_modal_bindings = vec![CrossModalBindingV1 {
        binding_id: id("binding:1"),
        event_id: id("event:2"),
        span_refs: BTreeSet::from([id("span:1"), id("span:image")]),
        alignment_kind: AlignmentKindV1::SameObservation,
        confidence_ppm: 900_000,
        producer_manifest_sha256: digest('3'),
    }];
    value
        .validate()
        .unwrap_or_else(|error| panic!("valid multimodal event: {error}"));

    value.modality_spans[1].modality = ModalityV1::Text;
    value.modality_spans[1].range = SpanRangeV1::ByteRange { start: 4, end: 8 };
    assert!(value.validate().is_err());
}

#[test]
fn next_snapshot_contracts_cannot_self_activate() {
    let plasticity = PlasticityBatchV1 {
        predecessor_generation: generation(1),
        next_generation: generation(2),
        outcome_signal_digest: digest('4'),
        weight_proposals: Vec::new(),
        threshold_proposals: Vec::new(),
        current_snapshot_immutable: true,
        production_activation_allowed: false,
    };
    plasticity
        .validate()
        .unwrap_or_else(|error| panic!("valid plasticity: {error}"));

    let mut activating = plasticity;
    activating.production_activation_allowed = true;
    assert!(activating.validate().is_err());

    let topology = TopologyProposalV1 {
        predecessor_generation: generation(1),
        next_generation: generation(2),
        operation: TopologyOperationV1::Add,
        subject_ids: BTreeSet::from([id("node:new")]),
        capability_typed: true,
        sandbox_only: true,
        operator_accepted: false,
        production_activation_allowed: false,
    };
    topology
        .validate()
        .unwrap_or_else(|error| panic!("valid topology proposal: {error}"));

    let forget = ForgetPropagationReceiptV1 {
        event_id: id("event:1"),
        predecessor_generation: generation(1),
        next_generation: generation(2),
        retired_node_ids: BTreeSet::from([id("node:1")]),
        retired_synapses: BTreeSet::new(),
        projection_rebuild_required: true,
        artifact_revocation_required: true,
    };
    forget
        .validate()
        .unwrap_or_else(|error| panic!("valid forget receipt: {error}"));
}

#[test]
fn recall_packet_requires_supported_non_abstaining_output() {
    let packet = RecallPacketV1 {
        cue_digest: digest('5'),
        event_snapshot_digest: digest('6'),
        engram_snapshot_digest: digest('7'),
        selected_events: BTreeSet::new(),
        active_nodes: BTreeSet::new(),
        activation_paths: BTreeSet::new(),
        contradictions: BTreeSet::new(),
        coverage_ppm: 0,
        confidence_ppm: 0,
        ood_ppm: 0,
        abstain: None,
        resource_receipt: ResourceReceiptV1 {
            candidate_events_seen: 0,
            engram_nodes_visited: 0,
            synapses_visited: 0,
            settling_steps: 0,
            recalled_events: 0,
            truncated: false,
        },
    };
    assert!(packet.validate().is_err());

    let mut abstaining = packet;
    abstaining.abstain = Some(AbstainReasonV1::LowCoverage);
    abstaining
        .validate()
        .unwrap_or_else(|error| panic!("valid abstention packet: {error}"));
}
