//! Bounded identity retention for explicitly admitted optional replacements.
//!
//! Generations here are host-local execution fences, not selection evidence or
//! durable writer leases. The composition owner must finish its existing state
//! handoff before registering a successor. Cross-process recovery still belongs
//! to the Supervisor and durable owners; this map is not a recovery checkpoint.

use std::future::Future;

use codex_hepta_control_plane::ActiveRuntimeModuleV1;
use codex_hepta_control_plane::RuntimeModuleAbiV1;
use codex_hepta_types::Generation;
use tokio_util::sync::CancellationToken;

use super::MAX_TASKS;
use super::RuntimeTasks;
use crate::AgentdError;

impl RuntimeTasks {
    /// Slots for NEW identities, not for replacements of acknowledged retired
    /// services. Exhaustion requires supervised process-generation rotation;
    /// dropping retirement fences or renaming services is not a recovery plan.
    pub fn remaining_admission_slots(&self) -> usize {
        MAX_TASKS.saturating_sub(self.admitted_names.len())
    }

    pub(super) fn reject_versioned_name(&self, name: &str) -> Result<(), AgentdError> {
        if self.service_generations.contains_key(name) {
            return Err(AgentdError::Protocol(
                "versioned runtime service requires an exact generation".to_string(),
            ));
        }
        Ok(())
    }

    /// Bind a compiled service to the composition owner's current module ABI.
    ///
    /// In particular, port order and versioned port identities must agree before
    /// the factory can execute. Reuses the existing module ABI and task host;
    /// there is no second registry or independently writable service manifest.
    /// The owner must validate its concrete Rust configuration before calling.
    /// These public DTOs are not capabilities: this compares trusted composition
    /// inputs, not independent selection, writer handoff or permission to act.
    pub fn spawn_bound_optional_service<F, S, Q, R>(
        &mut self,
        selected: &ActiveRuntimeModuleV1,
        implementation: &RuntimeModuleAbiV1,
        start: S,
        quarantine: Q,
        retire: R,
    ) -> Result<(), AgentdError>
    where
        F: Future<Output = Result<(), AgentdError>> + Send + 'static,
        S: FnOnce(CancellationToken) -> F + Send + 'static,
        Q: FnOnce() -> Result<(), AgentdError> + Send + 'static,
        R: FnOnce() -> Result<(), AgentdError> + Send + 'static,
    {
        implementation
            .validate()
            .map_err(|error| AgentdError::Protocol(format!("invalid service ABI: {error}")))?;
        let compiled = ActiveRuntimeModuleV1 {
            module_id: implementation.module_id.clone(),
            generation: implementation.generation,
            implementation_digest: implementation.implementation_digest,
            candidate_artifact_digest: implementation.candidate_artifact_digest,
            owner_id: implementation.owner_id.clone(),
            state_class: implementation.state_class,
            dependencies: implementation.dependencies.clone(),
            input_ports: implementation.input_ports.clone(),
            output_ports: implementation.output_ports.clone(),
            authoritative_domains: implementation.authoritative_domains.clone(),
            effect_scope: implementation.effect_scope.clone(),
        };
        if selected != &compiled {
            return Err(AgentdError::Protocol(
                "compiled service does not match the selected module ABI".to_string(),
            ));
        }
        self.spawn_optional_service_generation(
            implementation.module_id.as_str(),
            implementation.generation,
            implementation.predecessor_generation,
            start,
            quarantine,
            retire,
        )
    }

    /// Start a separately admitted generation through the SAME task host.
    ///
    /// Replacement requires the exact predecessor and acknowledged retirement.
    /// A timeout, quarantine or forced abort never releases a replacement slot.
    /// Every logical identity retains its greatest generation even when retired,
    /// so repeated acknowledged replacements use constant host memory.
    /// This method does not load code, approve compatibility, migrate owner state,
    /// select a candidate, issue authority or retry an external effect.
    pub fn spawn_optional_service_generation<F, S, Q, R>(
        &mut self,
        name: &str,
        generation: Generation,
        expected_predecessor: Option<Generation>,
        start: S,
        quarantine: Q,
        retire: R,
    ) -> Result<(), AgentdError>
    where
        F: Future<Output = Result<(), AgentdError>> + Send + 'static,
        S: FnOnce(CancellationToken) -> F + Send + 'static,
        Q: FnOnce() -> Result<(), AgentdError> + Send + 'static,
        R: FnOnce() -> Result<(), AgentdError> + Send + 'static,
    {
        let predecessor = self.service_generations.get(name).copied();
        if predecessor != expected_predecessor {
            return Err(AgentdError::Protocol(
                "runtime service predecessor generation mismatch".to_string(),
            ));
        }
        match predecessor {
            Some(previous) => {
                if generation <= previous {
                    return Err(AgentdError::Protocol(
                        "runtime service generation must advance".to_string(),
                    ));
                }
                if !self.retired_names.contains(name)
                    || self.entries.values().any(|entry| entry.name == name)
                {
                    return Err(AgentdError::Protocol(
                        "runtime predecessor retirement is not acknowledged".to_string(),
                    ));
                }
            }
            None if self.admitted_names.contains(name) => {
                return Err(AgentdError::Protocol(
                    "legacy runtime identity cannot become a versioned service".to_string(),
                ));
            }
            None => {}
        }
        // Transactional slot reuse: rejected admission preserves both the last
        // generation and its retirement acknowledgement. The factory remains
        // deferred inside the spawned future, never called by validation.
        let reserved = self.admitted_names.remove(name);
        let retired = self.retired_names.remove(name);
        if let Err(error) = self.spawn_service(name, start, quarantine, retire) {
            if reserved {
                self.admitted_names.insert(name.to_string());
            }
            if retired {
                self.retired_names.insert(name.to_string());
            }
            return Err(error);
        }
        self.service_generations.insert(name.to_string(), generation);
        Ok(())
    }

    /// Exact-generation retirement prevents delayed requests for a predecessor
    /// from stopping a newer implementation under the same logical identity.
    pub async fn retire_optional_generation(
        &mut self,
        name: &str,
        expected: Generation,
    ) -> Result<(), AgentdError> {
        if self.service_generations.get(name) != Some(&expected) {
            return Err(AgentdError::Protocol(
                "runtime retirement generation mismatch".to_string(),
            ));
        }
        self.retire_optional_inner(name).await
    }
}

#[cfg(test)]
#[path = "runtime_service_generation_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "runtime_service_writer_rotation_tests.rs"]
mod writer_tests;

#[cfg(test)]
#[path = "runtime_service_abi_tests.rs"]
mod abi_tests;
