//! Explicit host composition for the generation-bound memory retrieval engine.
//!
//! The runtime never invents external generations. A trusted host supplies a
//! current profile containing the full Lane C generation vector, retrieval
//! policy, engram and dynamics. Agentd verifies the cognitive-owned portion
//! against the canonical SQLite cut and revalidates the profile before return.

use std::sync::Arc;

use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_memory::DurableCognitiveSnapshot;
use codex_hepta_memory::RetrievalObservation;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_memory_retrieval::CandidateUnionBuildV1;
use codex_hepta_memory_retrieval::EngramSnapshotV1;
use codex_hepta_memory_retrieval::HnmfRecallReceiptV1;
use codex_hepta_memory_retrieval::RecallDynamicsV1;
use codex_hepta_memory_retrieval::RetrievalPolicyV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryRetrievalCandidateKeyV1 {
    pub record_id: String,
    pub revision: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryRetrievalPreparationV1 {
    pub owner_agent_id: AgentId,
    pub body_generation: u64,
    pub query_digest: Digest32,
    pub scope_id: StableId,
    pub owner_cut_digest: Digest32,
    pub memory_ledger_frontier: u64,
    pub source_ledger_frontier: u64,
    pub tombstone_frontier: u64,
    pub knowledge_fact_frontier: u64,
    pub knowledge_graph_generation: Generation,
    pub candidates: Vec<MemoryRetrievalCandidateKeyV1>,
}

impl MemoryRetrievalPreparationV1 {
    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.agentd.memory-retrieval-preparation.v1".to_vec();
        push_bytes(&mut bytes, self.owner_agent_id.as_str().as_bytes());
        bytes.extend_from_slice(&self.body_generation.to_be_bytes());
        bytes.extend_from_slice(self.query_digest.as_array());
        push_bytes(&mut bytes, self.scope_id.as_str().as_bytes());
        bytes.extend_from_slice(self.owner_cut_digest.as_array());
        for value in [
            self.memory_ledger_frontier,
            self.source_ledger_frontier,
            self.tombstone_frontier,
            self.knowledge_fact_frontier,
            self.knowledge_graph_generation.get(),
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(
            &u64::try_from(self.candidates.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        for candidate in &self.candidates {
            push_bytes(&mut bytes, candidate.record_id.as_bytes());
            bytes.extend_from_slice(&candidate.revision.to_be_bytes());
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryRetrievalProfileV1 {
    pub vector: LaneCGenerationVectorV1,
    pub cue_id: StableId,
    pub objective_digest: Digest32,
    pub approved_context_digest: Digest32,
    pub cue_profile_digest: Digest32,
    pub policy: RetrievalPolicyV1,
    pub engram: EngramSnapshotV1,
    pub dynamics: RecallDynamicsV1,
}

impl MemoryRetrievalProfileV1 {
    pub fn validate(
        &self,
        preparation: &MemoryRetrievalPreparationV1,
    ) -> Result<CognitiveSnapshotKeyV1, String> {
        if self.vector.scope_id != preparation.scope_id
            || self.vector.memory_ledger_frontier != preparation.memory_ledger_frontier
            || self.vector.source_ledger_frontier != preparation.source_ledger_frontier
            || self.vector.tombstone_frontier != preparation.tombstone_frontier
            || self.vector.knowledge_fact_frontier != preparation.knowledge_fact_frontier
            || self.vector.knowledge_graph_generation != preparation.knowledge_graph_generation
        {
            return Err("retrieval profile does not match canonical owner cut".to_string());
        }
        for (label, digest) in [
            ("objective", self.objective_digest),
            ("approved_context", self.approved_context_digest),
            ("cue_profile", self.cue_profile_digest),
        ] {
            if digest.is_zero() {
                return Err(format!("retrieval profile has empty {label} digest"));
            }
        }
        self.policy.validate().map_err(|error| error.to_string())?;
        self.engram.validate().map_err(|error| error.to_string())?;
        self.dynamics.validate().map_err(|error| error.to_string())?;
        let snapshot_key =
            CognitiveSnapshotKeyV1::new(self.vector.clone()).map_err(|error| error.to_string())?;
        if self.engram.generation_vector_digest != snapshot_key.vector_digest {
            return Err("engram generation differs from retrieval generation".to_string());
        }
        Ok(snapshot_key)
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let snapshot = CognitiveSnapshotKeyV1::new(self.vector.clone());
        let vector_digest = snapshot
            .map(|value| value.vector_digest)
            .unwrap_or(Digest32::ZERO);
        let mut bytes = b"hepta.agentd.memory-retrieval-profile.v1".to_vec();
        bytes.extend_from_slice(vector_digest.as_array());
        push_bytes(&mut bytes, self.cue_id.as_str().as_bytes());
        bytes.extend_from_slice(self.objective_digest.as_array());
        bytes.extend_from_slice(self.approved_context_digest.as_array());
        bytes.extend_from_slice(self.cue_profile_digest.as_array());
        bytes.extend_from_slice(self.policy.digest().as_array());
        bytes.extend_from_slice(self.engram.digest().as_array());
        bytes.extend_from_slice(self.dynamics.digest().as_array());
        Digest32::of_bytes(&bytes)
    }
}

pub trait CurrentMemoryRetrievalProfile: Send + Sync {
    fn current(
        &self,
        preparation: &MemoryRetrievalPreparationV1,
    ) -> Result<MemoryRetrievalProfileV1, String>;
}

pub trait MemoryRetrievalDecisionSink: Send + Sync {
    /// Append through the learning.ledger owner. The returned digest must bind
    /// the committed append/receipt; the retrieval runtime owns no ledger.
    fn append_decision(&self, decision: EpisodeDecision) -> Result<Digest32, String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedMemoryRetrievalV1 {
    pub preparation: MemoryRetrievalPreparationV1,
    pub profile: MemoryRetrievalProfileV1,
    pub preparation_digest: Digest32,
    pub profile_digest: Digest32,
}

pub struct PinnedMemoryRetrievalRuntime {
    owner: AgentId,
    body_generation: u64,
    current: Arc<dyn CurrentMemoryRetrievalProfile>,
    decision_sink: Arc<dyn MemoryRetrievalDecisionSink>,
}

impl PinnedMemoryRetrievalRuntime {
    pub fn new(
        owner: AgentId,
        body_generation: u64,
        current: Arc<dyn CurrentMemoryRetrievalProfile>,
        decision_sink: Arc<dyn MemoryRetrievalDecisionSink>,
    ) -> Result<Self, String> {
        if body_generation == 0 {
            return Err("memory retrieval runtime requires a non-zero body generation".to_string());
        }
        Ok(Self {
            owner,
            body_generation,
            current,
            decision_sink,
        })
    }

    pub fn require_identity(&self, owner: &AgentId, body_generation: u64) -> Result<(), String> {
        if owner != &self.owner || body_generation != self.body_generation {
            return Err("memory retrieval runtime belongs to another agent generation".to_string());
        }
        Ok(())
    }

    pub fn prepare(
        &self,
        owner: &AgentId,
        body_generation: u64,
        query: &str,
        cut: &DurableCognitiveSnapshot,
        observation: &RetrievalObservation,
    ) -> Result<PreparedMemoryRetrievalV1, String> {
        self.require_identity(owner, body_generation)?;
        if query.is_empty() || query.len() > 2048 {
            return Err("memory retrieval query outside bounded host profile".to_string());
        }
        let frontiers = cut.frontiers();
        let mut candidates = observation
            .materialized_candidates()
            .iter()
            .map(|candidate| MemoryRetrievalCandidateKeyV1 {
                record_id: candidate.memory.id.memory_id.as_str().to_string(),
                revision: candidate.memory.id.revision,
            })
            .collect::<Vec<_>>();
        candidates.sort_by(|left, right| {
            left.record_id
                .cmp(&right.record_id)
                .then_with(|| left.revision.cmp(&right.revision))
        });
        candidates.dedup();

        let preparation = MemoryRetrievalPreparationV1 {
            owner_agent_id: owner.clone(),
            body_generation,
            query_digest: Digest32::of_bytes(query.as_bytes()),
            scope_id: cut.scope_id().clone(),
            owner_cut_digest: cut.cut_digest(),
            memory_ledger_frontier: frontiers.memory,
            source_ledger_frontier: frontiers.source,
            tombstone_frontier: frontiers.tombstone,
            knowledge_fact_frontier: frontiers.knowledge_facts,
            knowledge_graph_generation: frontiers.knowledge_graph,
            candidates,
        };
        let profile = self.current.current(&preparation)?;
        profile.validate(&preparation)?;
        let preparation_digest = preparation.digest();
        let profile_digest = profile.digest();
        Ok(PreparedMemoryRetrievalV1 {
            preparation,
            profile,
            preparation_digest,
            profile_digest,
        })
    }

    pub fn revalidate(&self, prepared: &PreparedMemoryRetrievalV1) -> Result<(), String> {
        let current = self.current.current(&prepared.preparation)?;
        current.validate(&prepared.preparation)?;
        if prepared.preparation.digest() != prepared.preparation_digest
            || current.digest() != prepared.profile_digest
        {
            return Err("memory retrieval profile changed during request".to_string());
        }
        Ok(())
    }

    pub fn record_decision(
        &self,
        prepared: &PreparedMemoryRetrievalV1,
        built: &CandidateUnionBuildV1,
        receipt: &HnmfRecallReceiptV1,
        selected_identity: Option<(String, u64)>,
    ) -> Result<Digest32, String> {
        if !built.all_enabled_channels_exhausted {
            return Err("incomplete retrieval coverage cannot be logged as a causal decision".to_string());
        }
        built.validate().map_err(|error| error.to_string())?;
        receipt.validate().map_err(|error| error.to_string())?;
        if receipt.packet.candidate_union_digest != built.union.union_digest {
            return Err("recall packet does not bind the logged candidate union".to_string());
        }

        let mut candidate_ids = built
            .union
            .entries
            .iter()
            .map(|entry| retrieval_candidate_id(&entry.record.record_id, entry.record.revision.get()))
            .collect::<Result<Vec<_>, _>>()?;
        candidate_ids.push(StableId::new("abstain").map_err(|error| error.to_string())?);
        candidate_ids.sort();
        if candidate_ids.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err("retrieval candidate identity collision".to_string());
        }

        let selected_candidate_id = match selected_identity {
            Some((record_id, revision)) => {
                let record_id = StableId::new(record_id).map_err(|error| error.to_string())?;
                let candidate_id = retrieval_candidate_id(&record_id, revision)?;
                if !candidate_ids.contains(&candidate_id) {
                    return Err("selected retrieval identity is outside the complete legal set".to_string());
                }
                candidate_id
            }
            None => StableId::new("abstain").map_err(|error| error.to_string())?,
        };
        let mut support_bytes = b"hepta.memory-retrieval.learning-decision.v1".to_vec();
        support_bytes.extend_from_slice(prepared.preparation_digest.as_array());
        support_bytes.extend_from_slice(prepared.profile_digest.as_array());
        support_bytes.extend_from_slice(built.coverage_digest.as_array());
        support_bytes.extend_from_slice(receipt.receipt_digest.as_array());
        let support_digest = Digest32::of_bytes(&support_bytes);
        let episode_id = digest_stable_id("retrieval-episode", support_digest)?;
        let record_id = digest_stable_id("retrieval-decision", support_digest)?;
        let decision = EpisodeDecision {
            record_id,
            episode_id,
            objective_digest: prepared.profile.objective_digest,
            policy_id: prepared.profile.policy.policy_id.clone(),
            candidate_ids,
            selected_candidate_id,
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompleteness::Complete,
            support_digest,
        };
        self.decision_sink.append_decision(decision)
    }
}

fn retrieval_candidate_id(record_id: &StableId, revision: u64) -> Result<StableId, String> {
    let mut bytes = b"hepta.memory-retrieval.candidate-id.v1".to_vec();
    push_bytes(&mut bytes, record_id.as_str().as_bytes());
    bytes.extend_from_slice(&revision.to_be_bytes());
    digest_stable_id("rc", Digest32::of_bytes(&bytes))
}

fn digest_stable_id(prefix: &str, digest: Digest32) -> Result<StableId, String> {
    // 192 bits keeps a 512-entry decision comfortably below the durable V1
    // 32 KiB event ceiling while retaining a collision-resistant exact-set key.
    let hex = digest.to_string();
    StableId::new(format!("{prefix}-{}", &hex[..48])).map_err(|error| error.to_string())
}

fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value);
}

#[cfg(test)]
#[path = "memory_retrieval_runtime_tests.rs"]
mod tests;
