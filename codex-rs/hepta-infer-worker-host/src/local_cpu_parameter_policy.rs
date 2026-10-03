//! The installed sparse operand profile retains and enforces the complete signed
//! envelope. Its operand path grants no filesystem or owner authority.
use super::*;
use codex_hepta_agentd::CanonicalIterationEnvelopeV1;
use std::collections::BTreeSet;
use std::time::Duration;
use std::time::Instant;

pub const CPU_PARAMETER_OPERAND_V1: &str = "parameters/neuron.sparse.rates.q24.v1";
pub const CPU_PARAMETER_CHECKS_V1: [&str; 6] = [
    "verify_generated_parameter_candidates_v3",
    "apply_sparse_deltas",
    "validate_frozen_model",
    "validate_generation_plan",
    "validate_receipt",
    "original_current_plasticity_final_use_admission",
];
const DENIED_MODEL_AUTHORITIES: [&str; 8] = [
    "runtime",
    "production_writer",
    "model_invocation",
    "provider_dispatch",
    "external_effect",
    "selection",
    "promotion",
    "release",
];

/// The pin comes from the immutable installed descriptor, independently of
/// Generator output. Only this exact sparse operation profile is executable.
pub struct CpuNeuronParameterPolicyV2 {
    envelope: CanonicalIterationEnvelopeV1,
    started: Instant,
}
impl CpuNeuronParameterPolicyV2 {
    pub fn new(
        envelope: CanonicalIterationEnvelopeV1,
        independent_host_pin: Digest32,
    ) -> Result<Self, AgentdError> {
        let policy = envelope.policy();
        let exact = |actual: &[String], expected: &[&str]| {
            let actual: BTreeSet<_> = actual.iter().map(String::as_str).collect();
            actual == expected.iter().copied().collect()
        };
        if independent_host_pin.is_zero()
            || envelope.digest() != independent_host_pin
            || !exact(policy.allowed_paths, &[CPU_PARAMETER_OPERAND_V1])
            || !exact(policy.denied_authorities, &DENIED_MODEL_AUTHORITIES)
            || !exact(policy.mandatory_checks, &CPU_PARAMETER_CHECKS_V1)
        {
            return Err(error(
                "installed sparse policy pin, operand or checks changed",
            ));
        }
        Ok(Self {
            envelope,
            started: Instant::now(),
        })
    }

    pub(super) fn canonical(&self) -> CanonicalIterationEnvelopeV1 {
        self.envelope.clone()
    }

    pub(super) fn remaining(&self) -> Result<Duration, AgentdError> {
        Duration::from_micros(self.envelope.policy().wall_time_micros)
            .checked_sub(self.started.elapsed())
            .filter(|remaining| !remaining.is_zero())
            .ok_or_else(|| error("installed sparse policy wall time exhausted"))
    }

    pub(super) fn check_round(
        &self,
        round: &AgentdSelfIterationRoundV1,
        execution: &IterationEnvelopeV1,
        clock: &dyn AuthorityClock,
    ) -> Result<(), AgentdError> {
        round.canonical_bytes()?;
        let now = clock
            .now_unix_ms()
            .map_err(|value| error(value.to_string()))?;
        if round.canonical_policy_digest() != self.envelope.digest()
            || round.execution_envelope_digest() != self_iteration_envelope_digest_v1(execution)
            || round.candidate_admissions() != u32::from(execution.maximum_candidates)
            || now < round.admitted_at_ms()
            || now >= round.deadline_ms()
            || round.deadline_ms() > self.envelope.policy().expires_unix_ms
        {
            return Err(error(
                "sparse compiler original round, tight quota or deadline changed",
            ));
        }
        self.round_remaining(round, clock)?;
        Ok(())
    }

    pub(super) fn round_remaining(
        &self,
        round: &AgentdSelfIterationRoundV1,
        clock: &dyn AuthorityClock,
    ) -> Result<Duration, AgentdError> {
        let now = clock
            .now_unix_ms()
            .map_err(|value| error(value.to_string()))?;
        let milliseconds = round
            .deadline_ms()
            .checked_sub(now)
            .filter(|remaining| *remaining > 0)
            .ok_or_else(|| error("original sparse round deadline exhausted"))?;
        Ok(self.remaining()?.min(Duration::from_millis(milliseconds)))
    }

    pub(super) fn check_current(
        &self,
        clock: &dyn AuthorityClock,
        resources: &crate::FleetWorkerResourcePortV2,
    ) -> Result<(), AgentdError> {
        self.remaining()?;
        let policy = self.envelope.policy();
        let now = clock
            .now_unix_ms()
            .map_err(|value| error(value.to_string()))?;
        if now >= policy.expires_unix_ms {
            return Err(error("installed sparse policy expired"));
        }
        let current = resources
            .observe_current()
            .map_err(|value| error(value.to_string()))?;
        let allocation = &current.allocation().resources;
        // A larger owner allocation must be bounded by an independently
        // installed policy before this adapter can use it.
        if allocation.memory_bytes > policy.compute_budget.maximum_memory_bytes
            || allocation.tool_processes > u64::from(policy.compute_budget.maximum_processes)
            || allocation.concurrent_turns
                > u64::from(policy.compute_budget.maximum_parallel_sandboxes)
        {
            return Err(error(
                "current original Fleet allocation exceeds sparse policy ceilings",
            ));
        }
        self.remaining()?;
        Ok(())
    }

    pub(super) fn validate_plan(
        &self,
        plan: &CpuNeuronParameterCompilerPlanV2,
        owners: &CpuNeuronParameterCompilerOwnersV2,
    ) -> Result<(), AgentdError> {
        self.check_current(owners.clock.as_ref(), owners.resources.as_ref())?;
        let policy = self.envelope.policy();
        let execution = &plan.envelope;
        if execution.envelope_id.as_str() != policy.envelope_id
            || execution.base_commit != Digest32::of_bytes(policy.base_commit.as_bytes())
            || execution.base_tree != Digest32::of_bytes(policy.base_tree.as_bytes())
            || execution.objective_digest.to_string() != policy.objective_digest
            || execution.grammar_digest.to_string() != policy.grammar_digest
            || u32::from(execution.maximum_files) > policy.maximum_files
            || execution.maximum_diff_bytes > policy.maximum_bytes
            || u32::from(execution.maximum_candidates) > policy.maximum_candidates
            || execution.maximum_parallel_sandboxes
                > policy.compute_budget.maximum_parallel_sandboxes
            || execution.expiry_unix_seconds > policy.expires_unix_ms / 1_000
            || plan.request.generated.candidates.len() != usize::from(execution.maximum_candidates)
            || plan.request.generated.candidates.len() > policy.maximum_candidates as usize
        {
            return Err(error(
                "sparse execution fields differ from complete canonical policy",
            ));
        }
        for worker in plan
            .candidates
            .iter()
            .map(|candidate| &candidate.worker)
            .chain(std::iter::once(&plan.rollback_worker))
        {
            if !Arc::ptr_eq(&worker.resources, &owners.resources)
                || worker.maximum_request_duration > self.remaining()?
            {
                return Err(error(
                    "sparse generation changed original resource owner or deadline",
                ));
            }
        }
        Ok(())
    }

    pub(super) fn check_diff(&self, semantic_diff: &[u8]) -> Result<(), AgentdError> {
        let policy = self.envelope.policy();
        if policy.maximum_files < 1 || semantic_diff.len() as u64 > policy.maximum_bytes {
            return Err(error("actual sparse operand diff exceeds canonical limits"));
        }
        self.remaining()?;
        Ok(())
    }
}

#[cfg(test)]
#[path = "local_cpu_parameter_policy_tests.rs"]
mod tests;
