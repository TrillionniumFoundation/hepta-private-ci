//! Crash-recoverable Agentd run-lifecycle metadata.
//!
//! The ledger intentionally persists only run identity, digests, generations,
//! deadlines, revision, phase and cancellation metadata. Prompt, context and
//! artifact bytes remain with their canonical owners.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::ErrorKind;
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
const MAX_RUN_LEDGER_BYTES: u64 = 4 * 1024 * 1024;
const DEFAULT_CANCELLATION_ACK_TIMEOUT_MS: u64 = 5_000;

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
        let composition = runtime_composition(identity)?;

        let coordinator = if path_exists_without_following(&path)? {
            validate_private_regular_file(&path)?;
            let metadata = std::fs::symlink_metadata(&path)?;
            if metadata.len() > MAX_RUN_LEDGER_BYTES {
                return Err(AgentdError::Protocol(format!(
                    "Agentd run ledger exceeds {MAX_RUN_LEDGER_BYTES} bytes"
                )));
            }
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
            coordinator.validate_recovered_state().map_err(run_error)?;
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
        if bytes.len() as u64 > MAX_RUN_LEDGER_BYTES {
            return Err(AgentdError::Protocol(format!(
                "Agentd run ledger encoding exceeds {MAX_RUN_LEDGER_BYTES} bytes"
            )));
        }

        let tmp = temp_path(&self.path);
        remove_stale_private_temp(&tmp)?;
        let mut options = OpenOptions::new();
        options.create_new(true).write(true);
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
        validate_private_regular_file(&self.path)?;
        sync_parent(parent)?;
        Ok(())
    }
}

fn runtime_composition(identity: &AgentdIdentity) -> Result<RuntimeComposition, AgentdError> {
    let resources = serde_json::to_string(&identity.resources)?;
    let configuration = format!(
        "agentd-composition-v1\nagent={}\nspawn_generation={}\nfleet={}\nworkspace={}\nhome={}\nrun={}\nresources={}\ncancellation_ack_timeout_ms={}\n",
        identity.agent_id,
        identity.spawn_generation,
        identity.fleet_root.display(),
        identity.workspace.display(),
        identity.home_root.display(),
        identity.run_root.display(),
        resources,
        DEFAULT_CANCELLATION_ACK_TIMEOUT_MS,
    );
    let ports = format!(
        "agentd-ports-v1\ncontrol={}\napp_server={}\nprotocol={}\n",
        identity.control_socket.display(),
        identity.app_server_socket.display(),
        crate::AGENTD_CONTROL_SCHEMA_VERSION,
    );
    Ok(RuntimeComposition {
        agent_id: identity.agent_id.to_string(),
        supervisor_generation: identity.spawn_generation,
        agentd_generation: identity.spawn_generation,
        configuration_digest: Sha256Digest::for_bytes(configuration.as_bytes())
            .as_str()
            .to_string(),
        ports_digest: Sha256Digest::for_bytes(ports.as_bytes())
            .as_str()
            .to_string(),
        cancellation_ack_timeout_ms: DEFAULT_CANCELLATION_ACK_TIMEOUT_MS,
    })
}

fn path_exists_without_following(path: &Path) -> Result<bool, AgentdError> {
    match std::fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error.into()),
    }
}

fn remove_stale_private_temp(path: &Path) -> Result<(), AgentdError> {
    match std::fs::symlink_metadata(path) {
        Ok(_) => {
            validate_private_regular_file(path)?;
            std::fs::remove_file(path)?;
            Ok(())
        }
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}

fn validate_private_regular_file(path: &Path) -> Result<(), AgentdError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.file_type().is_file() {
        return Err(AgentdError::Protocol(format!(
            "Agentd run ledger path is not a regular non-symlink file: {}",
            path.display()
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        use std::os::unix::fs::PermissionsExt;

        if metadata.nlink() != 1 || metadata.permissions().mode() & 0o777 != 0o600 {
            return Err(AgentdError::Protocol(format!(
                "Agentd run ledger must be a single-link mode-0600 file: {}",
                path.display()
            )));
        }
        let parent = path.parent().ok_or_else(|| {
            AgentdError::Invalid("run ledger path has no parent directory".to_string())
        })?;
        let parent_metadata = std::fs::symlink_metadata(parent)?;
        if parent_metadata.file_type().is_symlink()
            || !parent_metadata.file_type().is_dir()
            || metadata.uid() != parent_metadata.uid()
        {
            return Err(AgentdError::Protocol(format!(
                "Agentd run ledger owner or parent boundary is invalid: {}",
                path.display()
            )));
        }
    }
    Ok(())
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

    #[cfg(unix)]
    #[test]
    fn private_file_validation_rejects_symlink_hardlink_and_open_mode() {
        use std::os::unix::fs::PermissionsExt;
        use std::os::unix::fs::symlink;

        let temp = tempfile::tempdir().expect("tempdir");
        let file = temp.path().join("ledger.json");
        std::fs::write(&file, b"{}").expect("write ledger");
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600)).expect("mode 0600");
        validate_private_regular_file(&file).expect("private regular file");

        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o644)).expect("mode 0644");
        assert!(validate_private_regular_file(&file).is_err());
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600))
            .expect("restore mode");

        let hardlink = temp.path().join("hardlink.json");
        std::fs::hard_link(&file, &hardlink).expect("hardlink");
        assert!(validate_private_regular_file(&file).is_err());
        std::fs::remove_file(&hardlink).expect("remove hardlink");
        validate_private_regular_file(&file).expect("single link restored");

        let link = temp.path().join("symlink.json");
        symlink(&file, &link).expect("symlink");
        assert!(validate_private_regular_file(&link).is_err());
    }

    #[test]
    fn ledger_filename_is_owner_local_and_fixed() {
        assert_eq!(RUN_LEDGER_FILE, "agentd-run-lifecycle-v1.json");
        assert!(!Path::new(RUN_LEDGER_FILE).is_absolute());
    }
}
