//! Strict bounded wire decoder. Parsing proves structure, never authenticity.
//! Signatures and currentness are verified by the existing leased provider.

use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_memory::RetrievalExecutionContextV1;
use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;
use codex_hepta_memory_retrieval::EngramSnapshotV1;
use codex_hepta_memory_retrieval::RetrievalChannelV1;
use codex_hepta_memory_retrieval::RetrievalChannelWeightV1;
use codex_hepta_memory_retrieval::RetrievalPolicyV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use serde::Deserialize;

#[path = "cognitive_retrieval_engram_codec.rs"]
mod engram;

pub(super) const MAX_CONTEXT_BYTES: usize = 16 * 1024 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ContextWire {
    schema: String,
    generation_vector: VectorWire,
    objective_digest: String,
    approved_context_digest: String,
    cue_profile_digest: String,
    retrieval_policy: PolicyWire,
    dynamics_policy: DynamicsWire,
    engram: engram::EngramWire,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct VectorWire {
    scope_id: String,
    purpose_id: String,
    memory_ledger_frontier: u64,
    knowledge_fact_frontier: u64,
    tombstone_frontier: u64,
    source_ledger_frontier: u64,
    knowledge_graph_generation: u64,
    compact_checkpoint_generation: u64,
    prompt_registry_revision: u64,
    retrieval_profile_digest: String,
    encoder_preprocessor_digest: String,
    authority_epoch: u64,
    model_digest: String,
    tokenizer_digest: String,
    template_digest: String,
    tool_schema_digest: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PolicyWire {
    policy_id: String,
    channel_weights: Vec<ChannelWire>,
    maximum_results: u32,
    minimum_total_score_q32: i64,
    maximum_ood_q32: u64,
    minimum_distinct_channels: u32,
    abstain_on_contradiction: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ChannelWire {
    channel: u8,
    weight_q32: i64,
    maximum_candidates: u32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DynamicsWire {
    policy_id: String,
    maximum_nodes: u32,
    maximum_synapses: u32,
    maximum_active_per_population: u32,
    maximum_active_nodes: u32,
    maximum_settling_steps: u8,
    maximum_graph_hops: u8,
    maximum_activation_paths: u32,
    leak_q32: i64,
    lateral_inhibition_q32: i64,
    minimum_activation_q32: i64,
    contradiction_forces_abstention: bool,
}

pub(super) fn decode(bytes: &[u8]) -> Result<RetrievalExecutionContextV1, String> {
    if bytes.is_empty() || bytes.len() > MAX_CONTEXT_BYTES {
        return Err("retrieval context wire byte limit".to_string());
    }
    // Typed serde structs reject duplicate fields, unknown fields, Boolean
    // integers, fractional integers and integer overflow at every level.
    let wire: ContextWire = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
    if wire.schema != "hepta.agentd.retrieval-context-json.v1" {
        return Err("unsupported retrieval context wire schema".to_string());
    }
    let v = wire.generation_vector;
    let vector = LaneCGenerationVectorV1 {
        scope_id: id(v.scope_id)?,
        purpose_id: id(v.purpose_id)?,
        memory_ledger_frontier: v.memory_ledger_frontier,
        knowledge_fact_frontier: v.knowledge_fact_frontier,
        tombstone_frontier: v.tombstone_frontier,
        source_ledger_frontier: v.source_ledger_frontier,
        knowledge_graph_generation: Generation::new(v.knowledge_graph_generation)
            .map_err(|error| error.to_string())?,
        compact_checkpoint_generation: Generation::new(v.compact_checkpoint_generation)
            .map_err(|error| error.to_string())?,
        prompt_registry_revision: Revision::new(v.prompt_registry_revision)
            .map_err(|error| error.to_string())?,
        retrieval_profile_digest: digest(&v.retrieval_profile_digest)?,
        encoder_preprocessor_digest: digest(&v.encoder_preprocessor_digest)?,
        authority_epoch: v.authority_epoch,
        model_digest: digest(&v.model_digest)?,
        tokenizer_digest: digest(&v.tokenizer_digest)?,
        template_digest: digest(&v.template_digest)?,
        tool_schema_digest: digest(&v.tool_schema_digest)?,
    };
    vector.validate().map_err(|error| error.to_string())?;
    let p = wire.retrieval_policy;
    if p.channel_weights.len() > 8 {
        return Err("retrieval channel wire limit".to_string());
    }
    let policy = RetrievalPolicyV1 {
        policy_id: id(p.policy_id)?,
        channel_weights: p
            .channel_weights
            .into_iter()
            .map(|row| {
                let channel = match row.channel {
                    0 => RetrievalChannelV1::Lexical,
                    1 => RetrievalChannelV1::Vector,
                    2 => RetrievalChannelV1::Entity,
                    3 => RetrievalChannelV1::Temporal,
                    4 => RetrievalChannelV1::Causal,
                    5 => RetrievalChannelV1::Procedural,
                    6 => RetrievalChannelV1::ContradictionSupport,
                    7 => RetrievalChannelV1::Graph,
                    _ => return Err("unknown retrieval channel wire code".to_string()),
                };
                Ok(RetrievalChannelWeightV1 {
                    channel,
                    weight: FixedQ32::from_raw(row.weight_q32),
                    maximum_candidates: row.maximum_candidates,
                })
            })
            .collect::<Result<Vec<_>, String>>()?,
        maximum_results: p.maximum_results,
        minimum_total_score: FixedQ32::from_raw(p.minimum_total_score_q32),
        maximum_ood: ProbabilityQ32::from_raw(p.maximum_ood_q32)
            .map_err(|error| error.to_string())?,
        minimum_distinct_channels: p.minimum_distinct_channels,
        abstain_on_contradiction: p.abstain_on_contradiction,
    };
    let d = wire.dynamics_policy;
    let dynamics = EngramDynamicsPolicyV1 {
        policy_id: id(d.policy_id)?,
        maximum_nodes: d.maximum_nodes,
        maximum_synapses: d.maximum_synapses,
        maximum_active_per_population: d.maximum_active_per_population,
        maximum_active_nodes: d.maximum_active_nodes,
        maximum_settling_steps: d.maximum_settling_steps,
        maximum_graph_hops: d.maximum_graph_hops,
        maximum_activation_paths: d.maximum_activation_paths,
        leak: FixedQ32::from_raw(d.leak_q32),
        lateral_inhibition: FixedQ32::from_raw(d.lateral_inhibition_q32),
        minimum_activation: FixedQ32::from_raw(d.minimum_activation_q32),
        contradiction_forces_abstention: d.contradiction_forces_abstention,
    };
    let vector_digest = vector.digest();
    let (engram_generation, nodes, synapses) = wire.engram.decode(vector_digest)?;
    let context = RetrievalExecutionContextV1 {
        generation_vector: vector,
        objective_digest: digest(&wire.objective_digest)?,
        approved_context_digest: digest(&wire.approved_context_digest)?,
        cue_profile_digest: digest(&wire.cue_profile_digest)?,
        retrieval_policy: policy,
        engram_snapshot: EngramSnapshotV1::new(vector_digest, engram_generation, nodes, synapses)
            .map_err(|error| error.to_string())?,
        dynamics_policy: dynamics,
    };
    context.validate().map_err(|error| error.to_string())?;
    Ok(context)
}

pub(super) fn digest(value: &str) -> Result<Digest32, String> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("retrieval digest must be canonical lowercase SHA-256 hex".to_string());
    }
    value.parse::<Digest32>().map_err(|error| error.to_string())
}

pub(super) fn id(value: String) -> Result<StableId, String> {
    StableId::new(value).map_err(|error| error.to_string())
}

#[cfg(test)]
#[path = "cognitive_retrieval_context_codec_tests.rs"]
mod tests;
