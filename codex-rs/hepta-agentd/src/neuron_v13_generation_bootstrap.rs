//! Explicit typed V13 assembly using the existing Cell and inference owners.
//! Preparing assets grants no source-frontier, learning or adoption authority;
//! the process verifies the named complete closure before every inference.

use std::fs::File;
use std::sync::Arc;
use std::sync::OnceLock;
use std::time::Duration;

use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::V13GenerationProcessConfigV1;
use codex_hepta_neuron::V13GenerationProcessFilesV1;
use codex_hepta_neuron::V13GenerationProcessWorkerV1;
use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::NeuronGenerationRuntimeBootstrapV2;
use crate::NeuronGenerationRuntimeHandleV2;
use crate::neuron_generation_channel_v2;
use crate::neuron_generation_process_bootstrap::linux::boot_id;
use crate::neuron_generation_process_bootstrap::linux::boottime_micros;
#[cfg(test)]
use crate::neuron_generation_process_identity_digest_v1;

#[path = "neuron_v13_generation_owners.rs"]
pub(crate) mod owners;

/// A V13 worker paired with the actual Linux boot identity and CLOCK_BOOTTIME.
/// Its fields are private so a caller cannot substitute an unrelated clock.
pub struct AgentdV13GenerationWorkerV1 {
    worker: Arc<V13GenerationProcessWorkerV1>,
    boot_id_digest: Digest32,
    preparation_scope: OnceLock<[u8; 32]>,
}

impl AgentdV13GenerationWorkerV1 {
    /// Read the immutable bindings needed to construct the host's manifest.
    pub fn worker(&self) -> &V13GenerationProcessWorkerV1 {
        &self.worker
    }

    pub fn boot_id_digest(&self) -> Digest32 {
        self.boot_id_digest
    }
}

/// Hash and retain host-opened assets without running a model or a verifier.
/// The caller remains responsible for admission of these exact artifacts and
/// the interpreter environment. This function never opens an owner file.
pub fn prepare_agentd_v13_generation_worker_v1(
    config: V13GenerationProcessConfigV1,
    files: V13GenerationProcessFilesV1,
) -> Result<AgentdV13GenerationWorkerV1, AgentdError> {
    let boot_id_digest = Digest32::of_parts(&[
        b"hepta.agentd.v13-generation-clock.v1\0",
        boot_id()?.as_bytes(),
    ]);
    boottime_micros()?;
    let clock: Arc<dyn Fn() -> u64 + Send + Sync> = Arc::new(|| boottime_micros().unwrap_or(0));
    let worker = V13GenerationProcessWorkerV1::open_files(config, files, clock).map_err(invalid)?;
    if boot_id_digest
        != Digest32::of_parts(&[
            b"hepta.agentd.v13-generation-clock.v1\0",
            boot_id()?.as_bytes(),
        ])
    {
        return Err(invalid("V13 preparation crossed a Linux boot identity"));
    }
    Ok(AgentdV13GenerationWorkerV1 {
        worker: Arc::new(worker),
        boot_id_digest,
        preparation_scope: OnceLock::new(),
    })
}

/// Typed host inputs. Expected digests pin this complete Agentd identity and
/// observed boot; they do not authorize publication or source adoption.
#[derive(Clone)]
pub struct AgentdV13GenerationBootstrapConfigV1 {
    pub expected_identity_digest: Digest32,
    pub expected_boot_id_digest: Digest32,
    pub generation: CellGenerationConfigV2,
    pub max_records: u64,
    pub control_capacity: usize,
    pub queue_capacity: usize,
    pub rpc_timeout: Duration,
}

/// Already opened owner capabilities. Callers must retain the witness
/// independently and must not retain writers or alter shared descriptor flags.
/// The host syncs the real containing directories for newly created entries.
/// No pathname is reopened and no failed recovery falls back to initialization.
pub struct V13GenerationOwnerFilesV1 {
    pub journal: File,
    pub witness: File,
    pub control: File,
}

/// Initialization proves the supplied files are empty, not their provenance.
/// Hosts choose create-new before transfer; reopen requires retained history.
#[derive(Clone, Copy)]
pub enum V13GenerationOwnerModeV1 {
    InitializeEmpty,
    Reopen,
}

/// Assemble the existing exclusive owners, preserving their original bytes.
/// All descriptor identity and mode checks precede owner locking or decoding.
/// The returned endpoint is typed only; ordinary CLI selection is unchanged.
pub fn bootstrap_agentd_v13_generation_v1(
    identity: &AgentdIdentity,
    config: AgentdV13GenerationBootstrapConfigV1,
    files: V13GenerationOwnerFilesV1,
    mode: V13GenerationOwnerModeV1,
    prepared: &AgentdV13GenerationWorkerV1,
) -> Result<
    (
        NeuronGenerationRuntimeHandleV2,
        NeuronGenerationRuntimeBootstrapV2,
    ),
    AgentdError,
> {
    let opened = owners::open_owners(identity, config, files, mode, prepared)?;
    let generation = opened.backend.configuration().generation.clone();
    let max_records = opened.backend.configuration().max_records;
    let queue_capacity = opened.backend.configuration().queue_capacity;
    let mut journal =
        CellGenerationJournalV2::open(opened.journal, opened.witness, generation, max_records)
            .map_err(invalid)?;
    // One prepared worker retains the same observation on an exact reopen.
    journal
        .record_cost(opened.backend.preparation_cost()?)
        .map_err(invalid)?;
    let (port, clock) = opened.backend.spawn()?;
    neuron_generation_channel_v2(identity, journal, port, move || clock(), queue_capacity)
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}

#[cfg(test)]
#[path = "neuron_v13_generation_bootstrap_tests.rs"]
mod tests;
