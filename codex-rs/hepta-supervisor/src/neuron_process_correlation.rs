//! Read-only correlation of selected Neuron module lifecycle with a LIVE Agentd.
//!
//! This call uses the actual in-process Supervisor and its registered process,
//! not a caller-provided "healthy" claim. It is a limited per-Agent diagnostic,
//! not proof of an authenticated CNS route or physical Neuron model loading.
//! The process runtime/spawn generations and Neuron module generation remain
//! distinct domains and are NEVER compared as the same generation.

use codex_hepta_contracts::AgentId;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use thiserror::Error;

use crate::ProcessDriver;
use crate::RuntimeModuleSupervisorErrorV1;
use crate::RuntimeModuleSupervisorV1;
use crate::Supervisor;
use crate::SupervisorNeuronActiveCandidateV1;
use crate::model::ControlRuntimePhase;

const DOMAIN: &[u8] = b"hepta.supervisor.neuron.agent-process-correlation.diagnostic.v1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SupervisorNeuronAgentProcessV1 {
    pub agent_id: AgentId,
    /// Actual process generation, not the Neuron module's model generation.
    pub process_runtime_generation: u64,
    /// A process restart changes this even if its release identity is equal.
    pub process_spawn_generation: u64,
    pub process_system_id: u64,
    pub process_incarnation_digest: Digest32,
    pub active_release_digest: Digest32,
    pub control_revision: u64,
    pub release_state_generation: u64,
    pub selected_module: SupervisorNeuronActiveCandidateV1,
    pub diagnostic_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl SupervisorNeuronAgentProcessV1 {
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut bytes = DOMAIN.to_vec();
        let raw = self.agent_id.as_str().as_bytes();
        bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
        bytes.extend_from_slice(raw);
        for number in [
            self.process_runtime_generation,
            self.process_spawn_generation,
            self.process_system_id,
            self.control_revision,
            self.release_state_generation,
        ] {
            bytes.extend_from_slice(&number.to_be_bytes());
        }
        for digest in [
            self.process_incarnation_digest,
            self.active_release_digest,
            self.selected_module.diagnostic_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }

    /// Self-integrity only. Old values are not current without re-reading the
    /// same owning Supervisor instance and module registry.
    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && self.process_runtime_generation != 0
            && self.process_spawn_generation != 0
            && self.process_system_id != 0
            && !self.process_incarnation_digest.is_zero()
            && !self.active_release_digest.is_zero()
            && self.selected_module.validate_integrity()
            && self.selected_module.owner_id.as_str() == self.agent_id.as_str()
            && !self.diagnostic_digest.is_zero()
            && self.diagnostic_digest == self.computed_digest()
    }
}

#[derive(Debug, Error)]
pub enum NeuronAgentProcessCorrelationErrorV1 {
    #[error("module selection: {0}")]
    Module(#[from] RuntimeModuleSupervisorErrorV1),
    #[error("Neuron module owner and Agentd agent identity disagree")]
    OwnerMismatch,
    #[error("Agentd is not an authenticated and unfenced Running process")]
    NotRunning,
    #[error("previous Neuron/Agentd process correlation is no longer current")]
    Stale,
}

impl<D: ProcessDriver> Supervisor<D> {
    /// Read the existing Supervisor's actual Agentd process snapshot and a
    /// selected ACTIVE Neuron module from the companion lifecycle owner.
    ///
    /// The initial profile requires module owner_id to be exactly the AgentId
    /// string. Deployments using another module-owner namespace require their
    /// OWN independently verified owner-to-agent mapping, not an implicit
    /// string substitution. A process observation is not host attestation.
    ///
    /// No new registry is created; the call does not select, run or deploy a
    /// Neuron or consume signed final-use authority. The status route of the
    /// current CNS is not a Neuron model dispatch route.
    pub fn read_current_neuron_agent_process_v1(
        &self,
        module_owner: &RuntimeModuleSupervisorV1,
        agent_id: &AgentId,
        module_generation: Generation,
        expected_module_candidate_digest: Digest32,
    ) -> Result<SupervisorNeuronAgentProcessV1, NeuronAgentProcessCorrelationErrorV1> {
        let module = module_owner
            .read_neuron_active_candidate_v1(module_generation, expected_module_candidate_digest)?;
        if module.owner_id.as_str() != agent_id.as_str() {
            return Err(NeuronAgentProcessCorrelationErrorV1::OwnerMismatch);
        }
        let status = self
            .snapshot(agent_id)
            .ok_or(NeuronAgentProcessCorrelationErrorV1::NotRunning)?;
        if !status.active
            || !status.healthy
            || status.release_change_pending
            || status.restart_pending
            || status.runtime_fenced
            || status.runtime_phase != Some(ControlRuntimePhase::Running)
        {
            return Err(NeuronAgentProcessCorrelationErrorV1::NotRunning);
        }
        let runtime_generation = status
            .runtime_generation
            .filter(|n| *n != 0)
            .ok_or(NeuronAgentProcessCorrelationErrorV1::NotRunning)?;
        let spawn_generation = status
            .spawn_generation
            .filter(|n| *n != 0)
            .ok_or(NeuronAgentProcessCorrelationErrorV1::NotRunning)?;
        let system_id = status
            .process_system_id
            .filter(|n| *n != 0)
            .ok_or(NeuronAgentProcessCorrelationErrorV1::NotRunning)?;
        let incarnation = status
            .runtime_incarnation
            .filter(|v| !v.is_empty())
            .ok_or(NeuronAgentProcessCorrelationErrorV1::NotRunning)?;
        let selected_release = status
            .active_release
            .filter(|v| !v.is_empty())
            .ok_or(NeuronAgentProcessCorrelationErrorV1::NotRunning)?;
        if status.runtime_release.as_deref() != Some(selected_release.as_str()) {
            return Err(NeuronAgentProcessCorrelationErrorV1::NotRunning);
        }

        let mut report = SupervisorNeuronAgentProcessV1 {
            agent_id: agent_id.clone(),
            process_runtime_generation: runtime_generation,
            process_spawn_generation: spawn_generation,
            process_system_id: system_id,
            process_incarnation_digest: Digest32::of_bytes(incarnation.as_bytes()),
            active_release_digest: Digest32::of_bytes(selected_release.as_bytes()),
            control_revision: status.control_revision,
            release_state_generation: status.release_state_generation,
            selected_module: module,
            diagnostic_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        report.diagnostic_digest = report.computed_digest();
        if !report.validate_integrity() {
            return Err(NeuronAgentProcessCorrelationErrorV1::NotRunning);
        }
        module_owner.revalidate_neuron_active_candidate_v1(&report.selected_module)?;
        Ok(report)
    }

    /// Compare a prior diagnostic against two freshly read in-process owners.
    /// In particular, changing PID/incarnation, release, restart/fence state,
    /// selected module, topology or selected generation invalidates the old
    /// observation. This is NOT an atomic snapshot of separate processes.
    pub fn revalidate_current_neuron_agent_process_v1(
        &self,
        module_owner: &RuntimeModuleSupervisorV1,
        previous: &SupervisorNeuronAgentProcessV1,
    ) -> Result<(), NeuronAgentProcessCorrelationErrorV1> {
        if !previous.validate_integrity() {
            return Err(NeuronAgentProcessCorrelationErrorV1::Stale);
        }
        let now = self.read_current_neuron_agent_process_v1(
            module_owner,
            &previous.agent_id,
            previous.selected_module.module_generation,
            previous.selected_module.candidate_artifact_digest,
        )?;
        if &now != previous {
            return Err(NeuronAgentProcessCorrelationErrorV1::Stale);
        }
        Ok(())
    }
}
