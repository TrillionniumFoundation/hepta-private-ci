use super::*;
use std::collections::BTreeSet;

fn digest(character: char) -> Digest32 {
    Digest32::parse(std::iter::repeat_n(character, 64).collect::<String>()).unwrap()
}

fn span(span_id: SpanId, modality: ModalityKind, range: SpanRange) -> ModalitySpanRef {
    ModalitySpanRef {
        span_id,
        modality,
        asset_sha256: digest('a'),
        range,
        preprocessor_manifest_sha256: digest('b'),
        feature_blob_sha256: Some(digest('c')),
        symbolic_projection_sha256: None,
        uncertainty_ppm: 10_000,
        privacy_class: PrivacyClass::AgentPrivate,
        redaction_mask_sha256: None,
    }
}

fn event(event_id: EventId, source: char, key: &str) -> MemoryEvent {
    MemoryEvent {
        event_id,
        episode_id: event_id,
        scope: MemoryScope::AgentPrivate {
            agent_id: "agent-a".to_string(),
        },
        observed_interval: TimeInterval {
            start_unix_ms: 1,
            end_unix_ms: None,
        },
        modality_spans: vec![span(
            event_id,
            ModalityKind::Text,
            SpanRange::ByteRange { start: 0, end: 4 },
        )],
        cross_modal_bindings: Vec::new(),
        semantic_keys: BTreeSet::from([key.to_string()]),
        provenance: vec![ProvenanceRef {
            source_id: format!("source-{event_id}"),
            source_revision: 1,
            source_sha256: digest(source),
            observed_at_unix_ms: 1,
        }],
        objective_digest: digest('d'),
        ndu_state_digest: digest('e'),
        behavior_propensity_ppm: Some(500_000),
        lifecycle: MemoryLifecycle::Active,
    }
}

fn principal() -> PrincipalScope {
    PrincipalScope {
        agent_id: "agent-a".to_string(),
        workspace_sha256: None,
    }
}

#[test]
fn digest_is_exact_lowercase_sha256_shape() {
    assert!(Digest32::parse("a".repeat(64)).is_ok());
    assert!(Digest32::parse("A".repeat(64)).is_err());
    assert!(Digest32::parse("g".repeat(64)).is_err());
}

#[test]
fn modality_range_must_match_modality() {
    assert!(
        span(
            1,
            ModalityKind::Image,
            SpanRange::ByteRange { start: 0, end: 4 }
        )
        .validate()
        .is_err()
    );
    assert!(
        span(
            1,
            ModalityKind::Image,
            SpanRange::PixelRect {
                x: 0,
                y: 0,
                width: 8,
                height: 8,
            }
        )
        .validate()
        .is_ok()
    );
}

#[test]
fn cross_modal_binding_requires_distinct_modalities() {
    let text = span(
        1,
        ModalityKind::Text,
        SpanRange::ByteRange { start: 0, end: 4 },
    );
    let image = span(
        2,
        ModalityKind::Image,
        SpanRange::PixelRect {
            x: 0,
            y: 0,
            width: 8,
            height: 8,
        },
    );
    let mut value = event(7, 'a', "door");
    value.modality_spans = vec![text, image];
    value.cross_modal_bindings = vec![CrossModalBinding {
        binding_id: 1,
        event_id: 7,
        span_ids: BTreeSet::from([1, 2]),
        alignment_kind: AlignmentKind::SameObservation,
        confidence_ppm: 900_000,
        producer_manifest_sha256: digest('f'),
    }];
    assert!(value.validate().is_ok());
    value.modality_spans[1] = span(
        2,
        ModalityKind::Text,
        SpanRange::ByteRange { start: 4, end: 8 },
    );
    assert!(value.validate().is_err());
}

#[test]
fn scope_and_span_privacy_are_exact() {
    let mut value = event(1, 'a', "alpha");
    value.modality_spans[0].privacy_class = PrivacyClass::WorkspacePrivate;
    assert_eq!(
        value.validate(),
        Err(ContractError::Conflict(
            "span privacy class does not match event scope"
        ))
    );
}

#[test]
fn event_projection_preserves_objective_ndu_and_source() {
    let value = event(1, 'a', "alpha");
    let view = KernelEventView::try_from(&value).unwrap();
    assert_eq!(view.objective_digest, digest('d'));
    assert_eq!(view.ndu_state_digest, digest('e'));
    assert_eq!(view.source_sha256, BTreeSet::from([digest('a')]));
}

#[test]
fn event_identity_is_idempotent_but_conflicting_reuse_fails() {
    let mut ledger = ContractLedger::default();
    let value = event(1, 'a', "alpha");
    ledger.append_event(value.clone()).unwrap();
    ledger.append_event(value).unwrap();
    assert_eq!(
        ledger.append_event(event(1, 'b', "beta")),
        Err(ContractError::Conflict(
            "event identity reused with different content"
        ))
    );
}

#[test]
fn association_expands_across_event_boundaries() {
    let mut ledger = ContractLedger::default();
    ledger.append_event(event(1, 'a', "door")).unwrap();
    ledger.append_event(event(2, 'b', "alarm")).unwrap();
    ledger.bind_node(10, BTreeSet::from([1])).unwrap();
    ledger.bind_node(20, BTreeSet::from([2])).unwrap();
    ledger.connect(10, 20).unwrap();
    let graph = ledger
        .expand_associative_subgraph(&BTreeSet::from([10]), &principal(), 10, 2, 16)
        .unwrap();
    assert_eq!(graph.nodes, BTreeSet::from([10, 20]));
    assert_eq!(graph.readable_events, BTreeSet::from([1, 2]));
}

#[test]
fn source_revocation_prevents_graph_resurrection() {
    let mut ledger = ContractLedger::default();
    ledger.append_event(event(1, 'a', "door")).unwrap();
    ledger.append_event(event(2, 'b', "alarm")).unwrap();
    ledger.bind_node(10, BTreeSet::from([1])).unwrap();
    ledger.bind_node(20, BTreeSet::from([2])).unwrap();
    ledger.connect(10, 20).unwrap();
    assert_eq!(ledger.revoke_source(digest('b')), BTreeSet::from([2]));
    let graph = ledger
        .expand_associative_subgraph(&BTreeSet::from([10]), &principal(), 10, 2, 16)
        .unwrap();
    assert_eq!(graph.nodes, BTreeSet::from([10]));
    assert_eq!(graph.readable_events, BTreeSet::from([1]));
}

#[test]
fn graph_bounds_fail_closed() {
    let mut ledger = ContractLedger::default();
    ledger.append_event(event(1, 'a', "door")).unwrap();
    ledger.bind_node(10, BTreeSet::from([1])).unwrap();
    assert!(
        ledger
            .expand_associative_subgraph(
                &BTreeSet::from([10]),
                &principal(),
                10,
                MAX_GRAPH_HOPS + 1,
                16,
            )
            .is_err()
    );
}

#[test]
fn authority_posture_is_compile_time_false() {
    let posture = [
        std::hint::black_box(CURRENT_RUN_MUTATION_ALLOWED),
        std::hint::black_box(ONLINE_TOPOLOGY_ACTIVATION_ALLOWED),
        std::hint::black_box(PRODUCTION_AUTHORITY),
        std::hint::black_box(EXTERNAL_EFFECTS_ALLOWED),
    ];
    assert_eq!(posture, [false; 4]);
}
