//! First external replay witness for the original, stopped Agent's sole store.
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::evidence::EVIDENCE_DATABASE_LINEAGE;
use codex_hepta_agent_components::evidence::HeptaEvidenceStore;
use codex_hepta_agent_components::evidence::ReplayCheckpoint;
use codex_hepta_agent_components::fleet::AgentLifecycle;
use codex_hepta_agent_components::fleet::FleetRegistry;
use codex_hepta_agent_components::paths::HeptaFleetRoot;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::authbus_checkpoint::ReplayCheckpointFile;
use crate::authbus_trust::invalid;
use crate::operator_namespace::OperatorNamespace;

/// Initialize only when the original resource/lifecycle owner says Stopped and
/// its actual writer lock is exclusively held. Existing witnesses use the same
/// pending/CAS reconciliation as ordinary startup; lost witnesses fail closed.
pub async fn initialize_offline_authbus_checkpoint_v1(
    fleet_root: &Path,
    agent_id: &AgentId,
    checkpoint_path: &Path,
) -> Result<ReplayCheckpoint, AgentdError> {
    let registry = FleetRegistry::open_existing_for_agent(
        HeptaFleetRoot::parse(fleet_root.to_owned())
            .map_err(|error| invalid(&error.to_string()))?,
        agent_id,
    )?;
    let record = registry.load_agent(agent_id)?;
    if record.lifecycle.lifecycle != AgentLifecycle::Stopped {
        return Err(invalid(
            "offline checkpoint requires the original Stopped lifecycle",
        ));
    }
    let home = record.layout.home_root();
    let home_metadata = std::fs::metadata(home)?;
    if rustix_uid() != home_metadata.uid()
        || home_metadata.mode() & 0o077 != 0
        || home.canonicalize()? != home
    {
        return Err(invalid(
            "offline checkpoint requires the exact private Agent owner",
        ));
    }
    // Never create a replacement lock or another evidence lineage.
    let lock_path = record.layout.writer_lock();
    let metadata = std::fs::symlink_metadata(lock_path)?;
    if metadata.uid() != home_metadata.uid() || metadata.mode() & 0o077 != 0 {
        return Err(invalid(
            "original writer lock has another owner or is unprotected",
        ));
    }
    let namespace = OperatorNamespace::capture(lock_path, &metadata)?;
    let lock = namespace.open_regular(lock_path, &metadata)?;
    lock.try_lock()
        .map_err(|_| invalid("original Agent writer is still active"))?;
    if registry.load_agent(agent_id)?.lifecycle != record.lifecycle {
        return Err(invalid(
            "original lifecycle advanced while taking the writer",
        ));
    }
    let database = home.join(EVIDENCE_DATABASE_LINEAGE);
    let database_metadata = std::fs::symlink_metadata(&database)?;
    if !database_metadata.is_file()
        || database_metadata.nlink() != 1
        || database_metadata.uid() != home_metadata.uid()
        || database_metadata.mode() & 0o077 != 0
    {
        return Err(invalid(
            "original evidence lineage is absent or unprotected",
        ));
    }
    let sqlite = SqliteConfig::from_sqlite_home(AbsolutePathBuf::from_absolute_path(home)?);
    // Verify the complete existing schema without migrating or creating a DB.
    let check = HeptaEvidenceStore::open_existing_read_only(&sqlite)
        .await
        .map_err(|error| invalid(&error.to_string()))?;
    check.close().await;
    let evidence = HeptaEvidenceStore::open(&sqlite)
        .await
        .map_err(|error| invalid(&error.to_string()))?;
    let identity = AgentdIdentity {
        agent_id: agent_id.clone(),
        layout: record.layout.clone(),
        // This stopped descriptor is used only by existing path validation;
        // it is never an execution, spawn or objective admission witness.
        spawn_generation: 0,
        fleet_root: fleet_root.to_owned(),
        workspace: record.manifest.workspace.as_path().to_owned(),
        resources: record.manifest.resources.clone(),
        home_root: home.to_owned(),
        run_root: record.layout.run_root().to_owned(),
        control_socket: record.layout.agentd_control_socket().to_owned(),
        app_server_socket: record.layout.app_server_socket().to_owned(),
    };
    let result = initialize_witness(&evidence, checkpoint_path, &identity).await;
    evidence.close().await;
    namespace.verify(lock_path, &std::fs::symlink_metadata(lock_path)?)?;
    if registry.load_agent(agent_id)?.lifecycle != record.lifecycle {
        return Err(invalid(
            "original lifecycle advanced during offline initialization",
        ));
    }
    result
}

async fn initialize_witness(
    evidence: &HeptaEvidenceStore,
    path: &Path,
    identity: &AgentdIdentity,
) -> Result<ReplayCheckpoint, AgentdError> {
    let local = evidence
        .authbus_restore_checkpoint()
        .await
        .map_err(|error| invalid(&error.to_string()))?;
    match std::fs::symlink_metadata(path) {
        Ok(_) => {
            let (file, external) = ReplayCheckpointFile::open(path.to_owned(), identity)?;
            if local.is_none() {
                evidence
                    .initialize_authbus_restore_checkpoint(external)
                    .await
                    .map_err(|error| invalid(&error.to_string()))?;
            } else if let Some(pending) = evidence
                .reconcile_authbus_restore_checkpoint(external)
                .await
                .map_err(|error| invalid(&error.to_string()))?
            {
                file.replace(external, pending)?;
                evidence
                    .advance_authbus_restore_checkpoint(external.generation, pending)
                    .await
                    .map_err(|error| invalid(&error.to_string()))?;
            }
            file.read()
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound && local.is_none() => {
            let checkpoint = ReplayCheckpoint {
                generation: 1,
                digest: evidence
                    .authbus_replay_frontier_digest()
                    .await
                    .map_err(|error| invalid(&error.to_string()))?,
            };
            write_initial_witness(path, identity, checkpoint)?;
            evidence
                .initialize_authbus_restore_checkpoint(checkpoint)
                .await
                .map_err(|error| invalid(&error.to_string()))?;
            Ok(checkpoint)
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Err(invalid(
            "existing original replay history lost its external witness",
        )),
        Err(error) => Err(error.into()),
    }
}

fn write_initial_witness(
    path: &Path,
    identity: &AgentdIdentity,
    checkpoint: ReplayCheckpoint,
) -> Result<(), AgentdError> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("external witness parent"))?;
    let home = std::fs::metadata(&identity.home_root)?;
    let metadata = std::fs::symlink_metadata(parent)?;
    if !path.is_absolute()
        || path.starts_with(&identity.home_root)
        || parent.canonicalize()? != parent
        || !metadata.is_dir()
        || metadata.uid() != home.uid()
        || metadata.mode() & 0o077 != 0
    {
        return Err(invalid(
            "first external witness must be outside home in the original private owner directory",
        ));
    }
    let bytes = serde_json::to_vec(&serde_json::json!({
        "schema_version": 1, "agent_id": identity.agent_id.to_string(),
        "generation": checkpoint.generation, "digest": checkpoint.digest.to_string(),
    }))?;
    let namespace = OperatorNamespace::capture(path, &metadata)?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    namespace.verify(path, &file.metadata()?)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    File::open(parent)?.sync_all()?;
    let (_, actual) = ReplayCheckpointFile::open(path.to_owned(), identity)?;
    if actual != checkpoint {
        return Err(invalid("initial witness changed during publication"));
    }
    Ok(())
}

fn rustix_uid() -> u32 {
    // Agentd already uses kernel ownership checks; this route never changes UID.
    unsafe { libc::geteuid() }
}

#[cfg(test)]
#[path = "authbus_offline_initialization_tests.rs"]
mod tests;
