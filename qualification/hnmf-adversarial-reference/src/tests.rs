use super::*;
use std::collections::BTreeSet;

fn set<T: Ord>(values: impl IntoIterator<Item = T>) -> BTreeSet<T> {
    values.into_iter().collect()
}

fn digest(character: char) -> String {
    std::iter::repeat_n(character, 64).collect()
}

fn event(
    id: EventId,
    episode_id: u64,
    modalities: &[hnmf_reference::ModalityKind],
    keys: &[&str],
) -> MemoryEvent {
    MemoryEvent {
        id,
        episode_id,
        modalities: set(modalities.iter().copied()),
        semantic_keys: set(keys.iter().map(|value| (*value).to_string())),
        source_sha256: set([digest(char::from_digit(id as u32 % 6 + 10, 16).unwrap())]),
        privacy: hnmf_reference::PrivacyClass::AgentPrivate,
        valid_from_unix_ms: 1,
        valid_to_unix_ms: None,
        utility_ppm: 100_000,
        risk_ppm: 10_000,
        tombstoned: false,
    }
}

fn node(
    id: NodeId,
    population: EngramPopulation,
    modalities: &[hnmf_reference::ModalityKind],
    keys: &[&str],
    support_events: &[EventId],
) -> EngramNode {
    EngramNode {
        id,
        population,
        modalities: set(modalities.iter().copied()),
        cue_keys: set(keys.iter().map(|value| (*value).to_string())),
        support_events: set(support_events.iter().copied()),
        threshold_ppm: 10_000,
        target_activity_ppm: 100_000,
        confidence_ppm: 900_000,
        retired: false,
    }
}

fn synapse(
    source: NodeId,
    target: NodeId,
    relation: SynapseRelation,
    support_events: &[EventId],
) -> Synapse {
    Synapse {
        source,
        target,
        relation,
        weight_ppm: 900_000,
        eligibility_ppm: 0,
        support_events: set(support_events.iter().copied()),
        retired: false,
    }
}

fn cue(keys: &[&str]) -> MemoryCue {
    MemoryCue {
        modalities: set([hnmf_reference::ModalityKind::Text]),
        semantic_keys: set(keys.iter().map(|value| (*value).to_string())),
        seed_nodes: BTreeSet::new(),
        now_unix_ms: 10,
    }
}

fn fabric() -> HardenedFabric {
    let mut fabric =
        HardenedFabric::new(7, FabricConfig::default(), HardeningConfig::default()).unwrap();
    fabric
        .insert_event(event(
            1,
            1,
            &[hnmf_reference::ModalityKind::Text],
            &["door"],
        ))
        .unwrap();
    fabric
        .insert_event(event(
            2,
            2,
            &[hnmf_reference::ModalityKind::Audio],
            &["alarm"],
        ))
        .unwrap();
    fabric
        .insert_node(node(
            1,
            EngramPopulation::SensoryTrace,
            &[hnmf_reference::ModalityKind::Text],
            &["door"],
            &[1],
        ))
        .unwrap();
    fabric
        .insert_node(node(
            2,
            EngramPopulation::EpisodicBinding,
            &[hnmf_reference::ModalityKind::Audio],
            &["alarm"],
            &[2],
        ))
        .unwrap();
    fabric
        .insert_synapse(synapse(1, 2, SynapseRelation::Associative, &[1, 2]))
        .unwrap();
    fabric
}

#[test]
fn cross_event_association_completes_different_event() {
    let packet = fabric().recall(&cue(&["door"])).unwrap();
    assert!(packet.packet.selected_events.contains(&1));
    assert!(packet.packet.selected_events.contains(&2));
    assert!(packet.expanded_node_ids.contains(&2));
}

#[test]
fn forged_recall_packet_cannot_drive_plasticity() {
    let fabric = fabric();
    let mut packet = fabric.recall(&cue(&["door"])).unwrap();
    packet.packet.active_nodes[0].activation_ppm -= 1;
    assert_eq!(
        fabric.propose_plasticity(
            &packet,
            OutcomeSignal {
                utility_delta_ppm: 100_000,
                prediction_error_ppm: 100_000,
                novelty_ppm: 100_000,
                risk_ppm: 0,
                ood_ppm: 0,
            },
        ),
        Err(HardeningError::Conflict(
            "recall packet does not match deterministic current snapshot"
        ))
    );
}

#[test]
fn forged_plasticity_batch_cannot_create_snapshot() {
    let fabric = fabric();
    let packet = fabric.recall(&cue(&["door"])).unwrap();
    let mut candidate = fabric
        .propose_plasticity(
            &packet,
            OutcomeSignal {
                utility_delta_ppm: 400_000,
                prediction_error_ppm: 500_000,
                novelty_ppm: 100_000,
                risk_ppm: 0,
                ood_ppm: 0,
            },
        )
        .unwrap();
    candidate.batch.modulator_ppm -= 1;
    assert_eq!(
        fabric.apply_plasticity(&candidate),
        Err(HardeningError::Conflict(
            "plasticity batch does not match deterministic source evidence"
        ))
    );
}

#[test]
fn exact_plasticity_creates_next_generation_only() {
    let fabric = fabric();
    let packet = fabric.recall(&cue(&["door"])).unwrap();
    let candidate = fabric
        .propose_plasticity(
            &packet,
            OutcomeSignal {
                utility_delta_ppm: 400_000,
                prediction_error_ppm: 500_000,
                novelty_ppm: 100_000,
                risk_ppm: 0,
                ood_ppm: 0,
            },
        )
        .unwrap();
    let next = fabric.apply_plasticity(&candidate).unwrap();
    assert_eq!(fabric.generation(), 7);
    assert_eq!(next.generation(), 8);
    assert!(candidate.current_snapshot_immutable);
    assert!(!candidate.production_activation_allowed);
}

#[test]
fn forget_requires_exact_support_closure() {
    let fabric = fabric();
    let mut candidate = fabric.propose_forget(1).unwrap();
    candidate.batch.affected_nodes.clear();
    assert_eq!(
        fabric.apply_forget(&candidate),
        Err(HardeningError::Conflict(
            "forget batch does not match exact support closure"
        ))
    );
}

#[test]
fn forget_prevents_cross_event_resurrection() {
    let fabric = fabric();
    let candidate = fabric.propose_forget(2).unwrap();
    let next = fabric.apply_forget(&candidate).unwrap();
    assert!(next.event(2).unwrap().tombstoned);
    let packet = next.recall(&cue(&["door"])).unwrap();
    assert!(!packet.packet.selected_events.contains(&2));
}

#[test]
fn replay_rejects_duplicate_event_ids() {
    let candidate = ReplayCandidate {
        event_id: 1,
        source_bucket: 1,
        expected_utility_gain_ppm: 900_000,
        prediction_error_ppm: 800_000,
        novelty_ppm: 700_000,
        rarity_ppm: 600_000,
        forgetting_risk_ppm: 500_000,
        coverage_need_ppm: 400_000,
        privacy_allowed: true,
    };
    assert_eq!(
        select_replay_hardened(&[candidate.clone(), candidate], 2, 2),
        Err(HardeningError::Conflict(
            "replay event ids must be unique and non-zero"
        ))
    );
}

#[test]
fn storage_and_query_candidate_bounds_are_distinct() {
    let hardening = HardeningConfig {
        maximum_stored_events: 2,
        maximum_candidate_events: 1,
        ..HardeningConfig::default()
    };
    let mut fabric = HardenedFabric::new(1, FabricConfig::default(), hardening).unwrap();
    fabric
        .insert_event(event(
            1,
            1,
            &[hnmf_reference::ModalityKind::Text],
            &["alpha"],
        ))
        .unwrap();
    fabric
        .insert_event(event(
            2,
            2,
            &[hnmf_reference::ModalityKind::Text],
            &["beta"],
        ))
        .unwrap();
    assert_eq!(
        fabric.insert_event(event(
            3,
            3,
            &[hnmf_reference::ModalityKind::Text],
            &["gamma"],
        )),
        Err(HardeningError::BoundExceeded("stored events"))
    );
}

#[test]
fn generation_overflow_fails_closed() {
    let mut fabric = HardenedFabric::new(
        u64::MAX,
        FabricConfig::default(),
        HardeningConfig::default(),
    )
    .unwrap();
    fabric
        .insert_event(event(
            1,
            1,
            &[hnmf_reference::ModalityKind::Text],
            &["alpha"],
        ))
        .unwrap();
    assert_eq!(
        fabric.propose_forget(1),
        Err(HardeningError::ArithmeticOverflow)
    );
}

#[test]
fn activation_paths_reference_only_final_active_nodes() {
    let packet = fabric().recall(&cue(&["door"])).unwrap();
    let active = packet
        .packet
        .active_nodes
        .iter()
        .map(|node| node.node_id)
        .collect::<BTreeSet<_>>();
    assert!(
        packet
            .packet
            .activation_paths
            .iter()
            .all(|path| { active.contains(&path.source) && active.contains(&path.target) })
    );
}

#[test]
fn insertion_order_is_deterministic() {
    let first = fabric();
    let mut second =
        HardenedFabric::new(7, FabricConfig::default(), HardeningConfig::default()).unwrap();
    second
        .insert_event(event(
            2,
            2,
            &[hnmf_reference::ModalityKind::Audio],
            &["alarm"],
        ))
        .unwrap();
    second
        .insert_event(event(
            1,
            1,
            &[hnmf_reference::ModalityKind::Text],
            &["door"],
        ))
        .unwrap();
    second
        .insert_node(node(
            2,
            EngramPopulation::EpisodicBinding,
            &[hnmf_reference::ModalityKind::Audio],
            &["alarm"],
            &[2],
        ))
        .unwrap();
    second
        .insert_node(node(
            1,
            EngramPopulation::SensoryTrace,
            &[hnmf_reference::ModalityKind::Text],
            &["door"],
            &[1],
        ))
        .unwrap();
    second
        .insert_synapse(synapse(1, 2, SynapseRelation::Associative, &[1, 2]))
        .unwrap();
    assert_eq!(
        first.recall(&cue(&["door"])).unwrap(),
        second.recall(&cue(&["door"])).unwrap()
    );
}

#[test]
fn authority_posture_is_compile_time_false() {
    const {
        assert!(!CURRENT_RUN_MUTATION_ALLOWED);
        assert!(!ONLINE_TOPOLOGY_ACTIVATION_ALLOWED);
        assert!(!PRODUCTION_AUTHORITY);
        assert!(!EXTERNAL_EFFECTS_ALLOWED);
    };
}
