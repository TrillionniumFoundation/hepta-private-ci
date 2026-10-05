//! Host-owned currentness for generation-bound memory retrieval.
//!
//! Context content, publication lifecycle and delivery policy are different
//! identities. The named Agentd caller acquires all three from host composition;
//! request data cannot select a treatment arm or enlarge a shadow budget.

use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::memory::RetrievalExecutionContextV1;
use codex_hepta_agent_components::memory_retrieval::MAX_ENGRAM_NODES;
use codex_hepta_agent_components::memory_retrieval::MAX_ENGRAM_SETTLING_STEPS;
use codex_hepta_agent_components::memory_retrieval::MAX_ENGRAM_SYNAPSES;
use codex_hepta_agent_components::memory_retrieval::MAX_GENERATION_BOUND_CANDIDATES;
use codex_hepta_agent_components::types::Digest32;

const DEFAULT_CANARY_THRESHOLD_PPM: u32 = 50_000;
const DEFAULT_CANARY_COHORT_DOMAIN: &[u8] = b"hepta.retrieval.default-canary-cohort.v1";

/// Read capability supplied by trusted host composition, not by request data.
/// Implementations authenticate their current owner independently, bind all
/// blocking I/O, and fail closed on expiry, rollback or revocation. This port
/// cannot publish, renew, rotate or revoke another owner's state.
pub trait CurrentMemoryRetrievalContext: Send + Sync {
    /// Delivery arm is fixed by the host. Shadow observations are not exposure.
    fn delivers_hnmf(&self, _owner: &AgentId) -> bool {
        true
    }

    /// Version 1 preserves the historical fixed five-percent cohort. Version 2
    /// uses the protected descriptor ppm/salt policy.
    fn canary_policy_version(&self) -> u8 {
        1
    }

    /// Host-owned canary allocation. One million means every owner; zero means
    /// no owner. Product bootstrap v2 overrides this only from a pinned,
    /// protected descriptor.
    fn canary_threshold_ppm(&self) -> u32 {
        DEFAULT_CANARY_THRESHOLD_PPM
    }

    /// Salt is part of the rollout identity so an owner cohort cannot be
    /// silently reused across independent policy generations.
    fn canary_cohort_salt(&self) -> Digest32 {
        Digest32::of_bytes(DEFAULT_CANARY_COHORT_DOMAIN)
    }

    /// Shadow evaluation has a separate structural budget. Exceeding it skips
    /// shadow work and preserves compatibility delivery; canary/required
    /// delivery continues to use the independently validated product limits.
    fn shadow_maximum_channel_candidates(&self) -> u32 {
        u32::try_from(MAX_GENERATION_BOUND_CANDIDATES).unwrap_or(u32::MAX)
    }

    fn shadow_maximum_nodes(&self) -> usize {
        MAX_ENGRAM_NODES
    }

    fn shadow_maximum_synapses(&self) -> usize {
        MAX_ENGRAM_SYNAPSES
    }

    fn shadow_maximum_settling_steps(&self) -> u8 {
        MAX_ENGRAM_SETTLING_STEPS
    }

    fn current(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<RetrievalExecutionContextV1, String>;

    /// Acquire within the request's existing absolute budget. Custom providers
    /// must override this to pass the deadline to blocking transports. The
    /// compatibility default rejects expired/late results but cannot preempt I/O.
    fn acquire_context_before(
        &self,
        owner: &AgentId,
        body_generation: u64,
        deadline: std::time::Instant,
    ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
        check_retrieval_deadline(deadline)?;
        let result = self.acquire_context(owner, body_generation)?;
        check_retrieval_deadline(deadline)?;
        Ok(result)
    }

    /// Atomically return payload, lifecycle binding and absolute lease deadline.
    /// The binding must cover the payload AND publication epoch/sequence/lease.
    /// Separate current/epoch/deadline reads are not an atomic observation.
    /// The legacy default preserves the prior payload-only host contract; None
    /// is explicitly NOT evidence of a signed product lease.
    fn acquire_context(
        &self,
        owner: &AgentId,
        body_generation: u64,
    ) -> Result<(RetrievalExecutionContextV1, Digest32, Option<u64>), String> {
        let context = self.current(owner, body_generation)?;
        context.validate().map_err(|error| error.to_string())?;
        let binding = context.binding_digest();
        Ok((context, binding, None))
    }
}

/// Expiry cannot be renewed by moving to another stage or provider operation.
pub(crate) fn check_retrieval_deadline(deadline: std::time::Instant) -> Result<(), String> {
    if std::time::Instant::now() >= deadline {
        Err("retrieval provider request deadline exceeded".to_string())
    } else {
        Ok(())
    }
}
