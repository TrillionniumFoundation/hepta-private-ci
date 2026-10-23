use super::*;
use crate::consumer::CanonicalConsumerV1;
use crate::consumer::CanonicalMigrationPostureV1;
use crate::consumer::bind_recall_packet_consumer_v1;
use crate::contract::Validated;

#[test]
fn recall_rejects_more_activation_paths_than_reported_synapses() {
    let mut packet = recall_packet();
    packet.activation_paths.push(ActivationPathV1 {
        source_node_id: id("node:1"),
        target_node_id: id("node:2"),
        relation: SynapseRelationV1::Associative,
        contribution_ppm: 1,
    });
    packet.resource_receipt.node_count = 2;
    assert_eq!(
        packet.validate(),
        Err(HnmfContractError::Invalid(
            "recall resource receipt binding"
        ))
    );
    assert!(Validated::new(packet.clone()).is_err());
    assert!(encode_wire_v1(&packet).is_err());
    for consumer in [
        CanonicalConsumerV1::MemoryRetrieval,
        CanonicalConsumerV1::IntelligenceControl,
    ] {
        assert!(
            bind_recall_packet_consumer_v1(
                id("operation:underreported-recall"),
                consumer,
                &packet,
                digest('a').digest(),
                digest('b').digest(),
                Some(digest('c').digest()),
                CanonicalMigrationPostureV1::CompatibilityBound,
            )
            .is_err()
        );
    }
}

#[test]
fn recall_resource_node_count_covers_all_referenced_identities() {
    let mut packet = recall_packet();
    packet.resource_receipt.synapse_count = 1;
    packet.activation_paths.push(ActivationPathV1 {
        source_node_id: id("node:1"),
        target_node_id: id("node:2"),
        relation: SynapseRelationV1::Associative,
        contribution_ppm: 1,
    });
    assert_eq!(
        packet.validate(),
        Err(HnmfContractError::Invalid(
            "recall resource receipt binding"
        ))
    );
    packet.resource_receipt.node_count = 2;
    packet.validate().expect("both path endpoints covered");

    packet.contradictions.push(ContradictionV1 {
        left_node_id: id("node:1"),
        right_node_id: id("node:3"),
    });
    assert_eq!(
        packet.validate(),
        Err(HnmfContractError::Invalid(
            "recall resource receipt binding"
        ))
    );
    packet.resource_receipt.node_count = 3;
    packet.validate().expect("all distinct references covered");
    let wire = encode_wire_v1(&packet).expect("valid reference counts");
    assert_eq!(
        decode_wire_v1::<RecallPacketV1>(&wire).expect("roundtrip"),
        packet
    );
}
