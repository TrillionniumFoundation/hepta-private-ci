use std::collections::BTreeSet;

use codex_hepta_types::Digest32;

use super::*;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn text_span() -> ModalitySpanRefV1 {
    let Ok(value) = ModalitySpanRefV1::try_new(
        1,
        ModalityKindV1::Text,
        digest("asset"),
        SpanRangeV1::ByteRange { start: 0, end: 12 },
        digest("preprocessor"),
        None,
        None,
        25_000,
        PrivacyClassV1::AgentPrivate,
        None,
    ) else {
        panic!("text span fixture must be valid");
    };
    value
}

fn memory_event(
    verification: MemoryVerificationStateV1,
    lifecycle: MemoryLifecycleV1,
) -> Result<MemoryEventV1, HnmfContractError> {
    let scope = MemoryScopeV1::agent_private("agent:test")?;
    let interval = TimeIntervalV1::try_new(1_000, None)?;
    let retention = RetentionPolicyV1::try_new(digest("retention"), None, false)?;
    let provenance = ProvenanceRefV1::try_new("source:test", 1, digest("source"), 1_000)?;
    MemoryEventV1::try_new(
        1,
        7,
        scope,
        interval,
        vec![text_span()],
        Vec::new(),
        BTreeSet::from(["door".to_string(), "red".to_string()]),
        vec![provenance],
        verification,
        retention,
        digest("objective"),
        digest("ndu"),
        Some(500_000),
        lifecycle,
    )
}

#[test]
fn canonical_json_round_trip_is_byte_stable() {
    let span = text_span();
    let Ok(bytes) = span.to_canonical_json() else {
        panic!("valid span must encode");
    };
    let Ok(decoded) = ModalitySpanRefV1::from_canonical_json(&bytes) else {
        panic!("canonical span must decode");
    };
    assert_eq!(decoded, span);
    assert_eq!(decoded.to_canonical_json(), Ok(bytes.clone()));
    assert_eq!(
        bytes.as_slice(),
        include_bytes!("../../tests/data/modality_span_v1.canonical.json")
    );
}

#[test]
fn canonical_json_rejects_unknown_envelope_fields_and_whitespace() {
    let span = text_span();
    let Ok(bytes) = span.to_canonical_json() else {
        panic!("valid span must encode");
    };
    let Ok(text) = String::from_utf8(bytes.clone()) else {
        panic!("canonical JSON must be UTF-8");
    };
    let unknown = text.replacen('{', "{\"unknown\":1,", 1);
    assert!(matches!(
        ModalitySpanRefV1::from_canonical_json(unknown.as_bytes()),
        Err(HnmfContractError::Wire(_))
    ));

    let mut noncanonical = bytes;
    noncanonical.push(b'\n');
    assert_eq!(
        ModalitySpanRefV1::from_canonical_json(&noncanonical),
        Err(HnmfContractError::NonCanonicalJson)
    );
}

#[test]
fn canonical_json_rejects_unknown_nested_variant_fields() {
    let span = text_span();
    let Ok(bytes) = span.to_canonical_json() else {
        panic!("valid span must encode");
    };
    let Ok(text) = String::from_utf8(bytes) else {
        panic!("canonical JSON must be UTF-8");
    };
    let invalid = text.replace(
        "\"kind\":\"byte_range\",",
        "\"kind\":\"byte_range\",\"unexpected\":1,",
    );
    assert!(matches!(
        ModalitySpanRefV1::from_canonical_json(invalid.as_bytes()),
        Err(HnmfContractError::Wire(_))
    ));
}

#[test]
fn canonical_json_rejects_unknown_enum_values() {
    let span = text_span();
    let Ok(bytes) = span.to_canonical_json() else {
        panic!("valid span must encode");
    };
    let Ok(text) = String::from_utf8(bytes) else {
        panic!("canonical JSON must be UTF-8");
    };
    let invalid = text.replace("\"modality\":\"text\"", "\"modality\":\"future_modality\"");
    assert!(matches!(
        ModalitySpanRefV1::from_canonical_json(invalid.as_bytes()),
        Err(HnmfContractError::Wire(_))
    ));
}

#[test]
fn revoked_events_cannot_remain_active() {
    assert_eq!(
        memory_event(
            MemoryVerificationStateV1::Revoked,
            MemoryLifecycleV1::Active
        ),
        Err(HnmfContractError::Conflict(
            "revoked event must be tombstoned"
        ))
    );
}

#[test]
fn event_wire_round_trip_binds_spec_only_fields() {
    let Ok(event) = memory_event(
        MemoryVerificationStateV1::Verified,
        MemoryLifecycleV1::Active,
    ) else {
        panic!("event fixture must be valid");
    };
    let Ok(bytes) = event.to_canonical_json() else {
        panic!("event must encode");
    };
    let Ok(text) = String::from_utf8(bytes.clone()) else {
        panic!("canonical JSON must be UTF-8");
    };
    assert!(text.contains("\"verification\":\"verified\""));
    assert!(text.contains("\"retentionPolicy\""));
    assert_eq!(MemoryEventV1::from_canonical_json(&bytes), Ok(event));
}

#[test]
fn topology_and_plasticity_constructors_enforce_next_snapshot_only() {
    let proposal = TopologyOperationV1::SplitNode {
        node_id: 3,
        left_label: "door-red".to_string(),
        right_label: "door-blue".to_string(),
    };
    assert!(TopologyProposalV1::try_new(7, 8, proposal).is_ok());

    let weight = WeightProposalV1::try_new(
        1,
        2,
        SynapseRelationV1::Associative,
        10_000,
        15_000,
        5_000,
    );
    let Ok(weight) = weight else {
        panic!("weight fixture must be valid");
    };
    assert!(
        PlasticityBatchV1::try_new(7, 8, digest("outcome"), vec![weight], Vec::new()).is_ok()
    );
    assert!(
        PlasticityBatchV1::try_new(7, 9, digest("outcome"), Vec::new(), Vec::new()).is_err()
    );
}

#[test]
fn all_canonical_hnmf_protocols_have_distinct_schema_ids() {
    let ids = BTreeSet::from([
        ModalitySpanRefV1::SCHEMA_ID,
        CrossModalBindingV1::SCHEMA_ID,
        MemoryEventV1::SCHEMA_ID,
        EngramNodeV1::SCHEMA_ID,
        SynapseV1::SCHEMA_ID,
        MemoryCueV1::SCHEMA_ID,
        RecallPacketV1::SCHEMA_ID,
        OutcomeSignalV1::SCHEMA_ID,
        ReplaySelectionReceiptV1::SCHEMA_ID,
        PlasticityBatchV1::SCHEMA_ID,
        TopologyProposalV1::SCHEMA_ID,
        ForgetPropagationReceiptV1::SCHEMA_ID,
    ]);
    assert_eq!(ids.len(), 12);
}


#[test]
fn canonical_json_rejects_missing_required_payload_fields() {
    let span = text_span();
    let Ok(bytes) = span.to_canonical_json() else {
        panic!("valid span must encode");
    };
    let Ok(text) = String::from_utf8(bytes) else {
        panic!("canonical JSON must be UTF-8");
    };
    let missing = text.replace("\"spanId\":1,", "");
    assert_ne!(missing, text);
    assert!(matches!(
        ModalitySpanRefV1::from_canonical_json(missing.as_bytes()),
        Err(HnmfContractError::Wire(_))
    ));
}

#[test]
fn canonical_json_rejects_reordered_envelope_keys() {
    let span = text_span();
    let Ok(bytes) = span.to_canonical_json() else {
        panic!("valid span must encode");
    };
    let Ok(text) = String::from_utf8(bytes) else {
        panic!("canonical JSON must be UTF-8");
    };
    let prefix =
        "{\"schema\":\"hepta.hnmf.modality-span-ref.v1\",\"schemaVersion\":1,\"payload\":";
    let reordered_prefix =
        "{\"schemaVersion\":1,\"schema\":\"hepta.hnmf.modality-span-ref.v1\",\"payload\":";
    assert!(text.starts_with(prefix));
    let reordered = text.replacen(prefix, reordered_prefix, 1);
    assert_eq!(
        ModalitySpanRefV1::from_canonical_json(reordered.as_bytes()),
        Err(HnmfContractError::NonCanonicalJson)
    );
}

#[test]
fn canonical_json_and_collection_bounds_fail_closed() {
    let oversized_wire = vec![
        b' ';
        <ModalitySpanRefV1 as CanonicalJsonV1>::MAX_ENCODED_BYTES + 1
    ];
    assert_eq!(
        ModalitySpanRefV1::from_canonical_json(&oversized_wire),
        Err(HnmfContractError::BoundExceeded("encoded bytes"))
    );

    let span_ids = (1..=u64::try_from(MAX_BINDING_SPANS + 1).unwrap_or(u64::MAX))
        .collect::<BTreeSet<_>>();
    assert_eq!(
        CrossModalBindingV1::try_new(
            1,
            1,
            span_ids,
            AlignmentKindV1::SameObservation,
            500_000,
            digest("producer"),
        ),
        Err(HnmfContractError::BoundExceeded("binding span count"))
    );

    assert_eq!(
        ResourceBudgetV1::try_new(
            MAX_CANDIDATE_EVENTS + 1,
            MAX_ENGRAM_NODES,
            MAX_ENGRAM_SYNAPSES,
            MAX_RECURRENT_STEPS,
            MAX_RECALL_EVENTS as u16,
            MAX_ACTIVATION_PATHS as u16,
        ),
        Err(HnmfContractError::BoundExceeded("recall resource budget"))
    );
}

#[test]
fn canonical_set_order_is_insertion_independent() {
    let left = CrossModalBindingV1::try_new(
        1,
        1,
        BTreeSet::from([2, 1]),
        AlignmentKindV1::SameObservation,
        500_000,
        digest("producer"),
    );
    let right = CrossModalBindingV1::try_new(
        1,
        1,
        [1, 2].into_iter().collect(),
        AlignmentKindV1::SameObservation,
        500_000,
        digest("producer"),
    );
    let (Ok(left), Ok(right)) = (left, right) else {
        panic!("binding fixtures must be valid");
    };
    assert_eq!(left.to_canonical_json(), right.to_canonical_json());
}
