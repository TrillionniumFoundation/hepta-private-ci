use super::CanonicalConsumerBindingError;
use super::CanonicalContractFailureV1;
use super::ContractErrorCodeV1;
use crate::consumer::CanonicalConsumerV1;
use crate::consumer::CanonicalMigrationPostureV1;
use crate::consumer::bind_recall_packet_consumer_v1;
use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::HnmfContractError;
use crate::hnmf_learning::RecallPacketV1;
use crate::hnmf_learning::RecallResourceReceiptV1;
use crate::hnmf_learning::SelectedEventRefV1;
use crate::wire::CognitiveWireError;
use crate::wire::canonical_contract_digest_v1;
use codex_hepta_types::Digest32;

#[test]
fn typed_codec_refusals_keep_categories_fields_and_payload_free_messages() {
    let json_error = serde_json::from_str::<u32>("\"private-payload-marker\"")
        .expect_err("wrong JSON field type");
    let errors = [
        CognitiveWireError::Contract(HnmfContractError::DuplicateIdentity("selectedEvents")),
        CognitiveWireError::SchemaMismatch,
        CognitiveWireError::VersionMismatch(2),
        CognitiveWireError::ContractMismatch,
        CognitiveWireError::NonCanonicalInput,
        CognitiveWireError::PayloadLength {
            actual: 2,
            maximum: 1,
        },
        CognitiveWireError::Json(json_error),
    ];
    for error in errors {
        let expected = error.violation();
        let projected = CanonicalConsumerBindingError::CanonicalContractTyped(
            CanonicalContractFailureV1::from_wire(&error),
        );
        assert_eq!(projected.violation(), expected);
        assert!(!projected.to_string().contains("private-payload-marker"));
    }
}

#[test]
fn public_recall_constructor_retains_the_original_structured_rejection() {
    let digest = Digest32::of_bytes(b"fixture");
    let contract_digest = ContractDigestV1::from_digest(digest).expect("digest");
    let mut packet = RecallPacketV1 {
        cue_digest: contract_digest,
        event_snapshot_digest: contract_digest,
        engram_snapshot_digest: contract_digest,
        selected_events: vec![SelectedEventRefV1 {
            event_id: ContractIdV1::new("event:typed-error").expect("event id"),
            revision: 1,
            event_digest: contract_digest,
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
    };
    let bind = |value: &RecallPacketV1, consumer| {
        bind_recall_packet_consumer_v1(
            ContractIdV1::new("operation:typed-error").expect("operation id"),
            consumer,
            value,
            digest,
            digest,
            Some(digest),
            CanonicalMigrationPostureV1::CompatibilityBound,
        )
    };
    for consumer in [
        CanonicalConsumerV1::MemoryRetrieval,
        CanonicalConsumerV1::IntelligenceControl,
    ] {
        bind(&packet, consumer).expect("valid existing path");
        packet.selected_events[0].revision = 0;
        let expected = canonical_contract_digest_v1(&packet).expect_err("invalid revision");
        let error = bind(&packet, consumer).expect_err("invalid payload must reject");
        assert_eq!(error.violation(), expected.violation());
        assert_eq!(error.violation().code, ContractErrorCodeV1::ZeroValue);
        assert!(matches!(
            error,
            CanonicalConsumerBindingError::CanonicalContractTyped(_)
        ));
        packet.selected_events[0].revision = 1;
        bind(&packet, consumer).expect("a refusal cannot poison subsequent legitimate use");
    }
}
