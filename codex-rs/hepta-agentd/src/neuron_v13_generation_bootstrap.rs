//! Explicit typed V13 assembly using the existing Cell and inference owners.
//! Preparing assets grants no source-frontier, learning or adoption authority;
//! the process verifies the named complete closure before every inference.

use std::fs::File;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::sync::Arc;
use std::sync::OnceLock;
use std::time::Duration;

use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellTaskCostIdentityV2;
use codex_hepta_neuron::ControlledCellGenerationConfigV2;
use codex_hepta_neuron::ControlledCellGenerationPortV2;
use codex_hepta_neuron::DurableInferenceControl;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::V13GenerationProcessConfigV1;
use codex_hepta_neuron::V13GenerationProcessFilesV1;
use codex_hepta_neuron::V13GenerationProcessWorkerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::NeuronGenerationRuntimeBootstrapV2;
use crate::NeuronGenerationRuntimeHandleV2;
use crate::neuron_generation_channel_v2;
use crate::neuron_generation_process_bootstrap::identity_context_digest;
use crate::neuron_generation_process_bootstrap::linux::boot_id;
use crate::neuron_generation_process_bootstrap::linux::boottime_micros;
use crate::neuron_generation_process_identity_digest_v1;

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
/// The ordinary descriptor loader uses this same owner and control boundary.
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
    let worker_generation = validate_bootstrap(identity, &config, prepared)?;
    let generation = &config.generation;
    let worker = &prepared.worker;
    validate_files(
        &files,
        mode,
        &worker.asset_file_identities().map_err(invalid)?,
    )?;
    let preparation_scope = Digest32::of_parts(&[
        b"hepta.agentd.v13-preparation-task.v1\0",
        &serde_json::to_vec(&(
            &generation.initial.scope,
            CellTaskCostIdentityV2 {
                task_digest: generation.task_digest,
                source_digest: generation.manifest.source_digest,
            },
        ))?,
    ])
    .into_array();
    // This in-memory use restriction is not a receipt owner. Bind before any
    // owner write and retain the choice even if later locking/recovery fails.
    // Concurrent different tasks cannot both charge the same preparation.
    if prepared.preparation_scope.get_or_init(|| preparation_scope) != &preparation_scope {
        return Err(invalid(
            "prepared V13 assets already belong to another task scope",
        ));
    }
    let binding = serde_json::to_vec(&(
        identity_context_digest(identity)?.to_string(),
        config.expected_boot_id_digest.to_string(),
        generation,
        config.max_records,
    ))?;
    // This path is only the existing control owner's diagnostic label. Its
    // constructor receives the owned descriptor and never opens this pathname.
    let label = format!("/proc/self/fd/{}", files.control.as_raw_fd());
    let control = DurableInferenceControl::open_file(files.control, label, config.control_capacity)
        .map_err(invalid)?;
    let witness = FileAnchorWitnessStore::open(
        files.witness,
        JournalScope {
            scope_digest: Digest32::of_parts(&[
                b"hepta.agentd.v13-generation-witness.v1\0",
                &binding,
            ]),
            objective_digest: Digest32::from_array(generation.task_digest),
        },
        worker_generation,
        config.max_records as usize,
    )
    .map_err(invalid)?;
    let mut journal = CellGenerationJournalV2::open(
        files.journal,
        witness,
        generation.clone(),
        config.max_records,
    )
    .map_err(invalid)?;
    // The preparation receipt is stable for this prepared worker. Exact replay
    // on reopen appends nothing; newly performed preparation is a new cost.
    journal
        .record_cost(
            worker
                .preparation_cost(CellTaskCostIdentityV2 {
                    task_digest: generation.task_digest,
                    source_digest: generation.manifest.source_digest,
                })
                .map_err(invalid)?,
        )
        .map_err(invalid)?;
    let clock = worker.clock();
    let worker_for_control = Arc::clone(worker);
    let port = ControlledCellGenerationPortV2::spawn(
        control,
        ControlledCellGenerationConfigV2 {
            scope: generation.initial.scope.clone(),
            manifest: generation.manifest.clone(),
            worker_generation: worker_generation.get(),
            queue_capacity: config.queue_capacity,
            rpc_timeout: config.rpc_timeout,
        },
        worker_for_control,
        Arc::clone(&clock),
    )
    .map_err(invalid)?;
    neuron_generation_channel_v2(
        identity,
        journal,
        port,
        move || clock(),
        config.queue_capacity,
    )
}

/// Shared preflight for typed capabilities and ordinary descriptor loading.
/// The pathname loader must call this before creating any writable owner file.
pub(crate) fn validate_bootstrap(
    identity: &AgentdIdentity,
    config: &AgentdV13GenerationBootstrapConfigV1,
    prepared: &AgentdV13GenerationWorkerV1,
) -> Result<Generation, AgentdError> {
    let generation = &config.generation;
    let worker = &prepared.worker;
    if identity.spawn_generation == 0
        || config.expected_identity_digest
            != neuron_generation_process_identity_digest_v1(identity)?
        || config.expected_boot_id_digest != prepared.boot_id_digest
        || prepared.boot_id_digest
            != Digest32::of_parts(&[
                b"hepta.agentd.v13-generation-clock.v1\0",
                boot_id()?.as_bytes(),
            ])
        || generation.initial.scope.agent_id != identity.agent_id.as_str()
    {
        return Err(AgentdError::GenerationFenced(
            "V13 host identity or Linux boot epoch differs".into(),
        ));
    }
    generation.initial.digest().map_err(invalid)?;
    worker
        .validate_manifest(&generation.manifest)
        .map_err(invalid)?;
    if !(8..=4096).contains(&config.max_records)
        || !(1..=16_384).contains(&config.control_capacity)
        || !(1..=64).contains(&config.queue_capacity)
        || !(Duration::from_millis(10)..=Duration::from_secs(5)).contains(&config.rpc_timeout)
        || generation.initial.manifest_digest != generation.manifest.digest().map_err(invalid)?
        || generation.initial.revision != 0
        || !generation.initial.state.is_empty()
        || !generation.initial.prefix.is_empty()
        || generation.initial.stopped
        || generation.task_digest == [0; 32]
        || generation.source_frontier != worker.learning_closure().source_version
    {
        return Err(invalid("invalid V13 limits or genesis/learning binding"));
    }
    let worker_generation = Generation::new(generation.initial.writer_epoch).map_err(invalid)?;
    boottime_micros()?;
    Ok(worker_generation)
}

fn validate_files(
    files: &V13GenerationOwnerFilesV1,
    mode: V13GenerationOwnerModeV1,
    assets: &[(u64, u64)],
) -> Result<(), AgentdError> {
    let mut identities = assets.to_vec();
    for (index, file) in [&files.journal, &files.witness, &files.control]
        .iter()
        .enumerate()
    {
        let metadata = file.metadata()?;
        let identity = (metadata.dev(), metadata.ino());
        // SAFETY: the borrowed File keeps this descriptor valid; F_GETFL reads
        // its actual status flags without pointers or descriptor mutation.
        let flags = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFL) };
        if !metadata.is_file()
            || metadata.mode() & 0o022 != 0
            || identities.contains(&identity)
            || flags < 0
            || flags & libc::O_ACCMODE != libc::O_RDWR
            || (flags & libc::O_APPEND != 0) != (index == 2)
        {
            return Err(invalid(
                "V13 owner descriptors must be distinct regular read/write files with exact append mode",
            ));
        }
        match mode {
            V13GenerationOwnerModeV1::InitializeEmpty if metadata.len() != 0 => {
                return Err(invalid("V13 initialization refuses existing owner history"));
            }
            V13GenerationOwnerModeV1::Reopen if index != 2 && metadata.len() == 0 => {
                return Err(invalid("V13 reopen requires nonempty journal and witness"));
            }
            V13GenerationOwnerModeV1::InitializeEmpty | V13GenerationOwnerModeV1::Reopen => {}
        }
        identities.push(identity);
    }
    Ok(())
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}

#[cfg(test)]
#[path = "neuron_v13_generation_bootstrap_tests.rs"]
mod tests;
