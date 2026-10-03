//! Bounded graph projection decoder for signed retrieval context publications.

use codex_hepta_agent_components::memory_retrieval::EngramNodeV1;
use codex_hepta_agent_components::memory_retrieval::EngramPopulationV1;
use codex_hepta_agent_components::memory_retrieval::EngramSupportV1;
use codex_hepta_agent_components::memory_retrieval::SynapseRelationV1;
use codex_hepta_agent_components::memory_retrieval::SynapseV1;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::FixedQ32;
use codex_hepta_agent_components::types::ProbabilityQ32;
use codex_hepta_agent_components::types::Revision;
use serde::Deserialize;

use super::digest;
use super::id;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct EngramWire {
    generation_digest: String,
    nodes: Vec<NodeWire>,
    synapses: Vec<SynapseWire>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NodeWire {
    node_id: String,
    population: u8,
    support: Vec<SupportWire>,
    threshold_q32: i64,
    confidence_q32: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SupportWire {
    record_id: String,
    record_revision: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SynapseWire {
    source_node_id: String,
    target_node_id: String,
    relation: u8,
    weight_q32: i64,
    support_digest: String,
}

type Projection = (Digest32, Vec<EngramNodeV1>, Vec<SynapseV1>);

impl EngramWire {
    pub(super) fn decode(self, generation: Digest32) -> Result<Projection, String> {
        if self.nodes.len() > 4096 || self.synapses.len() > 32_768 {
            return Err("retrieval engram wire structural limit".to_string());
        }
        let nodes = self
            .nodes
            .into_iter()
            .map(|node| {
                if node.support.is_empty() || node.support.len() > 512 {
                    return Err("retrieval node support wire limit".to_string());
                }
                let population = match node.population {
                    0 => EngramPopulationV1::SensoryTrace,
                    1 => EngramPopulationV1::EpisodicBinding,
                    2 => EngramPopulationV1::SemanticConcept,
                    3 => EngramPopulationV1::ProceduralSkill,
                    4 => EngramPopulationV1::PredictiveWorld,
                    5 => EngramPopulationV1::UtilitySalience,
                    6 => EngramPopulationV1::MetaMemory,
                    _ => return Err("unknown retrieval population wire code".to_string()),
                };
                let support = node
                    .support
                    .into_iter()
                    .map(|item| {
                        Ok(EngramSupportV1 {
                            record_id: id(item.record_id)?,
                            record_revision: Revision::new(item.record_revision)
                                .map_err(|error| error.to_string())?,
                        })
                    })
                    .collect::<Result<Vec<_>, String>>()?;
                Ok(EngramNodeV1 {
                    node_id: id(node.node_id)?,
                    population,
                    support,
                    threshold: FixedQ32::from_raw(node.threshold_q32),
                    confidence: ProbabilityQ32::from_raw(node.confidence_q32)
                        .map_err(|error| error.to_string())?,
                    generation_vector_digest: generation,
                })
            })
            .collect::<Result<Vec<_>, String>>()?;
        let synapses = self
            .synapses
            .into_iter()
            .map(|edge| {
                let relation = match edge.relation {
                    0 => SynapseRelationV1::Associative,
                    1 => SynapseRelationV1::Temporal,
                    2 => SynapseRelationV1::Causal,
                    3 => SynapseRelationV1::Procedural,
                    4 => SynapseRelationV1::Predictive,
                    5 => SynapseRelationV1::Supports,
                    6 => SynapseRelationV1::Inhibitory,
                    7 => SynapseRelationV1::Contradicts,
                    _ => return Err("unknown retrieval relation wire code".to_string()),
                };
                Ok(SynapseV1 {
                    source_node_id: id(edge.source_node_id)?,
                    target_node_id: id(edge.target_node_id)?,
                    relation,
                    weight: FixedQ32::from_raw(edge.weight_q32),
                    support_digest: digest(&edge.support_digest)?,
                    generation_vector_digest: generation,
                })
            })
            .collect::<Result<Vec<_>, String>>()?;
        Ok((digest(&self.generation_digest)?, nodes, synapses))
    }
}
