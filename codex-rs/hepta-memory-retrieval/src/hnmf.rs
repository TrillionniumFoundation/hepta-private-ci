//! Bounded local HNMF recall over a candidate engram.
//!
//! This is deliberately local and deterministic. It never expands the source
//! candidate set, authenticates a source, or grants effect authority. The host
//! must revalidate selected source support immediately before delivery.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::CandidateUnionEntryV1;
use crate::MemoryCueV1;
use crate::RecallAbstentionReasonV1;
use crate::RecallDispositionV1;
use crate::RecallErrorV1;
use crate::RecallPacketV1;
use crate::RecallSelectionV1;
use crate::RetrievalChannelCandidateV1;
use crate::RetrievalPolicyV1;
use crate::build_candidate_union;

pub const MAX_ENGRAM_NODES: usize = 4_096;
pub const MAX_ENGRAM_SYNAPSES: usize = 32_768;
pub const MAX_RECURRENT_STEPS: u8 = 4;
pub const MAX_ACTIVE_UNITS_PER_POPULATION: u16 = 64;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EngramNodeV1 {
    pub record_id: StableId,
    pub population_id: StableId,
    pub cue_bias: FixedQ32,
    pub threshold: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EngramSynapseV1 {
    pub from_record_id: StableId,
    pub to_record_id: StableId,
    pub weight: FixedQ32,
    pub inhibitory: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EngramSnapshotV1 {
    pub generation_vector_digest: Digest32,
    pub nodes: Vec<EngramNodeV1>,
    pub synapses: Vec<EngramSynapseV1>,
}

impl EngramSnapshotV1 {
    pub fn validate(&self) -> Result<(), HnmfRecallErrorV1> {
        if self.generation_vector_digest.is_zero() {
            return Err(HnmfRecallErrorV1::EmptyDigest("engram_generation"));
        }
        if self.nodes.len() > MAX_ENGRAM_NODES {
            return Err(HnmfRecallErrorV1::NodeLimitExceeded);
        }
        if self.synapses.len() > MAX_ENGRAM_SYNAPSES {
            return Err(HnmfRecallErrorV1::SynapseLimitExceeded);
        }
        let mut ids = BTreeSet::new();
        for node in &self.nodes {
            if !ids.insert(node.record_id.clone()) {
                return Err(HnmfRecallErrorV1::DuplicateNode(
                    node.record_id.to_string(),
                ));
            }
            for (name, value) in [("cue_bias", node.cue_bias), ("threshold", node.threshold)] {
                if value < FixedQ32::ZERO || value > FixedQ32::ONE {
                    return Err(HnmfRecallErrorV1::ScoreOutOfRange(name));
                }
            }
        }
        let mut synapses = BTreeSet::new();
        for synapse in &self.synapses {
            if !ids.contains(&synapse.from_record_id) || !ids.contains(&synapse.to_record_id) {
                return Err(HnmfRecallErrorV1::UnknownSynapseEndpoint);
            }
            if synapse.weight < FixedQ32::ZERO || synapse.weight > FixedQ32::ONE {
                return Err(HnmfRecallErrorV1::ScoreOutOfRange("synapse_weight"));
            }
            if !synapses.insert((
                synapse.from_record_id.clone(),
                synapse.to_record_id.clone(),
                synapse.inhibitory,
            )) {
                return Err(HnmfRecallErrorV1::DuplicateSynapse);
            }
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut nodes = self.nodes.iter().collect::<Vec<_>>();
        nodes.sort_by(|left, right| left.record_id.cmp(&right.record_id));
        let mut synapses = self.synapses.iter().collect::<Vec<_>>();
        synapses.sort_by(|left, right| {
            left.from_record_id
                .cmp(&right.from_record_id)
                .then_with(|| left.to_record_id.cmp(&right.to_record_id))
                .then_with(|| left.inhibitory.cmp(&right.inhibitory))
        });
        let mut bytes = b"hepta.retrieval-engram.v1".to_vec();
        bytes.extend_from_slice(self.generation_vector_digest.as_array());
        push_len(&mut bytes, nodes.len());
        for node in nodes {
            push_id(&mut bytes, &node.record_id);
            push_id(&mut bytes, &node.population_id);
            bytes.extend_from_slice(&node.cue_bias.raw().to_be_bytes());
            bytes.extend_from_slice(&node.threshold.raw().to_be_bytes());
        }
        push_len(&mut bytes, synapses.len());
        for synapse in synapses {
            push_id(&mut bytes, &synapse.from_record_id);
            push_id(&mut bytes, &synapse.to_record_id);
            bytes.extend_from_slice(&synapse.weight.raw().to_be_bytes());
            bytes.push(u8::from(synapse.inhibitory));
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecallDynamicsV1 {
    pub recurrent_steps: u8,
    pub maximum_active_units_per_population: u16,
    pub leak: FixedQ32,
}

impl RecallDynamicsV1 {
    pub fn validate(&self) -> Result<(), HnmfRecallErrorV1> {
        if self.recurrent_steps == 0 || self.recurrent_steps > MAX_RECURRENT_STEPS {
            return Err(HnmfRecallErrorV1::InvalidRecurrentSteps);
        }
        if self.maximum_active_units_per_population == 0
            || self.maximum_active_units_per_population > MAX_ACTIVE_UNITS_PER_POPULATION
        {
            return Err(HnmfRecallErrorV1::InvalidPopulationLimit);
        }
        if self.leak < FixedQ32::ZERO || self.leak > FixedQ32::ONE {
            return Err(HnmfRecallErrorV1::ScoreOutOfRange("leak"));
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.recall-dynamics.v1".to_vec();
        bytes.push(self.recurrent_steps);
        bytes.extend_from_slice(&self.maximum_active_units_per_population.to_be_bytes());
        bytes.extend_from_slice(&self.leak.raw().to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecallActivationV1 {
    pub record_id: StableId,
    pub final_activation: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HnmfRecallReceiptV1 {
    pub packet: RecallPacketV1,
    pub engram_digest: Digest32,
    pub dynamics_digest: Digest32,
    pub final_activations: Vec<RecallActivationV1>,
    pub settling_trace_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl HnmfRecallReceiptV1 {
    pub fn validate(&self) -> Result<(), HnmfRecallErrorV1> {
        self.packet.validate().map_err(HnmfRecallErrorV1::Recall)?;
        for digest in [
            self.engram_digest,
            self.dynamics_digest,
            self.settling_trace_digest,
            self.receipt_digest,
        ] {
            if digest.is_zero() {
                return Err(HnmfRecallErrorV1::EmptyDigest("hnmf_receipt"));
            }
        }
        if self
            .final_activations
            .windows(2)
            .any(|pair| pair[0].record_id >= pair[1].record_id)
        {
            return Err(HnmfRecallErrorV1::NonCanonicalActivationOrder);
        }
        for row in &self.final_activations {
            if row.final_activation < FixedQ32::ZERO || row.final_activation > FixedQ32::ONE {
                return Err(HnmfRecallErrorV1::ScoreOutOfRange("final_activation"));
            }
        }
        if self.authority.grants_any() {
            return Err(HnmfRecallErrorV1::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(HnmfRecallErrorV1::DigestMismatch);
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.hnmf-recall-receipt.v1".to_vec();
        bytes.extend_from_slice(self.packet.packet_digest.as_array());
        bytes.extend_from_slice(self.engram_digest.as_array());
        bytes.extend_from_slice(self.dynamics_digest.as_array());
        bytes.extend_from_slice(self.settling_trace_digest.as_array());
        push_len(&mut bytes, self.final_activations.len());
        for row in &self.final_activations {
            push_id(&mut bytes, &row.record_id);
            bytes.extend_from_slice(&row.final_activation.raw().to_be_bytes());
        }
        Digest32::of_bytes(&bytes)
    }
}

pub fn recall_with_engram(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    candidates: Vec<RetrievalChannelCandidateV1>,
    engram: &EngramSnapshotV1,
    dynamics: &RecallDynamicsV1,
) -> Result<HnmfRecallReceiptV1, HnmfRecallErrorV1> {
    cue.validate().map_err(HnmfRecallErrorV1::Recall)?;
    policy.validate().map_err(HnmfRecallErrorV1::Recall)?;
    engram.validate()?;
    dynamics.validate()?;
    if engram.generation_vector_digest != cue.snapshot_key.vector_digest {
        return Err(HnmfRecallErrorV1::GenerationVectorMismatch);
    }
    let union = build_candidate_union(cue, policy, candidates).map_err(HnmfRecallErrorV1::Recall)?;

    let node_by_record = engram
        .nodes
        .iter()
        .enumerate()
        .map(|(index, node)| (node.record_id.clone(), index))
        .collect::<BTreeMap<_, _>>();
    if union
        .entries
        .iter()
        .any(|entry| !node_by_record.contains_key(&entry.record.record_id))
    {
        return Err(HnmfRecallErrorV1::MissingCandidateNode);
    }

    let entry_by_record = union
        .entries
        .iter()
        .map(|entry| (entry.record.record_id.clone(), entry))
        .collect::<BTreeMap<_, _>>();
    let mut activation = vec![FixedQ32::ZERO; engram.nodes.len()];
    for (index, node) in engram.nodes.iter().enumerate() {
        let base = entry_by_record
            .get(&node.record_id)
            .map(|entry| entry.weighted_score)
            .unwrap_or(FixedQ32::ZERO);
        activation[index] = base
            .checked_add(node.cue_bias)
            .map_err(|_| HnmfRecallErrorV1::Arithmetic)?
            .checked_sub(node.threshold)
            .map_err(|_| HnmfRecallErrorV1::Arithmetic)?
            .clamp(FixedQ32::ZERO, FixedQ32::ONE)
            .map_err(|_| HnmfRecallErrorV1::Arithmetic)?;
    }

    let mut trace_bytes = b"hepta.hnmf-settling-trace.v1".to_vec();
    record_trace(&mut trace_bytes, 0, &engram.nodes, &activation);
    for step in 0..dynamics.recurrent_steps {
        let mut next = Vec::with_capacity(engram.nodes.len());
        for (index, node) in engram.nodes.iter().enumerate() {
            let base = entry_by_record
                .get(&node.record_id)
                .map(|entry| entry.weighted_score)
                .unwrap_or(FixedQ32::ZERO);
            let leaked = activation[index]
                .checked_mul(dynamics.leak)
                .map_err(|_| HnmfRecallErrorV1::Arithmetic)?;
            let mut value = base
                .checked_add(node.cue_bias)
                .and_then(|value| value.checked_add(leaked))
                .map_err(|_| HnmfRecallErrorV1::Arithmetic)?;
            for synapse in engram
                .synapses
                .iter()
                .filter(|synapse| synapse.to_record_id == node.record_id)
            {
                let source = *node_by_record
                    .get(&synapse.from_record_id)
                    .ok_or(HnmfRecallErrorV1::UnknownSynapseEndpoint)?;
                let contribution = activation[source]
                    .checked_mul(synapse.weight)
                    .map_err(|_| HnmfRecallErrorV1::Arithmetic)?;
                value = if synapse.inhibitory {
                    value
                        .checked_sub(contribution)
                        .map_err(|_| HnmfRecallErrorV1::Arithmetic)?
                } else {
                    value
                        .checked_add(contribution)
                        .map_err(|_| HnmfRecallErrorV1::Arithmetic)?
                };
            }
            next.push(
                value
                    .checked_sub(node.threshold)
                    .map_err(|_| HnmfRecallErrorV1::Arithmetic)?
                    .clamp(FixedQ32::ZERO, FixedQ32::ONE)
                    .map_err(|_| HnmfRecallErrorV1::Arithmetic)?,
            );
        }
        apply_population_competition(
            &engram.nodes,
            &mut next,
            usize::from(dynamics.maximum_active_units_per_population),
        );
        activation = next;
        record_trace(&mut trace_bytes, step + 1, &engram.nodes, &activation);
    }

    let activation_by_record = engram
        .nodes
        .iter()
        .zip(&activation)
        .map(|(node, value)| (node.record_id.clone(), *value))
        .collect::<BTreeMap<_, _>>();
    let mut ranked = union.entries.clone();
    ranked.sort_by(|left, right| {
        activation_by_record[&right.record.record_id]
            .cmp(&activation_by_record[&left.record.record_id])
            .then_with(|| left.record.record_id.cmp(&right.record.record_id))
            .then_with(|| left.record.revision.cmp(&right.record.revision))
    });

    let minimum_channels = usize::try_from(policy.minimum_distinct_channels).unwrap_or(usize::MAX);
    let observed_channels = usize::try_from(union.distinct_channels).unwrap_or(0);
    let maximum_ood = ranked
        .iter()
        .map(|entry| entry.maximum_ood)
        .max()
        .unwrap_or(codex_hepta_types::ProbabilityQ32::ZERO);
    let top_activation = ranked
        .first()
        .map(|entry| activation_by_record[&entry.record.record_id])
        .unwrap_or(FixedQ32::ZERO);
    let reason = if ranked.is_empty() {
        Some(RecallAbstentionReasonV1::NoCandidate)
    } else if observed_channels < minimum_channels {
        Some(RecallAbstentionReasonV1::InsufficientChannelCoverage)
    } else if policy.abstain_on_contradiction && contradiction_population_count(&ranked) > 0 {
        Some(RecallAbstentionReasonV1::ContradictoryEvidence)
    } else if maximum_ood > policy.maximum_ood {
        Some(RecallAbstentionReasonV1::OutOfDistribution)
    } else if top_activation < policy.minimum_total_score {
        Some(RecallAbstentionReasonV1::ScoreBelowFloor)
    } else {
        None
    };

    let maximum_results = usize::try_from(policy.maximum_results).unwrap_or(0);
    let (disposition, selections, omitted_count) = match reason {
        Some(reason) => (RecallDispositionV1::Abstained(reason), Vec::new(), 0),
        None => {
            let selected = ranked
                .iter()
                .filter(|entry| activation_by_record[&entry.record.record_id] > FixedQ32::ZERO)
                .take(maximum_results)
                .map(|entry| selection_from_entry(entry, activation_by_record[&entry.record.record_id]))
                .collect::<Vec<_>>();
            if selected.is_empty() {
                (RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ScoreBelowFloor), Vec::new(), 0)
            } else {
                let omitted = ranked.len().saturating_sub(selected.len());
                (
                    RecallDispositionV1::Recalled,
                    selected,
                    u32::try_from(omitted).unwrap_or(u32::MAX),
                )
            }
        }
    };

    let mut packet = RecallPacketV1 {
        cue_digest: union.cue_digest,
        policy_digest: union.policy_digest,
        candidate_union_digest: union.union_digest,
        generation_vector_digest: union.generation_vector_digest,
        disposition,
        selections,
        omitted_count,
        distinct_channels: union.distinct_channels,
        packet_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    packet.packet_digest = packet.compute_packet_digest();
    packet.validate().map_err(HnmfRecallErrorV1::Recall)?;

    let mut final_activations = engram
        .nodes
        .iter()
        .zip(activation)
        .map(|(node, final_activation)| RecallActivationV1 {
            record_id: node.record_id.clone(),
            final_activation,
        })
        .collect::<Vec<_>>();
    final_activations.sort_by(|left, right| left.record_id.cmp(&right.record_id));

    let mut receipt = HnmfRecallReceiptV1 {
        packet,
        engram_digest: engram.digest(),
        dynamics_digest: dynamics.digest(),
        final_activations,
        settling_trace_digest: Digest32::of_bytes(&trace_bytes),
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    receipt.validate()?;
    Ok(receipt)
}

fn selection_from_entry(entry: &CandidateUnionEntryV1, score: FixedQ32) -> RecallSelectionV1 {
    RecallSelectionV1 {
        record_id: entry.record.record_id.clone(),
        record_revision: entry.record.revision,
        record_digest: entry.record.record_digest(),
        weighted_score: score,
        maximum_ood: entry.maximum_ood,
        channels: entry.channels.clone(),
        support_digests: entry.support_digests.clone(),
        contradiction_group_digests: entry.contradiction_group_digests.clone(),
    }
}

fn apply_population_competition(
    nodes: &[EngramNodeV1],
    activation: &mut [FixedQ32],
    maximum_active: usize,
) {
    let mut populations = BTreeMap::<StableId, Vec<usize>>::new();
    for (index, node) in nodes.iter().enumerate() {
        populations
            .entry(node.population_id.clone())
            .or_default()
            .push(index);
    }
    for indices in populations.values_mut() {
        indices.sort_by(|left, right| {
            activation[*right]
                .cmp(&activation[*left])
                .then_with(|| nodes[*left].record_id.cmp(&nodes[*right].record_id))
        });
        for index in indices.iter().skip(maximum_active) {
            activation[*index] = FixedQ32::ZERO;
        }
    }
}

fn contradiction_population_count(entries: &[CandidateUnionEntryV1]) -> usize {
    let mut populations = BTreeMap::<Digest32, usize>::new();
    for entry in entries {
        for group in &entry.contradiction_group_digests {
            *populations.entry(*group).or_insert(0) += 1;
        }
    }
    populations.values().filter(|count| **count > 1).count()
}

fn record_trace(
    bytes: &mut Vec<u8>,
    step: u8,
    nodes: &[EngramNodeV1],
    activation: &[FixedQ32],
) {
    bytes.push(step);
    let mut rows = nodes.iter().zip(activation).collect::<Vec<_>>();
    rows.sort_by(|left, right| left.0.record_id.cmp(&right.0.record_id));
    push_len(bytes, rows.len());
    for (node, value) in rows {
        push_id(bytes, &node.record_id);
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum HnmfRecallErrorV1 {
    Recall(RecallErrorV1),
    EmptyDigest(&'static str),
    NodeLimitExceeded,
    SynapseLimitExceeded,
    DuplicateNode(String),
    DuplicateSynapse,
    UnknownSynapseEndpoint,
    MissingCandidateNode,
    GenerationVectorMismatch,
    InvalidRecurrentSteps,
    InvalidPopulationLimit,
    ScoreOutOfRange(&'static str),
    NonCanonicalActivationOrder,
    AuthorityGranted,
    DigestMismatch,
    Arithmetic,
}

impl fmt::Display for HnmfRecallErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for HnmfRecallErrorV1 {}

#[cfg(test)]
#[path = "hnmf_tests.rs"]
mod tests;
