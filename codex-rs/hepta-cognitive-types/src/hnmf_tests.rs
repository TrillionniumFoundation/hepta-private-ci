use std::collections::BTreeSet;
use std::fmt::Debug;

trait TestResultExt<T> {
    fn must(self) -> T;
}

impl<T, E: Debug> TestResultExt<T> for Result<T, E> {
    fn must(self) -> T {
        match self {
            Ok(value) => value,
            Err(error) => panic!("test fixture construction failed: {error:?}"),
        }
    }
}


use codex_hepta_types::Digest32;

use super::*;

fn digest(label: &[u8]) -> CanonicalDigestV1 {
    CanonicalDigestV1::new(Digest32::of_bytes(label)).must()
}

fn text_span(privacy_class: PrivacyClassV1) -> ModalitySpanRefV1 {
    ModalitySpanRefV1::try_new(
        1,
        ModalityKindV1::Text,
        digest(b"asset"),
        SpanRangeV1::ByteRange { start: 0, end: 4 },
        digest(b"preprocessor"),
        Some(digest(b"feature")),
        None,
        10_000,
        privacy_class,
        None,
    )
    .must()
}

fn valid_event() -> MemoryEventV1 {
    MemoryEventV1::try_new(
        7,
        7,
        MemoryScopeV1::try_agent_private("agent-a").must(),
        TimeIntervalV1::try_new(1, None).must(),
        vec![text_span(PrivacyClassV1::AgentPrivate)],
        Vec::new(),
        BTreeSet::from(["door".to_owned()]),
        vec![
            ProvenanceRefV1::try_new("source-7", 1, digest(b"source"), 1).must(),
        ],
        MemoryVerificationStateV1::Verified,
        RetentionPolicyV1::try_new(digest(b"retention"), None).must(),
        digest(b"objective"),
        digest(b"ndu"),
        Some(500_000),
        MemoryLifecycleV1::Active,
    )
    .must()
}

#[test]
fn canonical_event_is_constructed_valid() {
    let event = valid_event();
    assert_eq!(event.event_id(), 7);
    assert_eq!(event.episode_id(), 7);
    event.validate().must();
}

#[test]
fn invalid_span_modality_never_constructs() {
    let result = ModalitySpanRefV1::try_new(
        1,
        ModalityKindV1::Image,
        digest(b"asset"),
        SpanRangeV1::ByteRange { start: 0, end: 4 },
        digest(b"preprocessor"),
        None,
        None,
        0,
        PrivacyClassV1::AgentPrivate,
        None,
    );
    assert!(result.is_err());
}

#[test]
fn event_rejects_scope_span_privacy_drift() {
    let result = MemoryEventV1::try_new(
        7,
        7,
        MemoryScopeV1::try_agent_private("agent-a").must(),
        TimeIntervalV1::try_new(1, None).must(),
        vec![text_span(PrivacyClassV1::WorkspacePrivate)],
        Vec::new(),
        BTreeSet::from(["door".to_owned()]),
        vec![
            ProvenanceRefV1::try_new("source-7", 1, digest(b"source"), 1).must(),
        ],
        MemoryVerificationStateV1::Verified,
        RetentionPolicyV1::try_new(digest(b"retention"), None).must(),
        digest(b"objective"),
        digest(b"ndu"),
        None,
        MemoryLifecycleV1::Active,
    );
    assert_eq!(
        result,
        Err(ContractErrorV1::Conflict(
            "span privacy class does not match event scope"
        ))
    );
}

#[test]
fn cross_modal_binding_requires_distinct_modalities() {
    let binding = CrossModalBindingV1::try_new(
        1,
        7,
        BTreeSet::from([1, 2]),
        AlignmentKindV1::SameObservation,
        900_000,
        digest(b"binding-producer"),
    )
    .must();
    let second_text = ModalitySpanRefV1::try_new(
        2,
        ModalityKindV1::Text,
        digest(b"asset-2"),
        SpanRangeV1::ByteRange { start: 4, end: 8 },
        digest(b"preprocessor-2"),
        None,
        None,
        10_000,
        PrivacyClassV1::AgentPrivate,
        None,
    )
    .must();
    let result = MemoryEventV1::try_new(
        7,
        7,
        MemoryScopeV1::try_agent_private("agent-a").must(),
        TimeIntervalV1::try_new(1, None).must(),
        vec![text_span(PrivacyClassV1::AgentPrivate), second_text],
        vec![binding],
        BTreeSet::from(["door".to_owned()]),
        vec![
            ProvenanceRefV1::try_new("source-7", 1, digest(b"source"), 1).must(),
        ],
        MemoryVerificationStateV1::Verified,
        RetentionPolicyV1::try_new(digest(b"retention"), None).must(),
        digest(b"objective"),
        digest(b"ndu"),
        None,
        MemoryLifecycleV1::Active,
    );
    assert!(result.is_err());
}

#[test]
fn canonical_json_round_trip_is_byte_stable() {
    let event = valid_event();
    let encoded = canonical_json_bytes(&event).must();
    let decoded = decode_canonical_json::<MemoryEventV1>(&encoded).must();
    assert_eq!(decoded, event);
    assert_eq!(canonical_json_bytes(&decoded).must(), encoded);
    assert_eq!(
        canonical_json_digest(&decoded).must(),
        Digest32::of_bytes(&encoded)
    );
}

#[test]
fn canonical_json_denies_unknown_fields_and_noncanonical_whitespace() {
    let event = valid_event();
    let encoded = canonical_json_bytes(&event).must();

    let mut unknown = String::from_utf8(encoded.clone()).must();
    unknown.insert_str(1, ""unexpected":true,");
    assert!(decode_canonical_json::<MemoryEventV1>(unknown.as_bytes()).is_err());

    let mut spaced = encoded;
    spaced.push(b' ');
    assert!(matches!(
        decode_canonical_json::<MemoryEventV1>(&spaced),
        Err(CanonicalWireErrorV1::NonCanonicalEncoding)
    ));
}


#[test]
fn canonical_json_golden_vectors_are_stable() {
    let outcome = OutcomeSignalV1::try_new(
        1,
        -7,
        11,
        13,
        17,
        19,
        digest(b"observer"),
    )
    .must();
    let outcome_bytes =
        include_bytes!("../testdata/hnmf-wire-v1/outcome_signal_v1.json").as_slice();
    assert_eq!(canonical_json_bytes(&outcome).must().as_slice(), outcome_bytes);
    assert_eq!(
        canonical_json_digest(&outcome).must().to_string(),
        "94f1ea223042fd0fd5ab8b1b5294dabb71813aca7735674aa4145d180ff8306d"
    );

    let cue = MemoryCueV1::try_new(
        7,
        digest(b"objective"),
        digest(b"ndu"),
        BTreeSet::from([ModalityKindV1::Text]),
        BTreeSet::from(["door".to_owned()]),
        BTreeSet::new(),
        1,
        ResourceBudgetV1::hnmf_default(),
    )
    .must();
    let cue_bytes = include_bytes!("../testdata/hnmf-wire-v1/memory_cue_v1.json").as_slice();
    assert_eq!(canonical_json_bytes(&cue).must().as_slice(), cue_bytes);
    assert_eq!(
        canonical_json_digest(&cue).must().to_string(),
        "3416b1ec9cec8809423b33f4d8b5bc9758ad7a2c46b2f8f560d93e35a1b13087"
    );
}

#[test]
fn topology_and_plasticity_cannot_self_activate() {
    let topology = TopologyProposalV1::try_new(
        7,
        8,
        TopologyOperationV1::AddNode {
            label: "new-node".to_owned(),
            population: EngramPopulationV1::SemanticConcept,
        },
        true,
        true,
        false,
        false,
    )
    .must();
    topology.validate().must();

    assert!(
        TopologyProposalV1::try_new(
            7,
            8,
            TopologyOperationV1::RetireNode {
                node_id: 1,
                reason: "retire".to_owned(),
            },
            true,
            true,
            true,
            false,
        )
        .is_err()
    );

    assert!(
        PlasticityBatchV1::try_new(
            7,
            8,
            digest(b"outcome"),
            Vec::new(),
            Vec::new(),
            true,
            true,
        )
        .is_err()
    );
}
