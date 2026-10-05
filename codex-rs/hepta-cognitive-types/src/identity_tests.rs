// Included by contract_tests.rs to reuse the actual canonical V1 fixtures.
// Every mutant preserves canonical full-value ordering and unrelated invariants.

#[test]
fn provenance_identity_rejects_digest_and_observation_conflicts() {
    for change_digest in [true, false] {
        let mut value = event();
        value.validate().expect("valid baseline event");
        let mut duplicate = value.provenance[0].clone();
        if change_digest {
            duplicate.source_sha256 = digest('d');
        } else {
            duplicate.observed_at_unix_ms += 1;
        }
        value.provenance.push(duplicate);
        value.provenance.sort();
        assert_eq!(
            value.validate(),
            Err(HnmfContractError::DuplicateIdentity(
                "provenance.sourceId/sourceRevision"
            ))
        );
        assert!(encode_wire_v1(&value).is_err());
    }
}

#[test]
fn recall_identity_rejects_conflicting_event_digest() {
    let mut packet = recall_packet();
    packet.validate().expect("valid baseline recall");
    let mut duplicate = packet.selected_events[0].clone();
    duplicate.event_digest = digest('9');
    packet.selected_events.push(duplicate);
    packet.selected_events.sort();
    packet.resource_receipt.candidate_event_count = 2;
    assert_eq!(
        packet.validate(),
        Err(HnmfContractError::DuplicateIdentity("selectedEvents"))
    );
    assert!(encode_wire_v1(&packet).is_err());
}

#[test]
fn recall_identity_rejects_conflicting_node_population_and_activation() {
    for change_population in [true, false] {
        let mut packet = recall_packet();
        let mut duplicate = packet.active_nodes[0].clone();
        if change_population {
            duplicate.population = EngramPopulationV1::MetaMemory;
        } else {
            duplicate.activation_ppm += 1;
        }
        packet.active_nodes.push(duplicate);
        packet.active_nodes.sort();
        packet.resource_receipt.active_node_count = 2;
        packet.resource_receipt.node_count = 2;
        assert_eq!(
            packet.validate(),
            Err(HnmfContractError::DuplicateIdentity("activeNodes"))
        );
        assert!(encode_wire_v1(&packet).is_err());
    }
}

#[test]
fn recall_identity_rejects_conflicting_path_contributions() {
    let mut packet = recall_packet();
    packet.activation_paths = vec![ActivationPathV1 {
        source_node_id: id("node:1"),
        target_node_id: id("node:2"),
        relation: SynapseRelationV1::Associative,
        contribution_ppm: 1,
    }];
    packet.resource_receipt.node_count = 2;
    packet.resource_receipt.synapse_count = 1;
    packet.validate().expect("valid path baseline");
    let mut duplicate = packet.activation_paths[0].clone();
    duplicate.contribution_ppm = 2;
    packet.activation_paths.push(duplicate);
    assert_eq!(
        packet.validate(),
        Err(HnmfContractError::DuplicateIdentity("activationPaths"))
    );
}

#[test]
fn plasticity_identity_rejects_conflicting_weight_and_threshold_targets() {
    let mut weights = plasticity();
    weights.validate().expect("valid baseline plasticity");
    let mut duplicate = weights.weight_proposals[0].clone();
    duplicate.new_weight_q16 = 1_024;
    duplicate.delta_ppm = 15_625;
    weights.weight_proposals.push(duplicate);
    weights.weight_proposals.sort();
    assert_eq!(
        weights.validate(),
        Err(HnmfContractError::DuplicateIdentity("weightProposals"))
    );
    let mut thresholds = plasticity();
    let mut duplicate = thresholds.threshold_proposals[0].clone();
    duplicate.new_threshold_q16 = -1_024;
    duplicate.delta_ppm = -15_625;
    thresholds.threshold_proposals.push(duplicate);
    thresholds.threshold_proposals.sort();
    assert_eq!(
        thresholds.validate(),
        Err(HnmfContractError::DuplicateIdentity("thresholdProposals"))
    );
}

#[test]
fn topology_identity_rejects_conflicting_label_and_population() {
    for change_label in [true, false] {
        let mut proposal = topology();
        proposal.validate().expect("valid baseline topology");
        let mut duplicate = proposal.typed_nodes_edges.nodes[0].clone();
        if change_label {
            duplicate.label = "other-label".to_string();
        } else {
            duplicate.population = EngramPopulationV1::SemanticConcept;
        }
        proposal.typed_nodes_edges.nodes.push(duplicate);
        proposal.typed_nodes_edges.nodes.sort();
        proposal.resource_delta.node_delta = 2;
        proposal.resource_delta.resident_bytes_upper_bound_delta = 8_192;
        assert_eq!(
            proposal.validate(),
            Err(HnmfContractError::DuplicateIdentity("topologyNodes"))
        );
        assert!(encode_wire_v1(&proposal).is_err());
    }
}

proptest::proptest! {
    #[test]
    fn real_recall_identity_conflict_is_rejected_for_every_activation(value in 0u32..1_000_000) {
        let mut packet = recall_packet();
        packet.active_nodes[0].activation_ppm = value;
        packet.validate().expect("valid generated baseline");
        let mut duplicate = packet.active_nodes[0].clone();
        duplicate.activation_ppm = value + 1;
        packet.active_nodes.push(duplicate);
        packet.resource_receipt.active_node_count = 2;
        packet.resource_receipt.node_count = 2;
        proptest::prop_assert_eq!(packet.validate(), Err(HnmfContractError::DuplicateIdentity("activeNodes")));
    }

    #[test]
    fn real_plasticity_identity_conflict_is_rejected_for_valid_q16_deltas(value in 1i32..2_000) {
        let mut batch = plasticity();
        batch.weight_proposals[0].new_weight_q16 = value;
        batch.weight_proposals[0].delta_ppm = ((i64::from(value) * 1_000_000) / 65_536) as i32;
        batch.validate().expect("valid generated baseline");
        let mut duplicate = batch.weight_proposals[0].clone();
        duplicate.new_weight_q16 = value + 1;
        duplicate.delta_ppm = ((i64::from(value + 1) * 1_000_000) / 65_536) as i32;
        batch.weight_proposals.push(duplicate);
        proptest::prop_assert_eq!(batch.validate(), Err(HnmfContractError::DuplicateIdentity("weightProposals")));
    }
}
