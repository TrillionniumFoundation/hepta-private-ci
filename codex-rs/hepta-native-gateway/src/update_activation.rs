use std::path::Path;
use std::path::PathBuf;

use anyhow::Result;

use crate::updater::ArtifactDigest;
use crate::updater::SystemArtifactDigest;
use crate::updater::TransactionalUpdater;
use crate::updater::UpdateDisposition;

#[derive(Clone, Debug)]
pub struct NativeUpdateActivationConfig {
    pub active_artifact: PathBuf,
    pub rollback_artifact: PathBuf,
    pub stage_artifact: PathBuf,
    pub update_journal: PathBuf,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NativeActivationStatus {
    RestartRequired,
    Confirmed,
    RolledBack,
    Quarantined,
}

pub fn activate_staged_update(
    config: &NativeUpdateActivationConfig,
) -> Result<NativeActivationStatus> {
    let updater = open_updater(config)?;
    Ok(map_status(updater.activate_staged()?))
}

/// Called only after a newly launched application has stopped or failed to
/// confirm. Supplying the predecessor digest forces the activated candidate to
/// take the rollback branch rather than trying to mutate a running executable.
pub fn rollback_unconfirmed_update(
    config: &NativeUpdateActivationConfig,
    predecessor_digest: &str,
) -> Result<NativeActivationStatus> {
    let updater = open_updater(config)?;
    Ok(map_status(updater.recover_or_confirm(predecessor_digest)?))
}

pub fn artifact_digest(path: &Path) -> Result<String> {
    SystemArtifactDigest.sha256(path)
}

fn open_updater(
    config: &NativeUpdateActivationConfig,
) -> Result<TransactionalUpdater<SystemArtifactDigest>> {
    TransactionalUpdater::open(
        SystemArtifactDigest,
        config.active_artifact.clone(),
        config.rollback_artifact.clone(),
        config.stage_artifact.clone(),
        config.update_journal.clone(),
    )
}

fn map_status(value: UpdateDisposition) -> NativeActivationStatus {
    match value {
        UpdateDisposition::RestartRequired => NativeActivationStatus::RestartRequired,
        UpdateDisposition::Confirmed => NativeActivationStatus::Confirmed,
        UpdateDisposition::RolledBack => NativeActivationStatus::RolledBack,
        UpdateDisposition::Quarantined => NativeActivationStatus::Quarantined,
    }
}
