//! Private restart admission from the actual Config owner and held writer FD.
//! No serialized input, caller-supplied digest or cached lifecycle grants this.
use super::*;
use crate::AgentRunError;
use crate::RuntimeComposition;
use codex_hepta_agent_components::contracts::Sha256Digest;
#[cfg(unix)]
use std::os::unix::fs::MetadataExt;

pub(crate) struct VerifiedRunStoreRestart {
    identity: AgentdIdentity,
    registry: FleetRegistry,
    // A duplicated handle to the original locked file description keeps the
    // exact Config writer lock alive throughout the native store CAS.
    writer_lock: File,
}

impl AgentdConfig {
    pub(crate) fn verified_run_store_restart(
        &self,
    ) -> Result<VerifiedRunStoreRestart, AgentdError> {
        let admission = VerifiedRunStoreRestart {
            identity: self.identity.clone(),
            registry: self.registry.clone(),
            writer_lock: self._writer_lock.try_clone()?,
        };
        admission.validate_current().map_err(|error| {
            AgentdError::GenerationFenced(format!("run-store restart admission: {error}"))
        })?;
        Ok(admission)
    }
}

pub(crate) fn runtime_composition(
    identity: &AgentdIdentity,
    generation: u64,
) -> RuntimeComposition {
    let configuration = format!(
        "{}|{}|{}|{}|{}",
        identity.agent_id,
        generation,
        identity.workspace.display(),
        identity.home_root.display(),
        identity.run_root.display()
    );
    let ports = format!(
        "{}|{}|{}",
        identity.control_socket.display(),
        identity.app_server_socket.display(),
        crate::AGENTD_CONTROL_SCHEMA_VERSION
    );
    RuntimeComposition {
        agent_id: identity.agent_id.as_str().to_string(),
        supervisor_generation: generation,
        agentd_generation: generation,
        configuration_digest: Sha256Digest::for_bytes(configuration.as_bytes())
            .as_str()
            .to_string(),
        ports_digest: Sha256Digest::for_bytes(ports.as_bytes())
            .as_str()
            .to_string(),
        max_active_runs: usize::from(identity.resources.max_concurrent_turns),
    }
}

impl VerifiedRunStoreRestart {
    pub(crate) fn validate_current(&self) -> Result<(), AgentRunError> {
        let checked = (|| -> Result<(), AgentdError> {
            let record = self.registry.load_agent(&self.identity.agent_id)?;
            if record.lifecycle.lifecycle != AgentLifecycle::Starting
                || record.lifecycle.generation != self.identity.spawn_generation
                || record.layout != self.identity.layout
                || record.manifest.workspace.as_path() != self.identity.workspace
                || record.manifest.resources != self.identity.resources
                || record.layout.home_root() != self.identity.home_root
                || record.layout.run_root() != self.identity.run_root
                || record.layout.agentd_control_socket() != self.identity.control_socket
                || record.layout.app_server_socket() != self.identity.app_server_socket
            {
                return Err(AgentdError::GenerationFenced(
                    "restart launch identity is not current Starting".into(),
                ));
            }
            let held = self.writer_lock.metadata()?;
            let current = std::fs::symlink_metadata(record.layout.writer_lock())?;
            if !held.is_file() || !current.is_file() {
                return Err(AgentdError::GenerationFenced(
                    "restart writer lock is not a regular file".into(),
                ));
            }
            #[cfg(unix)]
            if held.dev() != current.dev() || held.ino() != current.ino() {
                return Err(AgentdError::GenerationFenced(
                    "restart writer lock path changed".into(),
                ));
            }
            Ok(())
        })();
        checked.map_err(|error| {
            AgentRunError::Persistence(format!("verified restart rejected: {error}"))
        })
    }

    pub(crate) fn validate_store_binding(
        &self,
        current: &RuntimeComposition,
        path: &Path,
        previous: Option<&RuntimeComposition>,
    ) -> Result<(), AgentRunError> {
        self.validate_current()?;
        if current != &runtime_composition(&self.identity, self.identity.spawn_generation)
            || path
                != self
                    .identity
                    .run_root
                    .join("runtime-codex-agent-runs-v1.json")
        {
            return Err(AgentRunError::MixedSnapshot);
        }
        if let Ok(metadata) = std::fs::symlink_metadata(path)
            && !metadata.is_file()
        {
            return Err(AgentRunError::Persistence(
                "restart run store must be a regular file".into(),
            ));
        }
        let Some(previous) = previous else {
            return Ok(());
        };
        if previous == current {
            return Ok(());
        }
        let old_generation = previous.agentd_generation;
        if old_generation >= self.identity.spawn_generation
            || previous != &runtime_composition(&self.identity, old_generation)
        {
            return Err(AgentRunError::MixedSnapshot);
        }
        let prior = self
            .registry
            .load_agent_lifecycle_generation(&self.identity.agent_id, old_generation)
            .map_err(|error| AgentRunError::Persistence(format!("prior spawn history: {error}")))?;
        if prior.lifecycle != AgentLifecycle::Starting {
            return Err(AgentRunError::InvalidGeneration);
        }
        // Historical reading is evidence only. Re-read the current complete
        // contiguous history and exact Config fence before any owner mutation.
        self.validate_current()
    }
}
