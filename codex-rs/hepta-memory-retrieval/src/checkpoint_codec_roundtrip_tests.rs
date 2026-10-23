//! Exercise codecs with the actual MemoryCell tick fixture, not copied receipts.

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::EngramPopulationV1;
use crate::EngramSnapshotV1;
use crate::SynapseRelationV1;
use crate::SynapseV1;
use crate::decode_engram_checkpoint_v1;
use crate::decode_recall_checkpoint_v1;
use crate::encode_engram_checkpoint_v1;
use crate::encode_recall_checkpoint_v1;

#[test]
fn restores_complete_selected_and_abstained_tick_receipts() {
    for with_candidate in [true, false] {
        let fixture = super::shadow_fixture(with_candidate);
        let first = super::execute(&fixture).unwrap();
        let state = encode_engram_checkpoint_v1(&fixture.snapshot).unwrap();
        let recall = encode_recall_checkpoint_v1(&first.recall).unwrap();
        let recovered = decode_engram_checkpoint_v1(&state, Digest32::of_bytes(&state)).unwrap();
        let receipt = decode_recall_checkpoint_v1(&recall, Digest32::of_bytes(&recall)).unwrap();
        assert_eq!(recovered, fixture.snapshot);
        assert_eq!(receipt, first.recall);
        assert_eq!(encode_engram_checkpoint_v1(&recovered).unwrap(), state);
        assert_eq!(encode_recall_checkpoint_v1(&receipt).unwrap(), recall);
        assert!(decode_recall_checkpoint_v1(&state, Digest32::of_bytes(&state)).is_err());
        assert!(decode_engram_checkpoint_v1(&recall, Digest32::of_bytes(&recall)).is_err());
        let mut restored_fixture = fixture;
        restored_fixture.snapshot = recovered;
        assert_eq!(super::execute(&restored_fixture).unwrap(), first);
    }
}

#[test]
fn complete_graph_restores_populations_support_and_negative_synapses() {
    let fixture = super::shadow_fixture(true);
    let populations = [
        EngramPopulationV1::SensoryTrace,
        EngramPopulationV1::EpisodicBinding,
        EngramPopulationV1::SemanticConcept,
        EngramPopulationV1::ProceduralSkill,
        EngramPopulationV1::PredictiveWorld,
        EngramPopulationV1::UtilitySalience,
        EngramPopulationV1::MetaMemory,
    ];
    let relations = [
        SynapseRelationV1::Associative,
        SynapseRelationV1::Temporal,
        SynapseRelationV1::Causal,
        SynapseRelationV1::Procedural,
        SynapseRelationV1::Predictive,
        SynapseRelationV1::Supports,
        SynapseRelationV1::Inhibitory,
        SynapseRelationV1::Contradicts,
    ];
    let nodes: Vec<_> = populations
        .into_iter()
        .enumerate()
        .map(|(index, population)| {
            let mut node = fixture.snapshot.nodes[0].clone();
            node.node_id = StableId::new(format!("node:population-{index}")).unwrap();
            node.population = population;
            node
        })
        .collect();
    let synapses = relations
        .into_iter()
        .enumerate()
        .map(|(index, relation)| SynapseV1 {
            source_node_id: nodes[0].node_id.clone(),
            target_node_id: nodes[1].node_id.clone(),
            relation,
            weight: FixedQ32::from_raw(-FixedQ32::ONE.raw() / 2),
            support_digest: Digest32::of_bytes(format!("support-{index}").as_bytes()),
            generation_vector_digest: fixture.snapshot.generation_vector_digest,
        })
        .collect();
    let graph = EngramSnapshotV1::new(
        fixture.snapshot.generation_vector_digest,
        fixture.snapshot.engram_generation_digest,
        nodes,
        synapses,
    )
    .unwrap();
    let bytes = encode_engram_checkpoint_v1(&graph).unwrap();
    assert_eq!(
        decode_engram_checkpoint_v1(&bytes, Digest32::of_bytes(&bytes)).unwrap(),
        graph
    );
}
