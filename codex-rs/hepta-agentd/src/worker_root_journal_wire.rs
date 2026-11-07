//! Public journal observations; copying these values creates no owner.

use super::lanes_wire::WorkerRootLaneBootstrapV1;
use super::refused;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use std::io;
use std::path::PathBuf;

pub(crate) const WORKER_ROOT_JOURNAL_V1: &str = "runtime.infer_worker.local_journal.v1";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerJournalDirectoryPinV1 {
    pub schema_version: u32,
    pub purpose: String,
    pub registration_sha256: Sha256Digest,
    pub slot_sequence: u64,
    pub parent: PathBuf,
    pub directory: PathBuf,
    pub parent_device: u64,
    pub parent_inode: u64,
    pub directory_device: u64,
    pub directory_inode: u64,
    pub worker_uid: u32,
    pub worker_gid: u32,
    pub initial_frontier: FinalUseFrontier,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerRootJournalBootstrapV1 {
    pub schema_version: u32,
    pub purpose: String,
    pub lanes: WorkerRootLaneBootstrapV1,
    pub journal: WorkerJournalDirectoryPinV1,
    pub effect_authorization_available: bool,
}

pub(crate) fn journal_basename(agent: &AgentId) -> io::Result<String> {
    let bytes = serde_json::to_vec(&(WORKER_ROOT_JOURNAL_V1, agent)).map_err(io::Error::other)?;
    Ok(format!(
        "worker-{}",
        Sha256Digest::for_bytes(&bytes).as_str()
    ))
}

impl WorkerRootJournalBootstrapV1 {
    pub(crate) fn validate(&self) -> io::Result<()> {
        self.lanes.validate()?;
        let pin = &self.journal;
        if self.schema_version != 1
            || self.purpose != WORKER_ROOT_JOURNAL_V1
            || self.effect_authorization_available
            || pin.schema_version != 1
            || pin.purpose != WORKER_ROOT_JOURNAL_V1
            || pin.registration_sha256 != self.lanes.registration_sha256()?
            || pin.slot_sequence != self.lanes.slot_sequence
            || pin.worker_uid != self.lanes.registration.worker.uid
            || pin.worker_gid != self.lanes.registration.worker.gid
            || !pin.parent.is_absolute()
            || pin.parent.to_str().is_none_or(|value| value.len() > 4096)
            || pin.directory
                != pin.parent.join(journal_basename(
                    &self.lanes.registration.registered_agent_id,
                )?)
            || pin.parent_inode == 0
            || pin.directory_inode == 0
            || (pin.parent_device, pin.parent_inode) == (pin.directory_device, pin.directory_inode)
            || pin.initial_frontier != self.lanes.frontier
            || pin.initial_frontier
                != FinalUseFrontier::for_initial_head(&self.lanes.revocations)
                    .map_err(io::Error::other)?
        {
            return Err(refused(
                "Worker journal sealed purpose, original registration or fresh frontier differs",
            ));
        }
        Ok(())
    }
}
