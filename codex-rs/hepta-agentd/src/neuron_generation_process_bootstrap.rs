//! Explicit process assembly for the existing Joint and V13 generation owners. A pinned
//! descriptor is host configuration, not an artifact adoption/signing authority.
//! Reopen never falls back to fresh files or a new clock epoch.

use std::path::Path;

use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::NeuronGenerationRuntimeBootstrapV2;
use crate::NeuronGenerationRuntimeHandleV2;

#[cfg(target_os = "linux")]
#[path = "neuron_generation_process_bootstrap_files.rs"]
mod files;

#[cfg(target_os = "linux")]
#[path = "neuron_v13_generation_process_bootstrap.rs"]
mod v13;

/// Bind every field of the host's actual identity, including the complete path
/// layout and resource budget. This content digest is not an authority grant.
pub fn neuron_generation_process_identity_digest_v1(
    identity: &AgentdIdentity,
) -> Result<Digest32, AgentdError> {
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.generation-process-identity.v1\0",
        identity_context_digest(identity)?.as_array(),
        &identity.spawn_generation.to_be_bytes(),
    ]))
}

pub(crate) fn identity_context_digest(identity: &AgentdIdentity) -> Result<Digest32, AgentdError> {
    let layout = &identity.layout;
    let paths = [
        layout.agent_root(),
        layout.agent_config(),
        layout.home_root(),
        layout.run_root(),
        layout.agentd_control_socket(),
        layout.matrixd_control_socket(),
        layout.app_server_socket(),
        layout.writer_lock(),
        layout.generation_cursor(),
        layout.matrixd_process_lease(),
        layout.logs_root(),
        layout.releases_root(),
        layout.active_release(),
        layout.cognitive_root(),
        layout.matrix_root(),
        layout.matrix_public_binding(),
        layout.matrix_secrets_root(),
        layout.automation_root(),
    ];
    let bytes = serde_json::to_vec(&(
        identity.agent_id.as_str(),
        layout.agent_id().as_str(),
        paths,
        &identity.fleet_root,
        &identity.workspace,
        &identity.resources,
        &identity.home_root,
        &identity.run_root,
        &identity.control_socket,
        &identity.app_server_socket,
    ))?;
    Ok(Digest32::of_parts(&[
        b"hepta.agentd.generation-process-context.v1\0",
        &bytes,
    ]))
}

/// Reconstruct an explicitly selected Joint or V13 worker, the existing durable control,
/// exclusive Cell journal and separately retained witness. No model is run by
/// this loader. The handle must remain live until the caller enables the
/// bootstrap's explicit control endpoint or otherwise retains the typed handle.
pub fn load_neuron_generation_process_bootstrap_v1(
    path: &Path,
    expected_descriptor_digest: Digest32,
    identity: &AgentdIdentity,
) -> Result<
    (
        NeuronGenerationRuntimeHandleV2,
        NeuronGenerationRuntimeBootstrapV2,
    ),
    AgentdError,
> {
    #[cfg(target_os = "linux")]
    {
        linux::load(path, expected_descriptor_digest, identity)
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (path, expected_descriptor_digest, identity);
        Err(AgentdError::Invalid(
            "generation process bootstrap requires Linux".into(),
        ))
    }
}

#[cfg(target_os = "linux")]
pub(crate) mod linux {
    use std::path::Path;
    use std::path::PathBuf;
    use std::sync::Arc;
    use std::time::Duration;

    use codex_hepta_neuron::CellGenerationConfigV2;
    use codex_hepta_neuron::CellGenerationJournalV2;
    use codex_hepta_neuron::ControlledCellGenerationConfigV2;
    use codex_hepta_neuron::ControlledCellGenerationPortV2;
    use codex_hepta_neuron::DurableInferenceControl;
    use codex_hepta_neuron::FileAnchorWitnessStore;
    use codex_hepta_neuron::JointGenerationProcessConfigV1;
    use codex_hepta_neuron::JointGenerationProcessFilesV1;
    use codex_hepta_neuron::JointGenerationProcessWorkerV1;
    use codex_hepta_neuron::JournalScope;
    use codex_hepta_types::Generation;
    use serde::Deserialize;

    use super::*;
    use crate::neuron_generation_channel_v2;

    const SCHEMA: &str = "hepta.agentd.neuron-generation-bootstrap.v1";
    const MAX_DESCRIPTOR_BYTES: u64 = 262_144;

    #[derive(Deserialize)]
    struct Schema {
        schema: String,
    }

    #[derive(Clone, Copy, Deserialize)]
    #[serde(rename_all = "snake_case")]
    pub(super) enum OpenMode {
        Create,
        Reopen,
    }

    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    pub(super) struct Asset {
        pub path: PathBuf,
        pub digest: String,
    }

    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    pub(super) struct Descriptor {
        schema: String,
        identity_digest: String,
        boot_id: String,
        pub mode: OpenMode,
        pub journal_path: PathBuf,
        pub witness_path: PathBuf,
        pub control_path: PathBuf,
        max_records: u64,
        worker_generation: u64,
        control_capacity: usize,
        queue_capacity: usize,
        rpc_timeout_millis: u64,
        config: CellGenerationConfigV2,
        pub executable: Asset,
        pub weights: Asset,
        pub public: Asset,
    }

    pub(super) fn load(
        path: &Path,
        expected_digest: Digest32,
        identity: &AgentdIdentity,
    ) -> Result<
        (
            NeuronGenerationRuntimeHandleV2,
            NeuronGenerationRuntimeBootstrapV2,
        ),
        AgentdError,
    > {
        let (bytes, descriptor_file) = files::read_bounded(path, MAX_DESCRIPTOR_BYTES)?;
        if expected_digest.is_zero() || Digest32::of_bytes(&bytes) != expected_digest {
            return Err(invalid("generation bootstrap descriptor digest mismatch"));
        }
        // Dispatch only after pinning the original bounded bytes. Each branch
        // then decodes its entire strict descriptor; unknown schemas never fall back.
        let header: Schema = serde_json::from_slice(&bytes)?;
        match header.schema.as_str() {
            SCHEMA => {}
            v13::SCHEMA => return v13::load(path, &bytes, descriptor_file, identity),
            _ => return Err(invalid("unsupported generation bootstrap schema")),
        }
        let d: Descriptor = serde_json::from_slice(&bytes)?;
        if identity.spawn_generation == 0
            || d.schema != SCHEMA
            || parse_digest(&d.identity_digest)?
                != neuron_generation_process_identity_digest_v1(identity)?
            || d.boot_id != boot_id()?
            || d.config.initial.scope.agent_id != identity.agent_id.as_str()
        {
            return Err(AgentdError::GenerationFenced(
                "generation descriptor identity or clock epoch differs".into(),
            ));
        }
        d.config.initial.digest().map_err(invalid)?;
        if !(6..=4096).contains(&d.max_records)
            || !(1..=16_384).contains(&d.control_capacity)
            || !(1..=64).contains(&d.queue_capacity)
            || !(10..=5000).contains(&d.rpc_timeout_millis)
            || d.worker_generation != d.config.initial.writer_epoch
            || d.config.initial.manifest_digest != d.config.manifest.digest().map_err(invalid)?
            || d.config.initial.revision != 0
            || !d.config.initial.state.is_empty()
            || !d.config.initial.prefix.is_empty()
            || d.config.initial.stopped
            || d.config.task_digest == [0; 32]
            || d.config.source_frontier == [0; 32]
        {
            return Err(invalid(
                "invalid generation bootstrap limits or genesis binding",
            ));
        }
        let owner_paths = [d.journal_path.as_path(), &d.witness_path, &d.control_path];
        files::validate_paths(
            d.mode,
            &[path, &d.executable.path, &d.weights.path, &d.public.path],
            owner_paths,
        )?;
        boottime_micros()?;
        // Zero is an invalid clock sample, never an invented successful time.
        // Admission rejects it and the native process refuses zero before spawn.
        let clock: Arc<dyn Fn() -> u64 + Send + Sync> = Arc::new(|| boottime_micros().unwrap_or(0));
        let open_worker = match d.config.manifest.profile.as_str() {
            JointGenerationProcessWorkerV1::PROFILE => JointGenerationProcessWorkerV1::open_files,
            JointGenerationProcessWorkerV1::RESIDENT_PROFILE => {
                JointGenerationProcessWorkerV1::open_resident_files
            }
            _ => return Err(invalid("unsupported Joint generation process profile")),
        };
        let assets = files::open_assets(&d)?;
        let worker = Arc::new(
            open_worker(
                JointGenerationProcessConfigV1 {
                    executable: d.executable.path.clone(),
                    executable_digest: parse_digest(&d.executable.digest)?.into_array(),
                    source_digest: d.config.manifest.source_digest,
                    weights: d.weights.path.clone(),
                    weights_digest: parse_digest(&d.weights.digest)?.into_array(),
                    public: d.public.path.clone(),
                    public_digest: parse_digest(&d.public.digest)?.into_array(),
                    device_digest: d.config.manifest.device_digest,
                },
                JointGenerationProcessFilesV1 {
                    executable: assets.executable.try_clone()?,
                    weights: assets.weights.try_clone()?,
                    public: assets.public.try_clone()?,
                },
                Arc::clone(&clock),
            )
            .map_err(invalid)?,
        );
        worker
            .validate_manifest(&d.config.manifest)
            .map_err(invalid)?;
        // No mutable owner file is created before the descriptor, identity,
        // clock, paths and actual executable/assets have passed validation.
        let binding = serde_json::to_vec(&(
            identity_context_digest(identity)?.to_string(),
            &d.boot_id,
            &d.config,
            d.max_records,
            d.worker_generation,
            &d.journal_path,
            &d.witness_path,
            &d.control_path,
        ))?;
        let owners = files::open_owners(
            d.mode,
            owner_paths,
            &[
                &descriptor_file,
                &assets.executable,
                &assets.weights,
                &assets.public,
            ],
        )?;
        let control =
            DurableInferenceControl::open_file(owners.control, &d.control_path, d.control_capacity)
                .map_err(invalid)?;
        let witness = FileAnchorWitnessStore::open(
            owners.witness,
            JournalScope {
                scope_digest: Digest32::of_parts(&[
                    b"hepta.agentd.generation-process-witness.v1\0",
                    &binding,
                ]),
                objective_digest: Digest32::from_array(d.config.task_digest),
            },
            Generation::new(d.worker_generation).map_err(invalid)?,
            d.max_records as usize,
        )
        .map_err(invalid)?;
        let journal =
            CellGenerationJournalV2::open(owners.journal, witness, d.config.clone(), d.max_records)
                .map_err(invalid)?;
        let port = ControlledCellGenerationPortV2::spawn(
            control,
            ControlledCellGenerationConfigV2 {
                scope: d.config.initial.scope.clone(),
                manifest: d.config.manifest,
                worker_generation: d.worker_generation,
                queue_capacity: d.queue_capacity,
                rpc_timeout: Duration::from_millis(d.rpc_timeout_millis),
            },
            worker,
            Arc::clone(&clock),
        )
        .map_err(invalid)?;
        neuron_generation_channel_v2(identity, journal, port, move || clock(), d.queue_capacity)
    }

    pub(crate) fn boot_id() -> Result<String, AgentdError> {
        let bytes = std::fs::read("/proc/sys/kernel/random/boot_id")?;
        let value = std::str::from_utf8(&bytes).map_err(invalid)?.trim();
        if value.len() != 36
            || !value.bytes().enumerate().all(|(i, b)| {
                if [8, 13, 18, 23].contains(&i) {
                    b == b'-'
                } else {
                    b.is_ascii_hexdigit()
                }
            })
        {
            return Err(invalid("invalid Linux boot identity"));
        }
        Ok(value.to_owned())
    }

    pub(crate) fn boottime_micros() -> Result<u64, AgentdError> {
        let mut stamp = libc::timespec {
            tv_sec: 0,
            tv_nsec: 0,
        };
        // SAFETY: Linux CLOCK_BOOTTIME writes one valid stack timespec and
        // includes suspend time. The descriptor binds this system boot epoch.
        if unsafe { libc::clock_gettime(libc::CLOCK_BOOTTIME, &mut stamp) } != 0
            || stamp.tv_sec < 0
            || !(0..1_000_000_000).contains(&stamp.tv_nsec)
        {
            return Err(invalid("generation boot clock unavailable"));
        }
        (stamp.tv_sec as u64)
            .checked_mul(1_000_000)
            .and_then(|s| s.checked_add(stamp.tv_nsec as u64 / 1000))
            .filter(|value| *value > 0)
            .ok_or_else(|| invalid("generation boot clock overflow"))
    }

    pub(super) fn parse_digest(value: &str) -> Result<Digest32, AgentdError> {
        let digest = value.parse::<Digest32>().map_err(invalid)?;
        if digest.is_zero() {
            return Err(invalid("zero generation descriptor digest"));
        }
        Ok(digest)
    }

    pub(super) fn invalid(error: impl std::fmt::Display) -> AgentdError {
        AgentdError::Invalid(error.to_string())
    }
}

#[cfg(all(test, target_os = "linux"))]
#[path = "neuron_generation_process_bootstrap_tests.rs"]
mod tests;
