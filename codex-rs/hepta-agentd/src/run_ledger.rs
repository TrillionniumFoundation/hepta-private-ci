//! Crash-recoverable Agentd run-lifecycle metadata.
//!
//! The ledger intentionally persists only run identity, digests, generations,
//! deadlines, revision, phase and cancellation metadata. Prompt, context and
//! artifact bytes remain with their canonical owners.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentRunCoordinator;
use crate::AgentRunError;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::RuntimeComposition;

const RUN_LEDGER_SCHEMA_VERSION: u32 = 1;
const RUN_LEDGER_FILE: &str = "agentd-run-lifecycle-v1.json";

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PersistedRunLedger {
    schema_version: u32,
    agent_id: String,
    coordinator: AgentRunCoordinator,
}

#[derive(Debug)]
pub(crate) struct RunLedger {
    path: PathBuf,
    agent_id: String,
    coordinator: AgentRunCoordinator,
}

impl RunLedger {
    pub(crate) fn open(identity: &AgentdIdentity) -> Result<Self, AgentdError> {
        let path = identity.run_root.join(RUN_LEDGER_FILE);
        let agent_id = identity.agent_id.to_string();
        let composition = runtime_composition(identity);

        let coordinator = if path.exists() {
            let bytes = std::fs::read(&path)?;
            let persisted: PersistedRunLedger = serde_json::from_slice(&bytes)?;
            if persisted.schema_version != RUN_LEDGER_SCHEMA_VERSION {
                return Err(AgentdError::Protocol(format!(
                    "unsupported Agentd run ledger schema {}",
                    persisted.schema_version
                )));
            }
            if persisted.agent_id != agent_id {
                return Err(AgentdError::GenerationFenced(format!(
                    "run ledger owner {} does not match Agentd owner {}",
                    persisted.agent_id, agent_id
                )));
            }
            let mut coordinator = persisted.coordinator;
            coordinator
                .validate_recovered_state()
                .map_err(run_error)?;
            coordinator
                .reconcile_after_restart(composition)
                .map_err(run_error)?;
            coordinator
        } else {
            AgentRunCoordinator::compose_runtime(composition).map_err(run_error)?
        };

        let ledger = Self {
            path,
            agent_id,
            coordinator,
        };
        ledger.persist_value(&ledger.coordinator)?;
        Ok(ledger)
    }

    pub(crate) fn coordinator(&self) -> &AgentRunCoordinator {
        &self.coordinator
    }

    /// Apply one lifecycle mutation transactionally with respect to the
    /// persisted ledger. The in-memory value advances only after the new file
    /// has been synced and atomically renamed.
    pub(crate) fn transact<T>(
        &mut self,
        operation: impl FnOnce(&mut AgentRunCoordinator) -> Result<T, AgentRunError>,
    ) -> Result<T, AgentdError> {
        let mut next = self.coordinator.clone();
        let result = operation(&mut next).map_err(run_error)?;
        next.validate_recovered_state().map_err(run_error)?;
        if next != self.coordinator {
            self.persist_value(&next)?;
            self.coordinator = next;
        }
        Ok(result)
    }

    fn persist_value(&self, coordinator: &AgentRunCoordinator) -> Result<(), AgentdError> {
        let parent = self.path.parent().ok_or_else(|| {
            AgentdError::Invalid("run ledger path has no parent directory".to_string())
        })?;
        std::fs::create_dir_all(parent)?;

        let persisted = PersistedRunLedger {
            schema_version: RUN_LEDGER_SCHEMA_VERSION,
            agent_id: self.agent_id.clone(),
            coordinator: coordinator.clone(),
        };
        let mut bytes = serde_json::to_vec(&persisted)?;
        bytes.push(b'\n');

        let tmp = temp_path(&self.path);
        let mut options = OpenOptions::new();
        options.create(true).truncate(true).write(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(&tmp)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        drop(file);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&tmp, std::fs::Permissions::from_mode(0o600))?;
        }
        std::fs::rename(&tmp, &self.path)?;
        sync_parent(parent)?;
        Ok(())
    }
}

fn runtime_composition(identity: &AgentdIdentity) -> RuntimeComposition {
    let configuration = format!(
        "agentd-composition-v1\nagent={}\nspawn_generation={}\nworkspace={}\nhome={}\nrun={}\n",
        identity.agent_id,
        identity.spawn_generation,
        identity.workspace.display(),
        identity.home_root.display(),
        identity.run_root.display(),
    );
    let ports = format!(
        "agentd-ports-v1\ncontrol={}\napp_server={}\nprotocol={}\n",
        identity.control_socket.display(),
        identity.app_server_socket.display(),
        crate::AGENTD_CONTROL_SCHEMA_VERSION,
    );
    RuntimeComposition {
        agent_id: identity.agent_id.to_string(),
        supervisor_generation: identity.spawn_generation,
        agentd_generation: identity.spawn_generation,
        configuration_digest: Sha256Digest::for_bytes(configuration.as_bytes())
            .as_str()
            .to_string(),
        ports_digest: Sha256Digest::for_bytes(ports.as_bytes())
            .as_str()
            .to_string(),
    }
}

fn temp_path(path: &Path) -> PathBuf {
    let mut value = path.as_os_str().to_os_string();
    value.push(".tmp");
    PathBuf::from(value)
}

#[cfg(unix)]
fn sync_parent(parent: &Path) -> Result<(), AgentdError> {
    File::open(parent)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_parent(_parent: &Path) -> Result<(), AgentdError> {
    Ok(())
}

fn run_error(error: AgentRunError) -> AgentdError {
    AgentdError::Protocol(format!("Agentd run lifecycle rejected: {error:?}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ledger_filename_is_owner_local_and_fixed() {
        assert_eq!(RUN_LEDGER_FILE, "agentd-run-lifecycle-v1.json");
        assert!(!Path::new(RUN_LEDGER_FILE).is_absolute());
    }
}
