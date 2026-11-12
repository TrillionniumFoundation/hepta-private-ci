//! Independent original Root RunStart retention. The stored tuple and physical
//! cut are data, not permission to execute, freeze a Dataset or read history.
//! A live first append is retained before A executes; cold opens never create
//! that first acknowledgement or promote an interrupted verification.

use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_learning_ledger::RunStartReadOnlyFrameV1;

use super::data_refusal::RootDataKind;
use super::data_refusal::RootDataRefusalV1;
use super::*;
use crate::authority_host_runtime::RootInitialRunStartFilesV1;

#[path = "authority_host_run_start_inputs.rs"]
mod inputs;
use inputs::OriginalInputPin;
#[path = "authority_host_run_start_context.rs"]
mod context;
#[path = "authority_host_run_start_store.rs"]
mod store;
#[path = "authority_host_run_start_transport.rs"]
mod transport;
pub(crate) use transport::OriginalRunStartRetentionExchange;

pub(crate) const RUN_START_RETENTION_PURPOSE: &str =
    "runtime.objective.original-run-start-retain.v1";
const RECORD_PURPOSE: &str = "runtime.objective.root-retained-run-start.v1";

/// Untrusted publication data from the actual append/sync receipt. No path,
/// key, writer, authority, caller-authored freshness flag or recovery mode.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct OriginalRunStartPublicationDataV1 {
    pub(crate) run_id: String,
    pub(crate) profile_digest: String,
    pub(crate) sequence: u64,
    pub(crate) record_digest: String,
    pub(crate) chain_digest: String,
}

impl OriginalRunStartPublicationDataV1 {
    fn validate(&self) -> io::Result<()> {
        StableId::new(&self.run_id).map_err(io::Error::other)?;
        digest(&self.profile_digest)?;
        digest(&self.record_digest)?;
        digest(&self.chain_digest)?;
        if !(1..=4_096).contains(&self.sequence) {
            return Err(io::Error::other("original RunStart sequence exceeds bound"));
        }
        Ok(())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct OriginalRunStartRetentionResponseV1 {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) request_id: u64,
    pub(crate) profile: String,
    pub(crate) mode: RootGenerationInitialModeV1,
    pub(crate) publication: OriginalRunStartPublicationDataV1,
    pub(crate) retained: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct OriginalRunStartRegistration {
    schema: u8,
    purpose: String,
    initial_profile: String,
    identity: String,
    spawn_generation: u64,
    writer: String,
    publisher_epoch: u64,
    publisher: CognitiveCheckpointPeerLifetime,
    publisher_gid: u32,
    target: CellGenerationOwnerBindingV1,
    target_files: String,
    inputs: OriginalInputPin,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum RetentionPhase {
    AwaitingLiveAppend,
    Finalized,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RunStartObservation {
    publication: OriginalRunStartPublicationDataV1,
    frame_start: u64,
    frame_end: u64,
    observed_length: u64,
    observed_unix_ms: u64,
    current: CurrentHead,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RetainedRunStartRecord {
    original: OriginalRunStartRegistration,
    phase: RetentionPhase,
    observed: Option<RunStartObservation>,
}

struct RunStartRecordStore {
    store: HostAuthorityFrontierStore<RetainedRunStartRecord>,
    owner: String,
    expected: RetainedRunStartRecord,
}

/// Lives only in the exact Initial runtime which registered these inputs.
/// It cannot be recovered, cloned, deserialized or supplied by the peer.
pub(crate) struct RegisteredInitialRunStartRetentionV1 {
    files: Arc<RootInitialRunStartFilesV1>,
    state: Mutex<RunStartRecordStore>,
    refusal: RootDataRefusalV1,
    consumed: AtomicBool,
}

/// A cold data reader. Only Finalized plus an independent Ready refusal marker
/// can open. New-recipient Root learning authority is deliberately separate.
pub(crate) struct RootRetainedRunStartDataV1 {
    state: RunStartRecordStore,
    refusal: RootDataRefusalV1,
}

fn digest(value: &str) -> io::Result<Digest32> {
    let digest = value.parse::<Digest32>().map_err(io::Error::other)?;
    if digest.is_zero() {
        return Err(io::Error::other(
            "nonzero original RunStart digest required",
        ));
    }
    Ok(digest)
}

fn require_end(end: Instant) -> io::Result<()> {
    original_root()?;
    if Instant::now() >= end {
        return Err(io::Error::new(
            io::ErrorKind::TimedOut,
            "original RunStart retention expired",
        ));
    }
    Ok(())
}

fn owner(target: &CellGenerationOwnerBindingV1) -> io::Result<String> {
    target.digest().map_err(io::Error::other)?;
    Ok(format!(
        "initial-run-start/{}",
        crate::neuron_generation_current::types::scope_digest(target.scope())
            .map_err(io::Error::other)?,
    ))
}

#[cfg(test)]
#[path = "authority_host_run_start_retention_tests.rs"]
mod tests;
