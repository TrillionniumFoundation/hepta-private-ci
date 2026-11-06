//! Shared actual-file and Linux-epoch checks for ordinary and guarded V13 owners.
//! These values remain inside Agentd; no checked file or raw worker is unsealed
//! to a caller between preflight, publication and runtime assembly.

use std::fs::File;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_neuron::CellCostEntryV2;
use codex_hepta_neuron::CellTaskCostIdentityV2;
use codex_hepta_neuron::ControlledCellGenerationConfigV2;
use codex_hepta_neuron::ControlledCellGenerationPortV2;
use codex_hepta_neuron::DurableInferenceControl;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::V13GenerationProcessWorkerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use super::AgentdV13GenerationBootstrapConfigV1;
use super::AgentdV13GenerationWorkerV1;
use super::V13GenerationOwnerFilesV1;
use super::V13GenerationOwnerModeV1;
use super::invalid;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::neuron_generation_process_bootstrap::identity_context_digest;
use crate::neuron_generation_process_bootstrap::linux::boot_id;
use crate::neuron_generation_process_bootstrap::linux::boottime_micros;
use crate::neuron_generation_process_identity_digest_v1;

pub(crate) type V13Clock = Arc<dyn Fn() -> u64 + Send + Sync>;

pub(crate) struct OpenedV13Owners {
    pub(crate) journal: File,
    pub(crate) witness: FileAnchorWitnessStore,
    pub(crate) backend: V13BackendOwner,
}

/// Owns the actual lower control lock and the admitted prepared worker. It has
/// no public constructor, clone or raw-control/worker extraction API.
pub(crate) struct V13BackendOwner {
    config: AgentdV13GenerationBootstrapConfigV1,
    worker: Arc<V13GenerationProcessWorkerV1>,
    control: DurableInferenceControl,
}

impl V13BackendOwner {
    pub(crate) fn configuration(&self) -> &AgentdV13GenerationBootstrapConfigV1 {
        &self.config
    }

    pub(crate) fn validate_identity(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        validate_configuration(
            identity,
            &self.config,
            self.config.expected_boot_id_digest,
            &self.worker,
        )?;
        Ok(())
    }

    pub(crate) fn preparation_cost(&self) -> Result<CellCostEntryV2, AgentdError> {
        self.worker.preparation_cost(CellTaskCostIdentityV2 {
            task_digest: self.config.generation.task_digest,
            source_digest: self.config.generation.manifest.source_digest,
        }).map_err(invalid)
    }

    pub(crate) fn spawn(self) -> Result<(ControlledCellGenerationPortV2, V13Clock), AgentdError> {
        let clock = self.worker.clock();
        let port = ControlledCellGenerationPortV2::spawn(
            self.control,
            ControlledCellGenerationConfigV2 {
                scope: self.config.generation.initial.scope,
                manifest: self.config.generation.manifest,
                worker_generation: self.config.generation.initial.writer_epoch,
                queue_capacity: self.config.queue_capacity,
                rpc_timeout: self.config.rpc_timeout,
            },
            self.worker,
            Arc::clone(&clock),
        ).map_err(invalid)?;
        Ok((port, clock))
    }
}

fn validate_configuration(
    identity: &AgentdIdentity,
    config: &AgentdV13GenerationBootstrapConfigV1,
    prepared_boot_id: Digest32,
    worker: &V13GenerationProcessWorkerV1,
) -> Result<Generation, AgentdError> {
    let generation = &config.generation;
    if identity.spawn_generation == 0
        || config.expected_identity_digest
            != neuron_generation_process_identity_digest_v1(identity)?
        || config.expected_boot_id_digest != prepared_boot_id
        || prepared_boot_id
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

pub(crate) fn open_owners(
    identity: &AgentdIdentity,
    config: AgentdV13GenerationBootstrapConfigV1,
    files: V13GenerationOwnerFilesV1,
    mode: V13GenerationOwnerModeV1,
    prepared: &AgentdV13GenerationWorkerV1,
) -> Result<OpenedV13Owners, AgentdError> {
    let worker_generation = validate_configuration(
        identity, &config, prepared.boot_id_digest, &prepared.worker,
    )?;
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
    Ok(OpenedV13Owners {
        journal: files.journal,
        witness,
        backend: V13BackendOwner {
            config,
            worker: Arc::clone(worker),
            control,
        },
    })
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


