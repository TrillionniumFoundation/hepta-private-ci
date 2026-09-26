//! Host-owned signed terminal outcome handoff.
//!
//! A physical driver cannot synthesize learning evidence from a terminal phase.
//! An independently authenticated observer registers the exact append request in
//! process; the run owner consumes it once when the matching run becomes terminal.

use std::collections::BTreeMap;
use std::sync::Mutex;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdIntelligenceOutcomeAppendV1;
use crate::AgentdIntelligenceObservabilityV1;
use crate::AgentdIntelligenceLearningErrorV1;

pub const MAX_PENDING_INTELLIGENCE_OUTCOMES: usize = 256;

struct PendingOutcomeV1 {
    semantic_digest: Digest32,
    request: AgentdIntelligenceOutcomeAppendV1,
}

pub struct RegisteredAgentdIntelligenceOutcomeProviderV1 {
    pending: Mutex<BTreeMap<StableId, PendingOutcomeV1>>,
    observability: std::sync::Arc<AgentdIntelligenceObservabilityV1>,
}

impl RegisteredAgentdIntelligenceOutcomeProviderV1 {
    pub fn new(observability: std::sync::Arc<AgentdIntelligenceObservabilityV1>) -> Self {
        Self {
            pending: Mutex::new(BTreeMap::new()),
            observability,
        }
    }

    pub fn register(
        &self,
        request: AgentdIntelligenceOutcomeAppendV1,
    ) -> Result<(), AgentdIntelligenceLearningErrorV1> {
        if request.run_id != request.outcome.record_id
            || request.expected_predecessor.is_zero()
            || request.run_snapshot_digest.is_zero()
            || request.decision_digest.is_zero()
        {
            return Err(AgentdIntelligenceLearningErrorV1::Binding);
        }
        let semantic_digest = semantic_digest(&request);
        let mut pending = self
            .pending
            .lock()
            .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?;
        if let Some(existing) = pending.get(&request.run_id) {
            if existing.semantic_digest == semantic_digest {
                return Ok(());
            }
            return Err(AgentdIntelligenceLearningErrorV1::Binding);
        }
        if pending.len() >= MAX_PENDING_INTELLIGENCE_OUTCOMES {
            return Err(AgentdIntelligenceLearningErrorV1::Binding);
        }
        pending.insert(
            request.run_id.clone(),
            PendingOutcomeV1 {
                semantic_digest,
                request,
            },
        );
        self.observability.set_provider_state(true, pending.len());
        Ok(())
    }

    pub fn take(
        &self,
        run_id: &StableId,
    ) -> Result<AgentdIntelligenceOutcomeAppendV1, AgentdIntelligenceLearningErrorV1> {
        let mut pending = self
            .pending
            .lock()
            .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?;
        let request = pending
            .remove(run_id)
            .ok_or(AgentdIntelligenceLearningErrorV1::Binding)?
            .request;
        self.observability.set_provider_state(true, pending.len());
        Ok(request)
    }

    pub fn pending_count(&self) -> Result<usize, AgentdIntelligenceLearningErrorV1> {
        Ok(self
            .pending
            .lock()
            .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?
            .len())
    }
}

fn semantic_digest(request: &AgentdIntelligenceOutcomeAppendV1) -> Digest32 {
    let mut bytes = b"hepta.agentd.intelligence-outcome-handoff.v1\0".to_vec();
    bytes.extend_from_slice(request.expected_predecessor.as_array());
    bytes.extend_from_slice(request.run_id.as_str().as_bytes());
    bytes.extend_from_slice(request.run_snapshot_digest.as_array());
    bytes.extend_from_slice(request.decision_digest.as_array());
    bytes.extend_from_slice(request.selected_candidate_id.as_str().as_bytes());
    bytes.extend_from_slice(request.outcome.record_id.as_str().as_bytes());
    bytes.extend_from_slice(request.outcome.outcome_id.as_str().as_bytes());
    bytes.extend_from_slice(request.outcome.episode_id.as_str().as_bytes());
    bytes.extend_from_slice(request.outcome.support_digest.as_array());
    bytes.extend_from_slice(request.evidence.payload_digest.as_array());
    bytes.extend_from_slice(&request.evidence.signature);
    Digest32::of_bytes(&bytes)
}
