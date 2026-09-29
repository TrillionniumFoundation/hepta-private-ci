// Included with the existing real V1 contract fixtures; not a new test ontology.

fn test_consumer_binding(
    consumer: crate::consumer::CanonicalConsumerV1,
    operation: &str,
    source: &str,
    snapshot: &str,
) -> crate::consumer::CanonicalConsumerBindingV1 {
    crate::consumer::bind_memory_event_consumer_v1(
        id(operation),
        consumer,
        &event(),
        codex_hepta_types::Digest32::of_bytes(source.as_bytes()),
        codex_hepta_types::Digest32::of_bytes(snapshot.as_bytes()),
        Some(codex_hepta_types::Digest32::of_bytes(b"legacy encoding")),
        crate::consumer::CanonicalMigrationPostureV1::CompatibilityBound,
    )
    .expect("valid event binding")
}

fn test_recall_consumer_binding(
    consumer: crate::consumer::CanonicalConsumerV1,
    operation: &str,
    source: &str,
    snapshot: &str,
) -> crate::consumer::CanonicalConsumerBindingV1 {
    crate::consumer::bind_recall_packet_consumer_v1(
        id(operation),
        consumer,
        &recall_packet(),
        codex_hepta_types::Digest32::of_bytes(source.as_bytes()),
        codex_hepta_types::Digest32::of_bytes(snapshot.as_bytes()),
        Some(codex_hepta_types::Digest32::of_bytes(b"legacy recall")),
        crate::consumer::CanonicalMigrationPostureV1::CompatibilityBound,
    )
    .expect("valid recall binding")
}

fn assert_common_semantic_comparison<T: crate::wire::CognitiveContractV1>(
    binding: &crate::consumer::CanonicalConsumerBindingV1,
    value: T,
) {
    use crate::contract::Validated;
    use crate::handoff::CanonicalParityV1;

    assert_ne!(
        binding.compatibility_payload_sha256.expect("legacy"),
        binding.canonical_payload_sha256
    );
    let (frozen, bound) = crate::wire::canonical_contract_digests_v1(&value)
        .expect("both profiles from one checked encoding");
    assert_eq!(frozen, canonical_contract_digest_v1(&value).expect("frozen"));
    assert_eq!(
        bound,
        canonical_contract_digest_bound_v1(&value).expect("schema bound")
    );
    assert_ne!(frozen, bound);
    // These are deterministic contract fixtures, not evidence that an actual
    // product owner independently produced or authenticated the projection.
    let expected = Validated::new(value.clone()).expect("owner projection fixture");
    let wire = encode_wire_v1(&value).expect("received canonical fixture");
    let comparison = binding
        .compare_canonical_projection_v1(&expected, &wire)
        .expect("common domain comparison");
    assert_eq!(comparison.parity(), CanonicalParityV1::Matched);
    assert_eq!(comparison.observed_semantic_digest(), bound);
    assert_eq!(
        comparison.expected_semantic_digest(),
        comparison.observed_semantic_digest()
    );
    comparison
        .require_match_for_current_binding(binding)
        .expect("matching current binding");
}

#[test]
fn common_semantic_comparison_never_compares_legacy_and_canonical_digest_domains() {
    use crate::consumer::CanonicalConsumerV1;

    for consumer in CanonicalConsumerV1::ALL {
        match consumer {
            CanonicalConsumerV1::CognitiveRead
            | CanonicalConsumerV1::CognitiveStore
            | CanonicalConsumerV1::CompactEngine => {
                let binding = test_consumer_binding(consumer, "operation:parity", "source", "cut");
                assert_common_semantic_comparison(&binding, event());
            }
            CanonicalConsumerV1::MemoryRetrieval | CanonicalConsumerV1::IntelligenceControl => {
                let binding =
                    test_recall_consumer_binding(consumer, "operation:parity", "source", "cut");
                assert_common_semantic_comparison(&binding, recall_packet());
            }
        }
    }
}

#[test]
fn semantic_comparison_records_and_rejects_a_real_payload_mismatch() {
    use crate::consumer::CanonicalConsumerV1;
    use crate::contract::Validated;
    use crate::handoff::CanonicalParityV1;

    let binding =
        test_consumer_binding(CanonicalConsumerV1::CognitiveStore, "op:1", "source", "cut");
    let mut changed = event();
    changed.semantic_keys.insert("window".to_string());
    let expected = Validated::new(changed).expect("different valid owner projection");
    let wire = encode_wire_v1(&event()).expect("wire");
    let comparison = binding
        .compare_canonical_projection_v1(&expected, &wire)
        .expect("record mismatch");
    assert_eq!(comparison.parity(), CanonicalParityV1::Mismatch);
    assert_ne!(
        comparison.expected_semantic_digest(),
        comparison.observed_semantic_digest()
    );
    assert_eq!(
        comparison
            .require_match_for_current_binding(&binding)
            .expect_err("must reject")
            .field_path,
        "handoff.semanticProjection"
    );
}

#[test]
fn semantic_handoff_rejects_operation_consumer_source_and_snapshot_substitution() {
    use crate::consumer::CanonicalConsumerV1;
    use crate::contract::Validated;

    let binding =
        test_consumer_binding(CanonicalConsumerV1::CognitiveRead, "op:1", "source", "cut");
    let expected = Validated::new(event()).expect("projection");
    let wire = encode_wire_v1(&event()).expect("wire");
    let comparison = binding
        .compare_canonical_projection_v1(&expected, &wire)
        .expect("compare");
    for substituted in [
        test_consumer_binding(CanonicalConsumerV1::CognitiveRead, "op:2", "source", "cut"),
        test_consumer_binding(CanonicalConsumerV1::CognitiveStore, "op:1", "source", "cut"),
        test_consumer_binding(
            CanonicalConsumerV1::CognitiveRead,
            "op:1",
            "other-source",
            "cut",
        ),
        test_consumer_binding(
            CanonicalConsumerV1::CognitiveRead,
            "op:1",
            "source",
            "other-cut",
        ),
    ] {
        substituted
            .validate()
            .expect("individually valid alternative binding");
        assert!(
            comparison
                .require_match_for_current_binding(&substituted)
                .is_err()
        );
    }
}

fn assert_handoff_rejects_resealed_substitutions<T: crate::wire::CognitiveContractV1>(
    binding: crate::consumer::CanonicalConsumerBindingV1,
    value: T,
    other_consumer: crate::consumer::CanonicalConsumerV1,
) {
    use crate::contract::Validated;

    let expected = Validated::new(value.clone()).expect("projection fixture");
    let wire = encode_wire_v1(&value).expect("wire");
    let comparison = binding
        .compare_canonical_projection_v1(&expected, &wire)
        .expect("comparison");
    for field in 0..6 {
        let mut current = binding.clone();
        match field {
            0 => current.operation_id = id("op:substituted"),
            1 => current.consumer = other_consumer,
            2 => current.source_identity_sha256 = digest('c'),
            3 => current.source_snapshot_sha256 = digest('d'),
            4 => current.compatibility_payload_sha256 = Some(digest('e')),
            5 => current.canonical_payload_sha256 = digest('f'),
            _ => unreachable!("bounded substitution inventory"),
        }
        assert_ne!(
            current, binding,
            "the fixture must actually change field {field}"
        );
        // A malformed digest would exercise only structural validation. These
        // substitutions must remain individually valid and be refused at use.
        current.binding_sha256 = current.compute_binding_sha256().expect("reseal");
        current.validate().expect("valid alternative current binding");
        let error = comparison
            .require_match_for_current_binding(&current)
            .err()
            .expect("a different valid binding must not reuse the old handoff");
        assert_eq!(error.field_path, "handoff.currentBinding");
    }
    comparison
        .require_match_for_current_binding(&binding)
        .expect("negative checks do not mutate the original comparison");
}

#[test]
fn all_five_handoffs_reject_resealed_current_binding_substitution() {
    use crate::consumer::CanonicalConsumerV1;

    for consumer in CanonicalConsumerV1::ALL {
        match consumer {
            CanonicalConsumerV1::CognitiveRead
            | CanonicalConsumerV1::CognitiveStore
            | CanonicalConsumerV1::CompactEngine => {
                let other = if consumer == CanonicalConsumerV1::CognitiveRead {
                    CanonicalConsumerV1::CognitiveStore
                } else {
                    CanonicalConsumerV1::CognitiveRead
                };
                assert_handoff_rejects_resealed_substitutions(
                    test_consumer_binding(consumer, "op:1", "source", "cut"),
                    event(),
                    other,
                );
            }
            CanonicalConsumerV1::MemoryRetrieval | CanonicalConsumerV1::IntelligenceControl => {
                let other = if consumer == CanonicalConsumerV1::MemoryRetrieval {
                    CanonicalConsumerV1::IntelligenceControl
                } else {
                    CanonicalConsumerV1::MemoryRetrieval
                };
                assert_handoff_rejects_resealed_substitutions(
                    test_recall_consumer_binding(consumer, "op:1", "source", "cut"),
                    recall_packet(),
                    other,
                );
            }
        }
    }
}

#[test]
fn recall_consumers_compare_actual_recall_packet_projections() {
    use crate::consumer::CanonicalConsumerV1;
    use crate::consumer::CanonicalMigrationPostureV1;
    use crate::contract::Validated;
    use crate::handoff::CanonicalParityV1;
    use codex_hepta_types::Digest32;

    for consumer in [
        CanonicalConsumerV1::MemoryRetrieval,
        CanonicalConsumerV1::IntelligenceControl,
    ] {
        let packet = recall_packet();
        let binding = crate::consumer::bind_recall_packet_consumer_v1(
            id("op:recall"),
            consumer,
            &packet,
            Digest32::of_bytes(b"source"),
            Digest32::of_bytes(b"cut"),
            Some(Digest32::of_bytes(b"legacy recall")),
            CanonicalMigrationPostureV1::CompatibilityBound,
        )
        .expect("binding");
        let expected = Validated::new(packet.clone()).expect("owner projection fixture");
        let comparison = binding
            .compare_canonical_projection_v1(&expected, &encode_wire_v1(&packet).expect("wire"))
            .expect("comparison");
        assert_eq!(comparison.parity(), CanonicalParityV1::Matched);
        comparison
            .require_match_for_current_binding(&binding)
            .expect("handoff");
        assert!(
            binding
                .compare_canonical_projection_v1(
                    &Validated::new(event()).expect("event"),
                    &encode_wire_v1(&event()).expect("event wire"),
                )
                .is_err()
        );
    }
}

#[test]
fn contextual_span_proof_is_stronger_than_structural_validation() {
    use crate::context::ManifestCheckedSpanV1;
    use crate::contract::Validated;

    let span = Validated::new(text_span()).expect("structurally valid span");
    let mut manifest = AssetManifestV1 {
        asset_sha256: digest('a'),
        modality: ModalityKindV1::Text,
        extent: AssetExtentV1::Bytes { byte_len: 4 },
        preprocessor_manifest_sha256: digest('b'),
    };
    {
        let checked = ManifestCheckedSpanV1::new(&span, &manifest).expect("exact extent");
        assert_eq!(checked.span(), &span);
        assert_eq!(checked.manifest(), &manifest);
    }
    manifest.extent = AssetExtentV1::Bytes { byte_len: 3 };
    assert!(ManifestCheckedSpanV1::new(&span, &manifest).is_err());
    manifest.extent = AssetExtentV1::Bytes { byte_len: 4 };
    manifest.asset_sha256 = digest('c');
    assert!(ManifestCheckedSpanV1::new(&span, &manifest).is_err());
}

#[test]
fn contextual_binding_proof_rejects_a_binding_absent_from_its_event() {
    use crate::context::EventCheckedBindingV1;
    use crate::contract::Validated;
    let binding = Validated::new(cross_binding()).expect("structural binding");
    let event = Validated::new(event()).expect("structural event");
    assert!(EventCheckedBindingV1::new(&binding, &event).is_err());
}

#[test]
fn explicit_digest_profiles_preserve_historical_digest_and_do_not_alias() {
    let event = event();
    assert_eq!(
        ContractDigestProfileV1::FrozenCanonicalJsonV1
            .digest(&event)
            .expect("frozen profile"),
        canonical_contract_digest_v1(&event).expect("historical digest")
    );
    assert_eq!(
        ContractDigestProfileV1::SchemaBoundV1
            .digest(&event)
            .expect("bound profile"),
        canonical_contract_digest_bound_v1(&event).expect("bound digest")
    );
    assert_ne!(
        ContractDigestProfileV1::SchemaBoundV1
            .digest(&event)
            .expect("bound"),
        ContractDigestProfileV1::FrozenCanonicalJsonV1
            .digest(&event)
            .expect("frozen")
    );
}
