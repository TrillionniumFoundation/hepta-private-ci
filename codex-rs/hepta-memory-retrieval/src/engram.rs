//! Generation-bound HNMF local engram expansion, recurrent settling and sparse competition.
//!
//! This is a pure deterministic core. It owns no store, encoder, clock, model
//! invocation or effect authority. The supplied snapshot must already be a
//! bounded immutable projection from its owner.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::CandidateUnionEntryV1;
use crate::CandidateUnionV1;
use crate::MAX_GENERATION_BOUND_CANDIDATES;
use crate::MemoryCueV1;
use crate::RecallAbstentionReasonV1;
use crate::RecallDispositionV1;
use crate::RecallErrorV1;
use crate::RecallPacketV1;
use crate::RecallSelectionV1;
use crate::RetrievalChannelCandidateV1;
use crate::RetrievalPolicyV1;
use crate::build_candidate_union;
use crate::generation_bound::admitted_distinct_channel_count;
use crate::generation_bound::contradiction_population_count;
use crate::generation_bound::risk_admitted_entries;
use crate::generation_bound::score_admitted_entries;

pub const MAX_ENGRAM_NODES: usize = 4096;
pub const MAX_ENGRAM_SYNAPSES: usize = 32_768;
pub const MAX_ENGRAM_SETTLING_STEPS: u8 = 4;
pub const MAX_ACTIVE_PER_POPULATION: usize = 64;
pub const MAX_ACTIVE_NODES: usize = 7 * MAX_ACTIVE_PER_POPULATION;
pub const MAX_ACTIVATION_PATHS: usize = 64;
pub const MAX_ENGRAM_GRAPH_HOPS: u8 = 2;

const ENGRAM_SNAPSHOT_DOMAIN: &[u8] = b"hepta.engram-snapshot.v1";
const ENGRAM_POLICY_DOMAIN: &[u8] = b"hepta.engram-dynamics-policy.v1";
const ENGRAM_RECALL_DOMAIN: &[u8] = b"hepta.engram-recall.v1";
const ENGRAM_RESOURCE_DOMAIN: &[u8] = b"hepta.engram-resource-receipt.v1";

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum EngramPopulationV1 {
    SensoryTrace,
    EpisodicBinding,
    SemanticConcept,
    ProceduralSkill,
    PredictiveWorld,
    UtilitySalience,
    MetaMemory,
}

impl EngramPopulationV1 {
    const ALL: [Self; 7] = [
        Self::SensoryTrace,
        Self::EpisodicBinding,
        Self::SemanticConcept,
        Self::ProceduralSkill,
        Self::PredictiveWorld,
        Self::UtilitySalience,
        Self::MetaMemory,
    ];
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum SynapseRelationV1 {
    Associative,
    Temporal,
    Causal,
    Procedural,
    Predictive,
    Supports,
    Inhibitory,
    Contradicts,
}

impl SynapseRelationV1 {
    const fn negative(self) -> bool {
        matches!(self, Self::Inhibitory | Self::Contradicts)
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct EngramSupportV1 {
    pub record_id: StableId,
    pub record_revision: Revision,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EngramNodeV1 {
    pub node_id: StableId,
    pub population: EngramPopulationV1,
    pub support: Vec<EngramSupportV1>,
    pub threshold: FixedQ32,
    pub confidence: ProbabilityQ32,
    pub generation_vector_digest: Digest32,
}

impl EngramNodeV1 {
    fn validate(&self, generation_vector_digest: Digest32) -> Result<(), EngramErrorV1> {
        if self.support.is_empty() {
            return Err(EngramErrorV1::EmptySupport(self.node_id.to_string()));
        }
        if !strictly_sorted_unique(&self.support) {
            return Err(EngramErrorV1::NonCanonical("node_support"));
        }
        if self.threshold < FixedQ32::ZERO || self.threshold > FixedQ32::ONE {
            return Err(EngramErrorV1::ScoreOutOfRange("node_threshold"));
        }
        if self.generation_vector_digest.is_zero()
            || self.generation_vector_digest != generation_vector_digest
        {
            return Err(EngramErrorV1::GenerationMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SynapseV1 {
    pub source_node_id: StableId,
    pub target_node_id: StableId,
    pub relation: SynapseRelationV1,
    pub weight: FixedQ32,
    pub support_digest: Digest32,
    pub generation_vector_digest: Digest32,
}

impl SynapseV1 {
    fn validate(&self, generation_vector_digest: Digest32) -> Result<(), EngramErrorV1> {
        if self.source_node_id == self.target_node_id {
            return Err(EngramErrorV1::SelfSynapse(self.source_node_id.to_string()));
        }
        if self.weight < FixedQ32::from_raw(-FixedQ32::ONE.raw()) || self.weight > FixedQ32::ONE {
            return Err(EngramErrorV1::ScoreOutOfRange("synapse_weight"));
        }
        if self.support_digest.is_zero() {
            return Err(EngramErrorV1::EmptyDigest("synapse_support"));
        }
        if self.generation_vector_digest.is_zero()
            || self.generation_vector_digest != generation_vector_digest
        {
            return Err(EngramErrorV1::GenerationMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EngramSnapshotV1 {
    pub generation_vector_digest: Digest32,
    pub engram_generation_digest: Digest32,
    pub nodes: Vec<EngramNodeV1>,
    pub synapses: Vec<SynapseV1>,
    pub snapshot_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl EngramSnapshotV1 {
    pub fn new(
        generation_vector_digest: Digest32,
        engram_generation_digest: Digest32,
        mut nodes: Vec<EngramNodeV1>,
        mut synapses: Vec<SynapseV1>,
    ) -> Result<Self, EngramErrorV1> {
        nodes.sort_by(|left, right| left.node_id.cmp(&right.node_id));
        synapses.sort_by_key(synapse_key);
        let mut value = Self {
            generation_vector_digest,
            engram_generation_digest,
            nodes,
            synapses,
            snapshot_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        value.snapshot_digest = value.compute_snapshot_digest();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), EngramErrorV1> {
        if self.generation_vector_digest.is_zero() {
            return Err(EngramErrorV1::EmptyDigest("engram_generation_vector"));
        }
        if self.engram_generation_digest.is_zero() {
            return Err(EngramErrorV1::EmptyDigest("engram_generation"));
        }
        if self.nodes.len() > MAX_ENGRAM_NODES {
            return Err(EngramErrorV1::NodeLimitExceeded);
        }
        if self.synapses.len() > MAX_ENGRAM_SYNAPSES {
            return Err(EngramErrorV1::SynapseLimitExceeded);
        }
        if self.authority.grants_any() {
            return Err(EngramErrorV1::AuthorityGranted);
        }
        if !strictly_sorted_by(&self.nodes, |node| node.node_id.clone()) {
            return Err(EngramErrorV1::NonCanonical("nodes"));
        }
        let mut node_ids = BTreeSet::new();
        for node in &self.nodes {
            node.validate(self.generation_vector_digest)?;
            if !node_ids.insert(node.node_id.clone()) {
                return Err(EngramErrorV1::DuplicateNode(node.node_id.to_string()));
            }
        }
        let mut edges = BTreeSet::new();
        let mut previous = None;
        for synapse in &self.synapses {
            synapse.validate(self.generation_vector_digest)?;
            if !node_ids.contains(&synapse.source_node_id)
                || !node_ids.contains(&synapse.target_node_id)
            {
                return Err(EngramErrorV1::MissingSynapseEndpoint);
            }
            let key = synapse_key(synapse);
            if !edges.insert(key.clone()) {
                return Err(EngramErrorV1::DuplicateSynapse);
            }
            if previous.as_ref().is_some_and(|value| value >= &key) {
                return Err(EngramErrorV1::NonCanonical("synapses"));
            }
            previous = Some(key);
        }
        if self.snapshot_digest != self.compute_snapshot_digest() {
            return Err(EngramErrorV1::DigestMismatch("engram_snapshot"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_snapshot_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ENGRAM_SNAPSHOT_DOMAIN);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_digest(&mut bytes, self.engram_generation_digest);
        push_len(&mut bytes, self.nodes.len());
        for node in &self.nodes {
            push_id(&mut bytes, &node.node_id);
            bytes.push(population_code(node.population));
            push_i64(&mut bytes, node.threshold.raw());
            push_u64(&mut bytes, node.confidence.raw());
            push_len(&mut bytes, node.support.len());
            for support in &node.support {
                push_id(&mut bytes, &support.record_id);
                push_u64(&mut bytes, support.record_revision.get());
            }
        }
        push_len(&mut bytes, self.synapses.len());
        for synapse in &self.synapses {
            push_id(&mut bytes, &synapse.source_node_id);
            push_id(&mut bytes, &synapse.target_node_id);
            bytes.push(relation_code(synapse.relation));
            push_i64(&mut bytes, synapse.weight.raw());
            push_digest(&mut bytes, synapse.support_digest);
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EngramDynamicsPolicyV1 {
    pub policy_id: StableId,
    pub maximum_nodes: u32,
    pub maximum_synapses: u32,
    pub maximum_active_per_population: u32,
    pub maximum_active_nodes: u32,
    pub maximum_settling_steps: u8,
    pub maximum_graph_hops: u8,
    pub maximum_activation_paths: u32,
    pub leak: FixedQ32,
    pub lateral_inhibition: FixedQ32,
    pub minimum_activation: FixedQ32,
    pub contradiction_forces_abstention: bool,
}

impl EngramDynamicsPolicyV1 {
    pub fn product_default() -> Result<Self, EngramErrorV1> {
        let value = Self {
            policy_id: StableId::new("policy:hnmf-engram-v1")
                .map_err(|error| EngramErrorV1::InvalidId(error.to_string()))?,
            maximum_nodes: u32::try_from(MAX_ENGRAM_NODES).unwrap_or(u32::MAX),
            maximum_synapses: u32::try_from(MAX_ENGRAM_SYNAPSES).unwrap_or(u32::MAX),
            maximum_active_per_population: u32::try_from(MAX_ACTIVE_PER_POPULATION)
                .unwrap_or(u32::MAX),
            maximum_active_nodes: u32::try_from(MAX_ACTIVE_NODES).unwrap_or(u32::MAX),
            maximum_settling_steps: MAX_ENGRAM_SETTLING_STEPS,
            maximum_graph_hops: MAX_ENGRAM_GRAPH_HOPS,
            maximum_activation_paths: u32::try_from(MAX_ACTIVATION_PATHS).unwrap_or(u32::MAX),
            leak: FixedQ32::from_raw(1_i64 << 30),
            lateral_inhibition: FixedQ32::from_raw(1_i64 << 26),
            minimum_activation: FixedQ32::from_raw(1),
            contradiction_forces_abstention: true,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), EngramErrorV1> {
        let maximum_nodes = usize::try_from(self.maximum_nodes).unwrap_or(usize::MAX);
        let maximum_synapses = usize::try_from(self.maximum_synapses).unwrap_or(usize::MAX);
        let maximum_active_per_population =
            usize::try_from(self.maximum_active_per_population).unwrap_or(usize::MAX);
        let maximum_active_nodes = usize::try_from(self.maximum_active_nodes).unwrap_or(usize::MAX);
        let maximum_activation_paths =
            usize::try_from(self.maximum_activation_paths).unwrap_or(usize::MAX);
        if maximum_nodes == 0 || maximum_nodes > MAX_ENGRAM_NODES {
            return Err(EngramErrorV1::NodeLimitExceeded);
        }
        if maximum_synapses == 0 || maximum_synapses > MAX_ENGRAM_SYNAPSES {
            return Err(EngramErrorV1::SynapseLimitExceeded);
        }
        if maximum_active_per_population == 0
            || maximum_active_per_population > MAX_ACTIVE_PER_POPULATION
        {
            return Err(EngramErrorV1::ActivePopulationLimitExceeded);
        }
        if maximum_active_nodes == 0 || maximum_active_nodes > MAX_ACTIVE_NODES {
            return Err(EngramErrorV1::ActiveNodeLimitExceeded);
        }
        if !(1..=MAX_ENGRAM_SETTLING_STEPS).contains(&self.maximum_settling_steps) {
            return Err(EngramErrorV1::SettlingStepLimitExceeded);
        }
        if self.maximum_graph_hops > MAX_ENGRAM_GRAPH_HOPS {
            return Err(EngramErrorV1::GraphHopLimitExceeded);
        }
        if maximum_activation_paths == 0 || maximum_activation_paths > MAX_ACTIVATION_PATHS {
            return Err(EngramErrorV1::ActivationPathLimitExceeded);
        }
        for (name, value) in [
            ("leak", self.leak),
            ("lateral_inhibition", self.lateral_inhibition),
        ] {
            if value < FixedQ32::ZERO || value > FixedQ32::ONE {
                return Err(EngramErrorV1::ScoreOutOfRange(name));
            }
        }
        if self.minimum_activation <= FixedQ32::ZERO || self.minimum_activation > FixedQ32::ONE {
            return Err(EngramErrorV1::ScoreOutOfRange("minimum_activation"));
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ENGRAM_POLICY_DOMAIN);
        push_id(&mut bytes, &self.policy_id);
        push_u64(&mut bytes, u64::from(self.maximum_nodes));
        push_u64(&mut bytes, u64::from(self.maximum_synapses));
        push_u64(&mut bytes, u64::from(self.maximum_active_per_population));
        push_u64(&mut bytes, u64::from(self.maximum_active_nodes));
        bytes.push(self.maximum_settling_steps);
        bytes.push(self.maximum_graph_hops);
        push_u64(&mut bytes, u64::from(self.maximum_activation_paths));
        push_i64(&mut bytes, self.leak.raw());
        push_i64(&mut bytes, self.lateral_inhibition.raw());
        push_i64(&mut bytes, self.minimum_activation.raw());
        bytes.push(u8::from(self.contradiction_forces_abstention));
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActiveEngramNodeV1 {
    pub node_id: StableId,
    pub population: EngramPopulationV1,
    pub activation: FixedQ32,
    pub confidence: ProbabilityQ32,
    pub support: Vec<EngramSupportV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EngramActivationPathV1 {
    pub source_node_id: StableId,
    pub target_node_id: StableId,
    pub relation: SynapseRelationV1,
    pub contribution: FixedQ32,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct EngramContradictionV1 {
    pub left_node_id: StableId,
    pub right_node_id: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EngramResourceReceiptV1 {
    pub candidate_records: u32,
    pub expanded_nodes: u32,
    pub traversed_synapses: u32,
    pub active_nodes: u32,
    pub settling_steps: u8,
    pub receipt_digest: Digest32,
}

impl EngramResourceReceiptV1 {
    fn compute_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ENGRAM_RESOURCE_DOMAIN);
        push_u64(&mut bytes, u64::from(self.candidate_records));
        push_u64(&mut bytes, u64::from(self.expanded_nodes));
        push_u64(&mut bytes, u64::from(self.traversed_synapses));
        push_u64(&mut bytes, u64::from(self.active_nodes));
        bytes.push(self.settling_steps);
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), EngramErrorV1> {
        if self.settling_steps == 0 || self.settling_steps > MAX_ENGRAM_SETTLING_STEPS {
            return Err(EngramErrorV1::SettlingStepLimitExceeded);
        }
        let candidate_records =
            usize::try_from(self.candidate_records).map_err(|_| EngramErrorV1::Arithmetic)?;
        let expanded_nodes =
            usize::try_from(self.expanded_nodes).map_err(|_| EngramErrorV1::Arithmetic)?;
        let traversed_synapses =
            usize::try_from(self.traversed_synapses).map_err(|_| EngramErrorV1::Arithmetic)?;
        let active_nodes =
            usize::try_from(self.active_nodes).map_err(|_| EngramErrorV1::Arithmetic)?;
        if candidate_records > MAX_GENERATION_BOUND_CANDIDATES {
            return Err(EngramErrorV1::PolicyBoundExceeded);
        }
        if expanded_nodes > MAX_ENGRAM_NODES {
            return Err(EngramErrorV1::NodeLimitExceeded);
        }
        if active_nodes > MAX_ACTIVE_NODES || active_nodes > expanded_nodes {
            return Err(EngramErrorV1::ActiveNodeLimitExceeded);
        }
        let maximum_traversals = MAX_ENGRAM_SYNAPSES
            .checked_mul(usize::from(self.settling_steps))
            .ok_or(EngramErrorV1::Arithmetic)?;
        if traversed_synapses > maximum_traversals {
            return Err(EngramErrorV1::SynapseLimitExceeded);
        }
        if self.receipt_digest != self.compute_digest() {
            return Err(EngramErrorV1::DigestMismatch("engram_resource"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EngramRecallReceiptV1 {
    pub generation_vector_digest: Digest32,
    pub engram_snapshot_digest: Digest32,
    pub dynamics_policy_digest: Digest32,
    pub active_nodes: Vec<ActiveEngramNodeV1>,
    pub activation_paths: Vec<EngramActivationPathV1>,
    pub contradictions: Vec<EngramContradictionV1>,
    pub selected_support: Vec<EngramSupportV1>,
    pub coverage: ProbabilityQ32,
    pub confidence: ProbabilityQ32,
    pub settling_steps: u8,
    pub resources: EngramResourceReceiptV1,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl EngramRecallReceiptV1 {
    pub fn validate(&self) -> Result<(), EngramErrorV1> {
        if self.generation_vector_digest.is_zero() {
            return Err(EngramErrorV1::EmptyDigest("engram_generation_vector"));
        }
        if self.engram_snapshot_digest.is_zero() {
            return Err(EngramErrorV1::EmptyDigest("engram_snapshot"));
        }
        if self.dynamics_policy_digest.is_zero() {
            return Err(EngramErrorV1::EmptyDigest("engram_policy"));
        }
        if self.settling_steps == 0 || self.settling_steps > MAX_ENGRAM_SETTLING_STEPS {
            return Err(EngramErrorV1::SettlingStepLimitExceeded);
        }
        if self.active_nodes.len() > MAX_ACTIVE_NODES {
            return Err(EngramErrorV1::ActiveNodeLimitExceeded);
        }
        if self.activation_paths.len() > MAX_ACTIVATION_PATHS {
            return Err(EngramErrorV1::ActivationPathLimitExceeded);
        }
        let mut active_ids = BTreeSet::new();
        let mut active_support = BTreeSet::new();
        let mut population_counts = BTreeMap::<EngramPopulationV1, usize>::new();
        let mut previous_active: Option<&ActiveEngramNodeV1> = None;
        for node in &self.active_nodes {
            if node.activation <= FixedQ32::ZERO || node.activation > FixedQ32::ONE {
                return Err(EngramErrorV1::ScoreOutOfRange("active_node_activation"));
            }
            if node.support.is_empty() {
                return Err(EngramErrorV1::EmptySupport(node.node_id.to_string()));
            }
            if !strictly_sorted_unique(&node.support) {
                return Err(EngramErrorV1::NonCanonical("active_node_support"));
            }
            if !active_ids.insert(node.node_id.clone()) {
                return Err(EngramErrorV1::DuplicateNode(node.node_id.to_string()));
            }
            let population_count = population_counts.entry(node.population).or_insert(0);
            *population_count = population_count
                .checked_add(1)
                .ok_or(EngramErrorV1::Arithmetic)?;
            if *population_count > MAX_ACTIVE_PER_POPULATION {
                return Err(EngramErrorV1::ActivePopulationLimitExceeded);
            }
            active_support.extend(node.support.iter().cloned());
            if let Some(left) = previous_active {
                let ordered = left.activation > node.activation
                    || (left.activation == node.activation && left.node_id < node.node_id);
                if !ordered {
                    return Err(EngramErrorV1::NonCanonical("active_nodes"));
                }
            }
            previous_active = Some(node);
        }

        let mut path_keys = BTreeSet::new();
        let mut previous_path: Option<&EngramActivationPathV1> = None;
        for path in &self.activation_paths {
            if path.source_node_id == path.target_node_id
                || !active_ids.contains(&path.source_node_id)
                || !active_ids.contains(&path.target_node_id)
            {
                return Err(EngramErrorV1::MissingSynapseEndpoint);
            }
            if path.contribution == FixedQ32::ZERO || abs_fixed(path.contribution)? > FixedQ32::ONE
            {
                return Err(EngramErrorV1::ScoreOutOfRange(
                    "activation_path_contribution",
                ));
            }
            if !path_keys.insert((
                path.source_node_id.clone(),
                path.target_node_id.clone(),
                path.relation,
            )) {
                return Err(EngramErrorV1::DuplicateSynapse);
            }
            if let Some(left) = previous_path
                && !activation_path_before(left, path)
            {
                return Err(EngramErrorV1::NonCanonical("activation_paths"));
            }
            previous_path = Some(path);
        }

        if !strictly_sorted_unique(&self.selected_support) {
            return Err(EngramErrorV1::NonCanonical("selected_support"));
        }
        if self
            .selected_support
            .iter()
            .any(|support| !active_support.contains(support))
        {
            return Err(EngramErrorV1::NonCanonical("selected_support"));
        }
        if !strictly_sorted_unique(&self.contradictions) {
            return Err(EngramErrorV1::NonCanonical("contradictions"));
        }
        if self.contradictions.iter().any(|contradiction| {
            contradiction.left_node_id == contradiction.right_node_id
                || !active_ids.contains(&contradiction.left_node_id)
                || !active_ids.contains(&contradiction.right_node_id)
        }) {
            return Err(EngramErrorV1::NonCanonical("contradictions"));
        }
        if self.authority.grants_any() {
            return Err(EngramErrorV1::AuthorityGranted);
        }
        self.resources.validate()?;
        if self.resources.settling_steps != self.settling_steps
            || usize::try_from(self.resources.active_nodes).unwrap_or(usize::MAX)
                != self.active_nodes.len()
            || usize::try_from(self.resources.expanded_nodes).unwrap_or(0) < self.active_nodes.len()
            || usize::try_from(self.resources.candidate_records).unwrap_or(0)
                < self.selected_support.len()
        {
            return Err(EngramErrorV1::NonCanonical("engram_resources"));
        }
        let expected_coverage = ratio_probability(
            self.selected_support.len(),
            usize::try_from(self.resources.candidate_records)
                .map_err(|_| EngramErrorV1::Arithmetic)?,
        )?;
        if self.coverage != expected_coverage {
            return Err(EngramErrorV1::NonCanonical("engram_coverage"));
        }
        if self.confidence != active_confidence(&self.active_nodes)? {
            return Err(EngramErrorV1::NonCanonical("engram_confidence"));
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(EngramErrorV1::DigestMismatch("engram_recall"));
        }
        Ok(())
    }

    pub(crate) fn support_strength(
        &self,
        record_id: &StableId,
        record_revision: Revision,
    ) -> Option<FixedQ32> {
        self.active_nodes
            .iter()
            .filter(|node| {
                node.support.iter().any(|support| {
                    &support.record_id == record_id && support.record_revision == record_revision
                })
            })
            .map(|node| node.activation)
            .max()
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(ENGRAM_RECALL_DOMAIN);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_digest(&mut bytes, self.engram_snapshot_digest);
        push_digest(&mut bytes, self.dynamics_policy_digest);
        push_u64(&mut bytes, self.coverage.raw());
        push_u64(&mut bytes, self.confidence.raw());
        bytes.push(self.settling_steps);
        push_digest(&mut bytes, self.resources.receipt_digest);
        push_len(&mut bytes, self.active_nodes.len());
        for node in &self.active_nodes {
            push_id(&mut bytes, &node.node_id);
            bytes.push(population_code(node.population));
            push_i64(&mut bytes, node.activation.raw());
            push_u64(&mut bytes, node.confidence.raw());
            push_len(&mut bytes, node.support.len());
            for support in &node.support {
                push_id(&mut bytes, &support.record_id);
                push_u64(&mut bytes, support.record_revision.get());
            }
        }
        push_len(&mut bytes, self.activation_paths.len());
        for path in &self.activation_paths {
            push_id(&mut bytes, &path.source_node_id);
            push_id(&mut bytes, &path.target_node_id);
            bytes.push(relation_code(path.relation));
            push_i64(&mut bytes, path.contribution.raw());
        }
        push_len(&mut bytes, self.contradictions.len());
        for contradiction in &self.contradictions {
            push_id(&mut bytes, &contradiction.left_node_id);
            push_id(&mut bytes, &contradiction.right_node_id);
        }
        push_len(&mut bytes, self.selected_support.len());
        for support in &self.selected_support {
            push_id(&mut bytes, &support.record_id);
            push_u64(&mut bytes, support.record_revision.get());
        }
        Digest32::of_bytes(&bytes)
    }
}

pub fn settle_engram(
    cue: &MemoryCueV1,
    union: &CandidateUnionV1,
    snapshot: &EngramSnapshotV1,
    policy: &EngramDynamicsPolicyV1,
) -> Result<EngramRecallReceiptV1, EngramErrorV1> {
    cue.validate().map_err(EngramErrorV1::Recall)?;
    union.validate().map_err(EngramErrorV1::Recall)?;
    snapshot.validate()?;
    policy.validate()?;
    if cue.snapshot_key.vector_digest != union.generation_vector_digest
        || cue.snapshot_key.vector_digest != snapshot.generation_vector_digest
    {
        return Err(EngramErrorV1::GenerationMismatch);
    }
    if snapshot.nodes.len() > usize::try_from(policy.maximum_nodes).unwrap_or(usize::MAX)
        || snapshot.synapses.len() > usize::try_from(policy.maximum_synapses).unwrap_or(usize::MAX)
    {
        return Err(EngramErrorV1::PolicyBoundExceeded);
    }

    let candidate_scores = union
        .entries
        .iter()
        .map(|entry| {
            (
                EngramSupportV1 {
                    record_id: entry.record.record_id.clone(),
                    record_revision: entry.record.revision,
                },
                entry.weighted_score,
            )
        })
        .collect::<BTreeMap<_, _>>();

    let node_map = snapshot
        .nodes
        .iter()
        .map(|node| (node.node_id.clone(), node))
        .collect::<BTreeMap<_, _>>();
    let seeds = snapshot
        .nodes
        .iter()
        .filter(|node| {
            node.support
                .iter()
                .any(|support| candidate_scores.contains_key(support))
        })
        .map(|node| node.node_id.clone())
        .collect::<BTreeSet<_>>();
    if seeds.is_empty() {
        return empty_receipt(union, snapshot, policy);
    }

    let expanded = expand_nodes(snapshot, &node_map, &seeds, policy)?;
    let mut direct = BTreeMap::new();
    for node_id in &expanded {
        let node = node_map
            .get(node_id)
            .copied()
            .ok_or(EngramErrorV1::MissingNode)?;
        let drive = node
            .support
            .iter()
            .filter_map(|support| candidate_scores.get(support).copied())
            .try_fold(FixedQ32::ZERO, |acc, value| {
                acc.checked_add(value)
                    .map_err(|_| EngramErrorV1::Arithmetic)
            })?
            .clamp(FixedQ32::ZERO, FixedQ32::ONE)
            .map_err(|_| EngramErrorV1::Arithmetic)?;
        direct.insert(node_id.clone(), drive);
    }

    let mut activation = expanded
        .iter()
        .map(|node_id| (node_id.clone(), FixedQ32::ZERO))
        .collect::<BTreeMap<_, _>>();
    let mut incoming_synapses = BTreeMap::new();
    for synapse in &snapshot.synapses {
        if synapse.weight != FixedQ32::ZERO
            && expanded.contains(&synapse.source_node_id)
            && expanded.contains(&synapse.target_node_id)
        {
            incoming_synapses
                .entry(synapse.target_node_id.clone())
                .or_insert_with(Vec::new)
                .push(synapse);
        }
    }

    let mut last_paths = Vec::new();
    let mut traversed_synapses = 0_usize;
    for _step in 0..policy.maximum_settling_steps {
        let mut raw = BTreeMap::new();
        let mut paths = Vec::new();
        for node_id in &expanded {
            let node = node_map
                .get(node_id)
                .copied()
                .ok_or(EngramErrorV1::MissingNode)?;
            let previous = activation.get(node_id).copied().unwrap_or(FixedQ32::ZERO);
            let mut value = direct
                .get(node_id)
                .copied()
                .unwrap_or(FixedQ32::ZERO)
                .checked_add(
                    previous
                        .checked_mul(policy.leak)
                        .map_err(|_| EngramErrorV1::Arithmetic)?,
                )
                .and_then(|value| value.checked_sub(node.threshold))
                .map_err(|_| EngramErrorV1::Arithmetic)?;
            for synapse in incoming_synapses
                .get(node_id)
                .into_iter()
                .flat_map(|synapses| synapses.iter().copied())
            {
                traversed_synapses = traversed_synapses
                    .checked_add(1)
                    .ok_or(EngramErrorV1::Arithmetic)?;
                let source = activation
                    .get(&synapse.source_node_id)
                    .copied()
                    .unwrap_or(FixedQ32::ZERO);
                if source <= FixedQ32::ZERO {
                    continue;
                }
                let magnitude = source
                    .checked_mul(abs_fixed(synapse.weight)?)
                    .map_err(|_| EngramErrorV1::Arithmetic)?;
                let negative = synapse.relation.negative() || synapse.weight < FixedQ32::ZERO;
                let contribution = if negative {
                    FixedQ32::ZERO
                        .checked_sub(magnitude)
                        .map_err(|_| EngramErrorV1::Arithmetic)?
                } else {
                    magnitude
                };
                value = value
                    .checked_add(contribution)
                    .map_err(|_| EngramErrorV1::Arithmetic)?;
                if contribution != FixedQ32::ZERO {
                    paths.push(EngramActivationPathV1 {
                        source_node_id: synapse.source_node_id.clone(),
                        target_node_id: synapse.target_node_id.clone(),
                        relation: synapse.relation,
                        contribution,
                    });
                }
            }
            raw.insert(
                node_id.clone(),
                value
                    .clamp(FixedQ32::ZERO, FixedQ32::ONE)
                    .map_err(|_| EngramErrorV1::Arithmetic)?,
            );
        }
        activation = sparse_select(&raw, &node_map, policy)?;
        last_paths = paths;
    }

    let mut active_nodes = activation
        .iter()
        .filter_map(|(node_id, activation)| {
            (*activation > FixedQ32::ZERO && *activation >= policy.minimum_activation)
                .then_some((node_id, activation))
        })
        .map(|(node_id, activation)| {
            let node = node_map
                .get(node_id)
                .copied()
                .ok_or(EngramErrorV1::MissingNode)?;
            Ok(ActiveEngramNodeV1 {
                node_id: node_id.clone(),
                population: node.population,
                activation: *activation,
                confidence: node.confidence,
                support: node.support.clone(),
            })
        })
        .collect::<Result<Vec<_>, EngramErrorV1>>()?;
    active_nodes.sort_by(|left, right| {
        right
            .activation
            .cmp(&left.activation)
            .then_with(|| left.node_id.cmp(&right.node_id))
    });
    active_nodes.truncate(usize::try_from(policy.maximum_active_nodes).unwrap_or(usize::MAX));
    let active_ids = active_nodes
        .iter()
        .map(|node| node.node_id.clone())
        .collect::<BTreeSet<_>>();

    let mut activation_paths = last_paths
        .into_iter()
        .filter(|path| {
            active_ids.contains(&path.source_node_id) && active_ids.contains(&path.target_node_id)
        })
        .collect::<Vec<_>>();
    activation_paths.sort_by(|left, right| {
        abs_raw(right.contribution.raw())
            .cmp(&abs_raw(left.contribution.raw()))
            .then_with(|| left.source_node_id.cmp(&right.source_node_id))
            .then_with(|| left.target_node_id.cmp(&right.target_node_id))
            .then_with(|| left.relation.cmp(&right.relation))
    });
    activation_paths.dedup_by(|left, right| {
        left.source_node_id == right.source_node_id
            && left.target_node_id == right.target_node_id
            && left.relation == right.relation
    });
    activation_paths
        .truncate(usize::try_from(policy.maximum_activation_paths).unwrap_or(usize::MAX));

    let contradictions = snapshot
        .synapses
        .iter()
        .filter(|synapse| {
            synapse.relation == SynapseRelationV1::Contradicts
                && synapse.weight != FixedQ32::ZERO
                && active_ids.contains(&synapse.source_node_id)
                && active_ids.contains(&synapse.target_node_id)
        })
        .map(|synapse| {
            let (left_node_id, right_node_id) = if synapse.source_node_id <= synapse.target_node_id
            {
                (
                    synapse.source_node_id.clone(),
                    synapse.target_node_id.clone(),
                )
            } else {
                (
                    synapse.target_node_id.clone(),
                    synapse.source_node_id.clone(),
                )
            };
            EngramContradictionV1 {
                left_node_id,
                right_node_id,
            }
        })
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();

    let selected_support = active_nodes
        .iter()
        .flat_map(|node| node.support.iter().cloned())
        .filter(|support| candidate_scores.contains_key(support))
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    let coverage = ratio_probability(selected_support.len(), candidate_scores.len())?;
    let confidence = active_confidence(&active_nodes)?;
    let mut resources = EngramResourceReceiptV1 {
        candidate_records: u32::try_from(union.entries.len()).unwrap_or(u32::MAX),
        expanded_nodes: u32::try_from(expanded.len()).unwrap_or(u32::MAX),
        traversed_synapses: u32::try_from(traversed_synapses).unwrap_or(u32::MAX),
        active_nodes: u32::try_from(active_nodes.len()).unwrap_or(u32::MAX),
        settling_steps: policy.maximum_settling_steps,
        receipt_digest: Digest32::ZERO,
    };
    resources.receipt_digest = resources.compute_digest();
    let mut receipt = EngramRecallReceiptV1 {
        generation_vector_digest: snapshot.generation_vector_digest,
        engram_snapshot_digest: snapshot.snapshot_digest,
        dynamics_policy_digest: policy.digest(),
        active_nodes,
        activation_paths,
        contradictions,
        selected_support,
        coverage,
        confidence,
        settling_steps: policy.maximum_settling_steps,
        resources,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    receipt.validate()?;
    Ok(receipt)
}

fn build_admitted_union(
    full: &CandidateUnionV1,
    admitted: &[&CandidateUnionEntryV1],
) -> Result<CandidateUnionV1, RecallErrorV1> {
    let entries = admitted
        .iter()
        .map(|entry| (*entry).clone())
        .collect::<Vec<_>>();
    let distinct_channels = entries
        .iter()
        .flat_map(|entry| entry.channels.iter().copied())
        .collect::<BTreeSet<_>>()
        .len();
    let mut value = CandidateUnionV1 {
        cue_digest: full.cue_digest,
        policy_digest: full.policy_digest,
        generation_vector_digest: full.generation_vector_digest,
        entries,
        distinct_channels: u32::try_from(distinct_channels).unwrap_or(u32::MAX),
        omitted_by_channel_limits: full.omitted_by_channel_limits,
        union_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    value.union_digest = value.compute_union_digest();
    value.validate()?;
    Ok(value)
}

pub fn recall_with_engram(
    cue: &MemoryCueV1,
    retrieval_policy: &RetrievalPolicyV1,
    candidates: Vec<RetrievalChannelCandidateV1>,
    engram_snapshot: &EngramSnapshotV1,
    dynamics_policy: &EngramDynamicsPolicyV1,
) -> Result<RecallPacketV1, EngramErrorV1> {
    cue.validate().map_err(EngramErrorV1::Recall)?;
    retrieval_policy.validate().map_err(EngramErrorV1::Recall)?;
    let union =
        build_candidate_union(cue, retrieval_policy, candidates).map_err(EngramErrorV1::Recall)?;
    let score_admitted = score_admitted_entries(&union.entries, retrieval_policy);
    let admitted = risk_admitted_entries(&score_admitted, retrieval_policy);
    let admitted_union = build_admitted_union(&union, &admitted).map_err(EngramErrorV1::Recall)?;
    let engram = settle_engram(cue, &admitted_union, engram_snapshot, dynamics_policy)?;

    let minimum_channels =
        usize::try_from(retrieval_policy.minimum_distinct_channels).unwrap_or(usize::MAX);
    let admitted_channels = admitted_distinct_channel_count(&admitted);
    let contradiction =
        !engram.contradictions.is_empty() || contradiction_population_count(&admitted) > 0;
    let reason = if union.entries.is_empty() {
        Some(RecallAbstentionReasonV1::NoCandidate)
    } else if score_admitted.is_empty() {
        Some(RecallAbstentionReasonV1::ScoreBelowFloor)
    } else if admitted.is_empty() {
        Some(RecallAbstentionReasonV1::OutOfDistribution)
    } else if engram.selected_support.is_empty() {
        Some(RecallAbstentionReasonV1::NoCandidate)
    } else if admitted_channels < minimum_channels {
        Some(RecallAbstentionReasonV1::InsufficientChannelCoverage)
    } else if contradiction
        && (retrieval_policy.abstain_on_contradiction
            || dynamics_policy.contradiction_forces_abstention)
    {
        Some(RecallAbstentionReasonV1::ContradictoryEvidence)
    } else {
        None
    };

    let maximum_results = usize::try_from(retrieval_policy.maximum_results).unwrap_or(0);
    let active_strength = active_support_strength(&engram);
    let (disposition, selections, omitted_count) = if let Some(reason) = reason {
        (RecallDispositionV1::Abstained(reason), Vec::new(), 0)
    } else {
        let mut ranked = admitted_union
            .entries
            .iter()
            .filter_map(|entry| {
                let support = support_for_entry(entry);
                let activation = active_strength.get(&support).copied()?;
                Some((entry, activation))
            })
            .collect::<Vec<_>>();
        ranked.sort_by(|(left, left_activation), (right, right_activation)| {
            right_activation
                .cmp(left_activation)
                .then_with(|| right.weighted_score.cmp(&left.weighted_score))
                .then_with(|| left.record.record_id.cmp(&right.record.record_id))
                .then_with(|| left.record.revision.cmp(&right.record.revision))
        });
        let selections = ranked
            .iter()
            .take(maximum_results)
            .map(|(entry, _)| RecallSelectionV1 {
                record_id: entry.record.record_id.clone(),
                record_revision: entry.record.revision,
                record_digest: entry.record.record_digest(),
                weighted_score: entry.weighted_score,
                maximum_ood: entry.maximum_ood,
                channels: entry.channels.clone(),
                support_digests: entry.support_digests.clone(),
                contradiction_evidence: entry.contradiction_evidence.clone(),
            })
            .collect::<Vec<_>>();
        if selections.is_empty() {
            (
                RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ScoreBelowFloor),
                Vec::new(),
                0,
            )
        } else {
            let omitted_count = u32::try_from(union.entries.len().saturating_sub(selections.len()))
                .unwrap_or(u32::MAX);
            (RecallDispositionV1::Recalled, selections, omitted_count)
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
        distinct_channels: u32::try_from(admitted_channels).unwrap_or(u32::MAX),
        engram: Some(engram),
        packet_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    packet.packet_digest = packet.compute_packet_digest();
    packet.validate().map_err(EngramErrorV1::Recall)?;
    Ok(packet)
}

fn empty_receipt(
    union: &CandidateUnionV1,
    snapshot: &EngramSnapshotV1,
    policy: &EngramDynamicsPolicyV1,
) -> Result<EngramRecallReceiptV1, EngramErrorV1> {
    let mut resources = EngramResourceReceiptV1 {
        candidate_records: u32::try_from(union.entries.len()).unwrap_or(u32::MAX),
        expanded_nodes: 0,
        traversed_synapses: 0,
        active_nodes: 0,
        settling_steps: policy.maximum_settling_steps,
        receipt_digest: Digest32::ZERO,
    };
    resources.receipt_digest = resources.compute_digest();
    let mut receipt = EngramRecallReceiptV1 {
        generation_vector_digest: snapshot.generation_vector_digest,
        engram_snapshot_digest: snapshot.snapshot_digest,
        dynamics_policy_digest: policy.digest(),
        active_nodes: Vec::new(),
        activation_paths: Vec::new(),
        contradictions: Vec::new(),
        selected_support: Vec::new(),
        coverage: ProbabilityQ32::ZERO,
        confidence: ProbabilityQ32::ZERO,
        settling_steps: policy.maximum_settling_steps,
        resources,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    receipt.validate()?;
    Ok(receipt)
}

fn expand_nodes(
    snapshot: &EngramSnapshotV1,
    node_map: &BTreeMap<StableId, &EngramNodeV1>,
    seeds: &BTreeSet<StableId>,
    policy: &EngramDynamicsPolicyV1,
) -> Result<BTreeSet<StableId>, EngramErrorV1> {
    let mut selected = seeds.clone();
    let mut frontier = seeds.clone();
    let maximum_nodes = usize::try_from(policy.maximum_nodes).unwrap_or(usize::MAX);
    for _ in 0..policy.maximum_graph_hops {
        if frontier.is_empty() || selected.len() >= maximum_nodes {
            break;
        }
        let mut next = BTreeSet::new();
        for synapse in snapshot
            .synapses
            .iter()
            .filter(|synapse| synapse.weight != FixedQ32::ZERO)
        {
            let mut consider = Vec::new();
            if frontier.contains(&synapse.source_node_id) {
                consider.push(synapse.target_node_id.clone());
            }
            if matches!(
                synapse.relation,
                SynapseRelationV1::Associative | SynapseRelationV1::Contradicts
            ) && frontier.contains(&synapse.target_node_id)
            {
                consider.push(synapse.source_node_id.clone());
            }
            for node_id in consider {
                if selected.len() >= maximum_nodes || selected.contains(&node_id) {
                    continue;
                }
                if !node_map.contains_key(&node_id) {
                    return Err(EngramErrorV1::MissingNode);
                }
                selected.insert(node_id.clone());
                next.insert(node_id);
            }
        }
        frontier = next;
    }
    Ok(selected)
}

fn sparse_select(
    raw: &BTreeMap<StableId, FixedQ32>,
    node_map: &BTreeMap<StableId, &EngramNodeV1>,
    policy: &EngramDynamicsPolicyV1,
) -> Result<BTreeMap<StableId, FixedQ32>, EngramErrorV1> {
    let mut selected = BTreeMap::new();
    let maximum_per_population =
        usize::try_from(policy.maximum_active_per_population).unwrap_or(usize::MAX);
    for population in EngramPopulationV1::ALL {
        let mut group = raw
            .iter()
            .filter_map(|(node_id, value)| {
                node_map
                    .get(node_id)
                    .filter(|node| node.population == population && *value > FixedQ32::ZERO)
                    .map(|_| (node_id.clone(), *value))
            })
            .collect::<Vec<_>>();
        group.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
        group.truncate(maximum_per_population);
        for (rank, (node_id, value)) in group.into_iter().enumerate() {
            let inhibition = scalar_mul(policy.lateral_inhibition, rank)?;
            let inhibited = value
                .checked_sub(inhibition)
                .unwrap_or(FixedQ32::ZERO)
                .clamp(FixedQ32::ZERO, FixedQ32::ONE)
                .map_err(|_| EngramErrorV1::Arithmetic)?;
            selected.insert(node_id, inhibited);
        }
    }
    let mut ranked = selected.into_iter().collect::<Vec<_>>();
    ranked.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
    ranked.truncate(usize::try_from(policy.maximum_active_nodes).unwrap_or(usize::MAX));
    let active = ranked.into_iter().collect::<BTreeMap<_, _>>();
    Ok(raw
        .keys()
        .map(|node_id| {
            (
                node_id.clone(),
                active.get(node_id).copied().unwrap_or(FixedQ32::ZERO),
            )
        })
        .collect())
}

fn active_support_strength(engram: &EngramRecallReceiptV1) -> BTreeMap<EngramSupportV1, FixedQ32> {
    let mut values = BTreeMap::new();
    for node in &engram.active_nodes {
        for support in &node.support {
            values
                .entry(support.clone())
                .and_modify(|current| {
                    if node.activation > *current {
                        *current = node.activation;
                    }
                })
                .or_insert(node.activation);
        }
    }
    values
}

fn active_confidence(active_nodes: &[ActiveEngramNodeV1]) -> Result<ProbabilityQ32, EngramErrorV1> {
    if active_nodes.is_empty() {
        return Ok(ProbabilityQ32::ZERO);
    }
    let mut activation_total = 0_u128;
    let mut weighted_confidence = 0_u128;
    for node in active_nodes {
        let activation =
            u128::try_from(node.activation.raw()).map_err(|_| EngramErrorV1::Arithmetic)?;
        activation_total = activation_total
            .checked_add(activation)
            .ok_or(EngramErrorV1::Arithmetic)?;
        weighted_confidence = weighted_confidence
            .checked_add(
                activation
                    .checked_mul(u128::from(node.confidence.raw()))
                    .ok_or(EngramErrorV1::Arithmetic)?,
            )
            .ok_or(EngramErrorV1::Arithmetic)?;
    }
    if activation_total == 0 {
        return Err(EngramErrorV1::Arithmetic);
    }
    let raw = weighted_confidence / activation_total;
    ProbabilityQ32::from_raw(u64::try_from(raw).map_err(|_| EngramErrorV1::Arithmetic)?)
        .map_err(|_| EngramErrorV1::Arithmetic)
}

fn ratio_probability(
    numerator: usize,
    denominator: usize,
) -> Result<ProbabilityQ32, EngramErrorV1> {
    if denominator == 0 {
        return Ok(ProbabilityQ32::ZERO);
    }
    let numerator = u128::try_from(numerator).map_err(|_| EngramErrorV1::Arithmetic)?;
    let denominator = u128::try_from(denominator).map_err(|_| EngramErrorV1::Arithmetic)?;
    let raw = numerator
        .checked_mul(u128::from(ProbabilityQ32::ONE.raw()))
        .ok_or(EngramErrorV1::Arithmetic)?
        / denominator;
    ProbabilityQ32::from_raw(u64::try_from(raw).map_err(|_| EngramErrorV1::Arithmetic)?)
        .map_err(|_| EngramErrorV1::Arithmetic)
}

fn support_for_entry(entry: &CandidateUnionEntryV1) -> EngramSupportV1 {
    EngramSupportV1 {
        record_id: entry.record.record_id.clone(),
        record_revision: entry.record.revision,
    }
}

fn contradiction_population_count(entries: &[CandidateUnionEntryV1]) -> usize {
    let mut groups = BTreeMap::<Digest32, usize>::new();
    for entry in entries {
        for group in &entry.contradiction_evidence {
            *groups.entry(*group).or_insert(0) += 1;
        }
    }
    groups.values().filter(|count| **count > 1).count()
}

fn abs_fixed(value: FixedQ32) -> Result<FixedQ32, EngramErrorV1> {
    if value.raw() == i64::MIN {
        return Err(EngramErrorV1::Arithmetic);
    }
    Ok(FixedQ32::from_raw(value.raw().abs()))
}

fn scalar_mul(value: FixedQ32, scalar: usize) -> Result<FixedQ32, EngramErrorV1> {
    let raw = i128::from(value.raw())
        .checked_mul(i128::try_from(scalar).map_err(|_| EngramErrorV1::Arithmetic)?)
        .ok_or(EngramErrorV1::Arithmetic)?;
    Ok(FixedQ32::from_raw(
        i64::try_from(raw).map_err(|_| EngramErrorV1::Arithmetic)?,
    ))
}

fn abs_raw(value: i64) -> u64 {
    value.unsigned_abs()
}

fn activation_path_before(left: &EngramActivationPathV1, right: &EngramActivationPathV1) -> bool {
    let left_magnitude = abs_raw(left.contribution.raw());
    let right_magnitude = abs_raw(right.contribution.raw());
    left_magnitude > right_magnitude
        || (left_magnitude == right_magnitude
            && (left.source_node_id < right.source_node_id
                || (left.source_node_id == right.source_node_id
                    && (left.target_node_id < right.target_node_id
                        || (left.target_node_id == right.target_node_id
                            && left.relation < right.relation)))))
}

fn synapse_key(synapse: &SynapseV1) -> (StableId, StableId, SynapseRelationV1) {
    (
        synapse.source_node_id.clone(),
        synapse.target_node_id.clone(),
        synapse.relation,
    )
}

fn strictly_sorted_unique<T: Ord>(values: &[T]) -> bool {
    values.windows(2).all(|pair| pair[0] < pair[1])
}

fn strictly_sorted_by<T, K: Ord>(values: &[T], key: impl Fn(&T) -> K) -> bool {
    values.windows(2).all(|pair| key(&pair[0]) < key(&pair[1]))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EngramErrorV1 {
    Recall(RecallErrorV1),
    InvalidId(String),
    EmptyDigest(&'static str),
    EmptySupport(String),
    DuplicateNode(String),
    DuplicateSynapse,
    SelfSynapse(String),
    MissingSynapseEndpoint,
    MissingNode,
    GenerationMismatch,
    NonCanonical(&'static str),
    ScoreOutOfRange(&'static str),
    NodeLimitExceeded,
    SynapseLimitExceeded,
    ActivePopulationLimitExceeded,
    ActiveNodeLimitExceeded,
    SettlingStepLimitExceeded,
    GraphHopLimitExceeded,
    ActivationPathLimitExceeded,
    PolicyBoundExceeded,
    AuthorityGranted,
    DigestMismatch(&'static str),
    Arithmetic,
}

impl fmt::Display for EngramErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for EngramErrorV1 {}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_i64(bytes: &mut Vec<u8>, value: i64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

const fn population_code(value: EngramPopulationV1) -> u8 {
    match value {
        EngramPopulationV1::SensoryTrace => 0,
        EngramPopulationV1::EpisodicBinding => 1,
        EngramPopulationV1::SemanticConcept => 2,
        EngramPopulationV1::ProceduralSkill => 3,
        EngramPopulationV1::PredictiveWorld => 4,
        EngramPopulationV1::UtilitySalience => 5,
        EngramPopulationV1::MetaMemory => 6,
    }
}

const fn relation_code(value: SynapseRelationV1) -> u8 {
    match value {
        SynapseRelationV1::Associative => 0,
        SynapseRelationV1::Temporal => 1,
        SynapseRelationV1::Causal => 2,
        SynapseRelationV1::Procedural => 3,
        SynapseRelationV1::Predictive => 4,
        SynapseRelationV1::Supports => 5,
        SynapseRelationV1::Inhibitory => 6,
        SynapseRelationV1::Contradicts => 7,
    }
}

#[cfg(test)]
#[path = "engram_tests.rs"]
mod tests;
