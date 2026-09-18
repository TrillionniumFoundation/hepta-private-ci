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
    assert_eq!(decoded.to_canonical_json(), Ok(bytes));
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
