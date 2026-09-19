use std::collections::BTreeSet;

use crate::hnmf::*;
use crate::hnmf_learning::*;
use crate::wire::*;

fn id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(character: char) -> ContractDigestV1 {
    ContractDigestV1::parse(&std::iter::repeat_n(character, 64).collect::<String>())
        .unwrap_or_else(|error| panic!("valid digest: {error}"))
}

fn generation(value: u64) -> ContractGenerationV1 {
    ContractGenerationV1::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

fn text_span() -> ModalitySpanRefV1 {
    ModalitySpanRefV1 {
        span_id: id("span:1"),
        modality: ModalityKindV1::Text,
        asset_sha256: digest('a'),
        range: SpanRangeV1::ByteRange { start: 0, end: 4 },
        preprocessor_manifest_sha256: digest('b'),
        feature_blob_sha256: None,
        symbolic_projection_sha256: None,
        uncertainty_ppm: 10_000,
        privacy_class: PrivacyClassV1::AgentPrivate,
        redaction_mask_sha256: None,
    }
}

fn event() -> MemoryEventV1 {
    MemoryEventV1 {
        event_id: id("event:1"),
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
        semantic_keys: BTreeSet::from(["door".to_string()]),
        provenance: vec![ProvenanceRefV1 {
            source_id: id("source:1"),
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
        behavior_propensity_ppm: Some(500_000),
        lifecycle: MemoryLifecycleV1::Active,
    }
}

fn cross_binding() -> CrossModalBindingV1 {
    CrossModalBindingV1 {
        binding_id: id("binding:1"),
        event_id: id("event:1"),
        span_refs: BTreeSet::from([id("span:1"), id("span:2")]),
        alignment_kind: AlignmentKindV1::SameObservation,
        confidence_ppm: 900_000,
        producer_manifest_sha256: digest('f'),
    }
}

fn engram_node() -> EngramNodeV1 {
    EngramNodeV1 {
        node_id: id("node:1"),
        population: EngramPopulationV1::SemanticConcept,
        modality_mask: BTreeSet::from([ModalityKindV1::Text]),
        semantic_keys: BTreeSet::from(["door".to_string()]),
        support_manifest_sha256: digest('1'),
        threshold_q16: 12,
        target_activity_ppm: 100_000,
        confidence_ppm: 900_000,
        snapshot_generation: generation(1),
    }
}

fn synapse() -> SynapseV1 {
    SynapseV1 {
        source_node_id: id("node:1"),
        target_node_id: id("node:2"),
        relation: SynapseRelationV1::Associative,
        weight_q16: 100,
        delay_steps: 1,
        plasticity_class: PlasticityClassV1::EligibilityGated,
        support_manifest_sha256: digest('2'),
        snapshot_generation: generation(1),
    }
}

fn cue() -> MemoryCueV1 {
    MemoryCueV1 {
        cue_id: id("cue:1"),
        objective_digest: digest('3'),
        ndu_state_digest: digest('4'),
        modalities: BTreeSet::from([ModalityKindV1::Text]),
        semantic_keys: BTreeSet::from(["door".to_string()]),
        seed_node_ids: BTreeSet::from([id("node:1")]),
        now_unix_ms: 10,
        resource_budget: RecallResourceBudgetV1::default(),
    }
}

fn recall_packet() -> RecallPacketV1 {
    RecallPacketV1 {
        cue_digest: digest('5'),
        event_snapshot_digest: digest('6'),
        engram_snapshot_digest: digest('7'),
        selected_events: vec![SelectedEventRefV1 {
            event_id: id("event:1"),
            revision: 1,
            event_digest: digest('8'),
        }],
        active_nodes: vec![ActiveNodeV1 {
            node_id: id("node:1"),
            population: EngramPopulationV1::SemanticConcept,
            activation_ppm: 800_000,
        }],
        activation_paths: Vec::new(),
        contradictions: Vec::new(),
        coverage_ppm: 900_000,
        confidence_ppm: 800_000,
        ood_ppm: 100_000,
        abstain: None,
        resource_receipt: RecallResourceReceiptV1 {
            candidate_event_count: 1,
            node_count: 1,
            synapse_count: 0,
            active_node_count: 1,
            settling_steps: 1,
        },
    }
}

fn outcome() -> OutcomeSignalV1 {
    OutcomeSignalV1 {
        episode_id: id("episode:1"),
        utility_delta_ppm: 10_000,
        prediction_error_ppm: 20_000,
        novelty_ppm: 30_000,
        risk_ppm: 40_000,
        ood_ppm: 50_000,
        observer_digest: digest('9'),
    }
}

fn replay_receipt() -> ReplaySelectionReceiptV1 {
    ReplaySelectionReceiptV1 {
        candidate_set_digest: digest('a'),
        selected_event_ids: vec![id("event:1")],
        source_bucket_counts: vec![SourceBucketCountV1 {
            source_bucket: 1,
            selected_count: 1,
        }],
        selection_policy_digest: digest('b'),
        resource_receipt: ReplayResourceReceiptV1 {
            candidate_count: 1,
            selected_count: 1,
            maximum_per_source_bucket: 1,
        },
    }
}

fn plasticity() -> PlasticityBatchV1 {
    PlasticityBatchV1 {
        predecessor_generation: generation(1),
        next_generation: generation(2),
        outcome_signal_digest: digest('c'),
        weight_proposals: Vec::new(),
        threshold_proposals: Vec::new(),
        current_snapshot_immutable: true,
        production_activation_allowed: false,
    }
}

fn topology() -> TopologyProposalV1 {
    TopologyProposalV1 {
        proposal_id: id("topology-proposal:1"),
        predecessor_topology_digest: digest('d'),
        operation: TopologyOperationV1::Add,
        typed_nodes_edges: TopologyTypedNodesEdgesV1 {
            nodes: vec![TopologyNodeSpecV1 {
                node_id: id("node:3"),
                population: EngramPopulationV1::MetaMemory,
                label: "new-node".to_string(),
            }],
            edges: Vec::new(),
        },
        compatibility_plan_digest: digest('e'),
        resource_delta: TopologyResourceDeltaV1 {
            node_delta: 1,
            edge_delta: 0,
            resident_bytes_upper_bound_delta: 4_096,
        },
        security_review_digest: digest('f'),
        lesion_plan_digest: digest('1'),
        rollback_plan_digest: digest('2'),
        state: TopologyProposalStateV1::QualificationRequired,
    }
}

fn forget() -> ForgetPropagationReceiptV1 {
    ForgetPropagationReceiptV1 {
        event_id: id("event:1"),
        predecessor_generation: generation(1),
        next_generation: generation(2),
        retired_node_ids: vec![id("node:1")],
        retired_synapses: Vec::new(),
        projection_rebuild_required: true,
        artifact_revocation_required: true,
    }
}

#[test]
fn ctype_01_modality_units_cannot_be_rebound() {
    let mut span = text_span();
    span.range = SpanRangeV1::SampleRange {
        start: 0,
        end: 4,
        sample_rate_hz: 48_000,
    };
    assert_eq!(
        span.validate(),
        Err(HnmfContractError::Invalid(
            "span range kind does not match modality"
        ))
    );
}

#[test]
fn ctype_02_asset_extent_and_identity_fail_closed() {
    let mut image = text_span();
    image.span_id = id("span:image");
    image.modality = ModalityKindV1::Image;
    image.range = SpanRangeV1::PixelRect {
        x: 9,
        y: 9,
        width: 2,
        height: 2,
    };
    let manifest = AssetManifestV1 {
        asset_sha256: image.asset_sha256,
        modality: ModalityKindV1::Image,
        extent: AssetExtentV1::Image {
            width: 10,
            height: 10,
        },
        preprocessor_manifest_sha256: image.preprocessor_manifest_sha256,
    };
    assert_eq!(
        validate_span_against_manifest_v1(&manifest, &image),
        Err(HnmfContractError::Invalid("span exceeds asset extent"))
    );

    let mut wrong_asset = image.clone();
    wrong_asset.range = SpanRangeV1::PixelRect {
        x: 0,
        y: 0,
        width: 2,
        height: 2,
    };
    wrong_asset.asset_sha256 = digest('f');
    assert_eq!(
        validate_span_against_manifest_v1(&manifest, &wrong_asset),
        Err(HnmfContractError::Conflict("asset/span binding"))
    );

    let mut ast = text_span();
    ast.modality = ModalityKindV1::CodeAst;
    ast.range = SpanRangeV1::AstPath {
        path: "x".repeat(MAX_PATH_BYTES + 1),
    };
    assert!(ast.validate().is_err());
}

#[test]
fn ctype_03_lifecycle_states_are_semantically_distinct() {
    let active = event();
    let mut superseded = active.clone();
    superseded.lifecycle = MemoryLifecycleV1::Superseded {
        by_event_id: id("event:2"),
    };
    let mut tombstoned = active.clone();
    tombstoned.lifecycle = MemoryLifecycleV1::Tombstoned {
        reason_sha256: digest('f'),
    };
    let a = canonical_contract_digest_v1(&active).expect("active digest");
    let s = canonical_contract_digest_v1(&superseded).expect("superseded digest");
    let t = canonical_contract_digest_v1(&tombstoned).expect("tombstone digest");
    assert_ne!(a, s);
    assert_ne!(a, t);
    assert_ne!(s, t);
}

#[test]
fn ctype_04_canonical_wire_vector_is_exact() {
    let encoded = encode_wire_v1(&text_span()).expect("canonical span wire");
    let expected = format!(
        "{{\"contract\":\"ModalitySpanRefV1\",\"payload\":{{\"assetSha256\":\"{}\",\"featureBlobSha256\":null,\"modality\":\"text\",\"preprocessorManifestSha256\":\"{}\",\"privacyClass\":\"agent_private\",\"range\":{{\"end\":4,\"kind\":\"byte_range\",\"start\":0}},\"redactionMaskSha256\":null,\"spanId\":\"span:1\",\"symbolicProjectionSha256\":null,\"uncertaintyPpm\":10000}},\"schema\":\"hepta.hnmf.modality-span-ref.v1\",\"schemaVersion\":1}}",
        "a".repeat(64),
        "b".repeat(64)
    );
    assert_eq!(encoded, expected.as_bytes());
    assert_eq!(
        decode_wire_v1::<ModalitySpanRefV1>(&encoded).expect("decode canonical vector"),
        text_span()
    );
    assert_eq!(
        canonical_contract_digest_v1(&text_span())
            .expect("canonical digest")
            .to_string(),
        "1e1c8f2232a1f6ddfea98400f3c2ae9d29ecd39ae2a2ff0e0bac70f91f0ad273"
    );
}

#[test]
fn strict_wire_rejects_unknown_fields_invalid_enum_and_noncanonical_json() {
    let encoded = String::from_utf8(encode_wire_v1(&text_span()).expect("wire")).expect("utf8");
    let unknown = encoded.replace(
        "\"uncertaintyPpm\":10000}",
        "\"uncertaintyPpm\":10000,\"unexpected\":1}",
    );
    assert!(decode_wire_v1::<ModalitySpanRefV1>(unknown.as_bytes()).is_err());

    let invalid_enum = encoded.replace("\"modality\":\"text\"", "\"modality\":\"bogus\"");
    assert!(decode_wire_v1::<ModalitySpanRefV1>(invalid_enum.as_bytes()).is_err());

    let noncanonical = format!(" {encoded}");
    assert_eq!(
        decode_wire_v1::<ModalitySpanRefV1>(noncanonical.as_bytes())
            .expect_err("whitespace must be rejected")
            .to_string(),
        "cognitive wire bytes are not canonical V1 JSON"
    );
}

#[test]
fn maximum_bounds_reject_before_publication() {
    let mut value = event();
    value.modality_spans = (0..=MAX_MODALITY_SPANS)
        .map(|index| {
            let mut span = text_span();
            span.span_id = id(&format!("span:{index:03}"));
            span
        })
        .collect();
    assert!(value.validate().is_err());

    let mut cue = cue();
    cue.resource_budget.maximum_recurrent_steps = MAX_RECURRENT_STEPS + 1;
    assert!(cue.validate().is_err());

    let mut signal = outcome();
    signal.ood_ppm = PPM + 1;
    assert!(signal.validate().is_err());
}

#[test]
fn all_registered_v1_contracts_have_distinct_nonzero_digests() {
    let values = [
        canonical_contract_digest_v1(&text_span()).expect("span"),
        canonical_contract_digest_v1(&event()).expect("event"),
        canonical_contract_digest_v1(&cross_binding()).expect("binding"),
        canonical_contract_digest_v1(&engram_node()).expect("engram"),
        canonical_contract_digest_v1(&synapse()).expect("synapse"),
        canonical_contract_digest_v1(&cue()).expect("cue"),
        canonical_contract_digest_v1(&recall_packet()).expect("recall"),
        canonical_contract_digest_v1(&outcome()).expect("outcome"),
        canonical_contract_digest_v1(&replay_receipt()).expect("replay"),
        canonical_contract_digest_v1(&plasticity()).expect("plasticity"),
        canonical_contract_digest_v1(&topology()).expect("topology"),
        canonical_contract_digest_v1(&forget()).expect("forget"),
    ];
    assert!(values.iter().all(|value| !value.is_zero()));
    assert_eq!(values.into_iter().collect::<BTreeSet<_>>().len(), 12);
}

#[test]
fn set_insertion_order_cannot_change_wire_or_digest() {
    let left = event();
    let mut right = left.clone();
    right.semantic_keys = ["zeta".to_string(), "alpha".to_string()]
        .into_iter()
        .collect();
    let mut other = left;
    other.semantic_keys = ["alpha".to_string(), "zeta".to_string()]
        .into_iter()
        .collect();
    assert_eq!(
        encode_wire_v1(&right).expect("right"),
        encode_wire_v1(&other).expect("other")
    );
    assert_eq!(
        canonical_contract_digest_v1(&right).expect("right digest"),
        canonical_contract_digest_v1(&other).expect("other digest")
    );
}

#[test]
fn proposal_contracts_cannot_self_activate() {
    let mut batch = plasticity();
    batch.production_activation_allowed = true;
    assert!(batch.validate().is_err());

    let proposal = topology();
    proposal
        .validate()
        .unwrap_or_else(|error| panic!("valid topology proposal: {error}"));
    let encoded = encode_wire_v1(&proposal).expect("topology wire");
    let encoded = String::from_utf8(encoded).expect("topology wire utf8");
    assert!(!encoded.contains("activation"));
    assert!(encoded.contains("\"state\":\"qualification_required\""));

    let mut invalid = proposal;
    invalid.typed_nodes_edges.nodes.clear();
    assert!(invalid.validate().is_err());
}
