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
        valid_from_unix_ms: 1,
        valid_to_unix_ms: None,
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
        eligibility_ppm: 0,
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
        weight_proposals: vec![WeightProposalV1 {
            source_node_id: id("node:1"),
            target_node_id: id("node:2"),
            relation: SynapseRelationV1::Associative,
            old_weight_q16: 0,
            new_weight_q16: 2_048,
            delta_ppm: 31_250,
        }],
        threshold_proposals: vec![ThresholdProposalV1 {
            node_id: id("node:1"),
            old_threshold_q16: 0,
            new_threshold_q16: -2_048,
            delta_ppm: -31_250,
        }],
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
    assert_eq!(
        canonical_contract_digest_v1(&event())
            .expect("canonical event digest")
            .to_string(),
        "22d5a29e55ad08c3541eb8eb9afe577eb5efd1a75e0d37ea1c64eae436db0540"
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
fn all_registered_v1_contracts_have_distinct_cross_language_golden_digests() {
    let values = [
        (
            canonical_contract_digest_v1(&text_span()).expect("span"),
            "1e1c8f2232a1f6ddfea98400f3c2ae9d29ecd39ae2a2ff0e0bac70f91f0ad273",
        ),
        (
            canonical_contract_digest_v1(&event()).expect("event"),
            "22d5a29e55ad08c3541eb8eb9afe577eb5efd1a75e0d37ea1c64eae436db0540",
        ),
        (
            canonical_contract_digest_v1(&cross_binding()).expect("binding"),
            "4f85c20ffc206e5fe472dfd5be8ab7a71e5d79eb8661bce6dcb5a8f8284b777f",
        ),
        (
            canonical_contract_digest_v1(&engram_node()).expect("engram"),
            "5b7f4f5addf00b7e331d6682e9fb5be99dbc438d4cfc915ac536e8a16dcb23c5",
        ),
        (
            canonical_contract_digest_v1(&synapse()).expect("synapse"),
            "1649b8d6d428cd485dfbf2c46b2b0b82f41baec6c1cd0bee5da7a511cad93d6c",
        ),
        (
            canonical_contract_digest_v1(&cue()).expect("cue"),
            "27adab5830e8849e2ac765bf69728bfb10d000caaa639c84e2cec9e3adec5a00",
        ),
        (
            canonical_contract_digest_v1(&recall_packet()).expect("recall"),
            "0a3ec1c285ce6f7c710c975c79497a870c2d9c6a91696e22c16a11c43b0983fc",
        ),
        (
            canonical_contract_digest_v1(&outcome()).expect("outcome"),
            "78294b30bac6687f2332b4294471d3ba609bb827e0b01ec77280e2eeedc07a0d",
        ),
        (
            canonical_contract_digest_v1(&replay_receipt()).expect("replay"),
            "94f4265ca6c39c314e1d350aba45d78dd6b9aa973bfd740f8bb81df0995a5787",
        ),
        (
            canonical_contract_digest_v1(&plasticity()).expect("plasticity"),
            "779fc9779a6a170aba791fd4c984eb35855d5cbc394c37945123bc0ddf8dd41a",
        ),
        (
            canonical_contract_digest_v1(&topology()).expect("topology"),
            "83fed9c7f5a4677f9564ac36b524cf8865effc27f032ca465d4368c114ac40aa",
        ),
        (
            canonical_contract_digest_v1(&forget()).expect("forget"),
            "f0f4f746a2c2e3f5a22bd5d5ce1760185d5c6579ef0bb6e5a23b1722edbfd62b",
        ),
    ];
    assert!(values.iter().all(|(value, _)| !value.is_zero()));
    assert_eq!(
        values
            .iter()
            .map(|(value, _)| *value)
            .collect::<BTreeSet<_>>()
            .len(),
        12
    );
    for (actual, expected) in values {
        assert_eq!(actual.to_string(), expected);
    }
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

#[test]
fn recall_receipts_bind_counts_and_population_limits() {
    let mut mismatched = recall_packet();
    mismatched.resource_receipt.active_node_count = 2;
    assert!(mismatched.validate().is_err());

    let mut overfull = recall_packet();
    overfull.active_nodes = (0..=MAX_ACTIVE_PER_POPULATION)
        .map(|index| ActiveNodeV1 {
            node_id: id(&format!("node:{index:03}")),
            population: EngramPopulationV1::SemanticConcept,
            activation_ppm: 1,
        })
        .collect();
    overfull.resource_receipt.node_count =
        u16::try_from(overfull.active_nodes.len()).expect("bounded node count");
    overfull.resource_receipt.active_node_count =
        u16::try_from(overfull.active_nodes.len()).expect("bounded active count");
    assert!(overfull.validate().is_err());
}

#[test]
fn recall_abstention_and_selected_revision_are_fail_closed() {
    let mut contradictory = recall_packet();
    contradictory.abstain = Some(RecallAbstainReasonV1::LowConfidence);
    assert_eq!(
        contradictory.validate(),
        Err(HnmfContractError::Invalid(
            "abstaining recall contains selected events"
        ))
    );

    let mut zero_revision = recall_packet();
    zero_revision.selected_events[0].revision = 0;
    assert_eq!(
        zero_revision.validate(),
        Err(HnmfContractError::ZeroValue("selectedEvent.revision"))
    );

    let mut empty_success = recall_packet();
    empty_success.selected_events.clear();
    assert_eq!(
        empty_success.validate(),
        Err(HnmfContractError::Invalid("empty non-abstaining recall"))
    );
}

#[test]
fn q16_and_plasticity_delta_bindings_are_exact() {
    plasticity()
        .validate()
        .unwrap_or_else(|error| panic!("valid plasticity fixture: {error}"));

    let mut bad_weight_delta = plasticity();
    bad_weight_delta.weight_proposals[0].delta_ppm = 0;
    assert_eq!(
        bad_weight_delta.validate(),
        Err(HnmfContractError::Conflict("weight proposal delta"))
    );

    let mut bad_threshold_delta = plasticity();
    bad_threshold_delta.threshold_proposals[0].delta_ppm = 0;
    assert_eq!(
        bad_threshold_delta.validate(),
        Err(HnmfContractError::Conflict("threshold proposal delta"))
    );

    let mut out_of_range = synapse();
    out_of_range.weight_q16 = Q16_ONE + 1;
    assert_eq!(
        out_of_range.validate(),
        Err(HnmfContractError::Invalid("synapse weight"))
    );

    let mut bad_eligibility = synapse();
    bad_eligibility.eligibility_ppm = PPM as i32 + 1;
    assert_eq!(
        bad_eligibility.validate(),
        Err(HnmfContractError::Invalid("synapse eligibility"))
    );
}

#[test]
fn engram_validity_and_contextual_binding_are_exact() {
    let mut invalid = engram_node();
    invalid.valid_to_unix_ms = Some(invalid.valid_from_unix_ms);
    assert_eq!(
        invalid.validate(),
        Err(HnmfContractError::Invalid("engram validity interval"))
    );

    let mut event = event();
    let mut image = text_span();
    image.span_id = id("span:2");
    image.modality = ModalityKindV1::Image;
    image.range = SpanRangeV1::PixelRect {
        x: 0,
        y: 0,
        width: 1,
        height: 1,
    };
    event.modality_spans.push(image);
    let binding = cross_binding();
    event.cross_modal_bindings.push(binding.clone());
    event
        .validate()
        .unwrap_or_else(|error| panic!("valid bound event: {error}"));
    validate_cross_modal_binding_against_event_v1(&event, &binding)
        .unwrap_or_else(|error| panic!("valid contextual binding: {error}"));

    let mut drifted = binding;
    drifted.confidence_ppm = 800_000;
    assert_eq!(
        validate_cross_modal_binding_against_event_v1(&event, &drifted),
        Err(HnmfContractError::Conflict("binding/event payload"))
    );
}

#[test]
fn replay_receipts_bind_candidate_and_source_bucket_counts() {
    let mut selected_without_candidate = replay_receipt();
    selected_without_candidate.resource_receipt.candidate_count = 0;
    assert!(selected_without_candidate.validate().is_err());

    let mut bad_sum = replay_receipt();
    bad_sum.source_bucket_counts[0].selected_count = 2;
    assert!(bad_sum.validate().is_err());

    let mut duplicate_bucket = replay_receipt();
    duplicate_bucket.resource_receipt.selected_count = 2;
    duplicate_bucket.resource_receipt.candidate_count = 2;
    duplicate_bucket.selected_event_ids.push(id("event:2"));
    duplicate_bucket
        .source_bucket_counts
        .push(SourceBucketCountV1 {
            source_bucket: 1,
            selected_count: 1,
        });
    assert!(duplicate_bucket.validate().is_err());
}

#[test]
fn bounded_arbitrary_byte_decoder_smoke_covers_all_registered_contracts() {
    let mut seed = 0x9e37_79b9_7f4a_7c15_u64;
    for case in 0..256usize {
        let len = 1 + (case % 257);
        let mut bytes = vec![0u8; len];
        for byte in &mut bytes {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            *byte = seed.to_le_bytes()[0];
        }

        let _ = decode_wire_v1::<ModalitySpanRefV1>(&bytes);
        let _ = decode_wire_v1::<MemoryEventV1>(&bytes);
        let _ = decode_wire_v1::<CrossModalBindingV1>(&bytes);
        let _ = decode_wire_v1::<EngramNodeV1>(&bytes);
        let _ = decode_wire_v1::<SynapseV1>(&bytes);
        let _ = decode_wire_v1::<MemoryCueV1>(&bytes);
        let _ = decode_wire_v1::<RecallPacketV1>(&bytes);
        let _ = decode_wire_v1::<OutcomeSignalV1>(&bytes);
        let _ = decode_wire_v1::<ReplaySelectionReceiptV1>(&bytes);
        let _ = decode_wire_v1::<PlasticityBatchV1>(&bytes);
        let _ = decode_wire_v1::<TopologyProposalV1>(&bytes);
        let _ = decode_wire_v1::<ForgetPropagationReceiptV1>(&bytes);
    }
}

#[test]
fn canonical_wire_roundtrip_property_holds_across_registered_contracts() {
    macro_rules! roundtrip {
        ($value:expr, $type:ty) => {{
            let value: $type = $value;
            let bytes = encode_wire_v1(&value).expect("canonical encode");
            let decoded = decode_wire_v1::<$type>(&bytes).expect("canonical decode");
            assert_eq!(decoded, value);
            assert_eq!(
                encode_wire_v1(&decoded).expect("canonical re-encode"),
                bytes
            );
        }};
    }

    roundtrip!(text_span(), ModalitySpanRefV1);
    roundtrip!(event(), MemoryEventV1);
    roundtrip!(cross_binding(), CrossModalBindingV1);
    roundtrip!(engram_node(), EngramNodeV1);
    roundtrip!(synapse(), SynapseV1);
    roundtrip!(cue(), MemoryCueV1);
    roundtrip!(recall_packet(), RecallPacketV1);
    roundtrip!(outcome(), OutcomeSignalV1);
    roundtrip!(replay_receipt(), ReplaySelectionReceiptV1);
    roundtrip!(plasticity(), PlasticityBatchV1);
    roundtrip!(topology(), TopologyProposalV1);
    roundtrip!(forget(), ForgetPropagationReceiptV1);
}
