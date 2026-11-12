//! Explicit Root CLI composition from the original private deployment files.
//! Real peer progress is matched against independent Root-approved materials.
//! The original host owns every capability and actual acknowledgement.

use super::*;
use super::super::generation_initial::RootGenerationInitialDeploymentFilesV1;
use super::super::generation_publication::deployment::files;
use super::super::generation_publication::deployment::files::DirectoryPin;
use super::super::generation_publication::deployment::files::MetadataFile;
use super::super::generation_publication::deployment::phase_inputs::OriginalCurrentPhaseFiles;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::io::Write;
use std::os::unix::net::UnixDatagram;
use std::path::PathBuf;
use std::sync::mpsc;

#[path = "authority_host_same_actor_q24_deployment_bridge.rs"]
mod bridge;
#[path = "authority_host_same_actor_q24_deployment_progress.rs"]
mod progress;

use crate::same_actor_q24_deployment_protocol::OriginalDeploymentStage as DeploymentStage;

/// Each slot consumes one real inherited descriptor. The CLI claims all four
/// before opening material or a runtime; no path or numeric PID substitutes.
pub struct RootSameActorDeploymentHandoffsV1 {
    pub writer: UnixDatagram,
    pub phase: UnixDatagram,
    pub scoped: UnixDatagram,
    pub root_pidfd: OwnedFd,
}

const DEPLOYMENT_PURPOSE: &str = "hepta.same-actor-q24-phase.deployment.v1";

#[derive(Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum RootWorkerRetirementMode {
    OriginalRootWorkers,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct DeploymentData {
    schema_version: u32,
    initial_deployment: PathBuf,
    publication_deployment: PathBuf,
    q24_model_reservation: PathBuf,
    learning_profile: PathBuf,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    root_worker_retirement: Option<RootWorkerRetirementMode>,
}

/// Public output contains correlation data only. It does not make a listener
/// ready or approve material; all actual registration remains one-shot.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct DeploymentSession {
    purpose: String,
    schema_version: u32,
    phase: String,
    root_pid: u32,
    root_boot_id: String,
    root_start_ticks: u64,
    consumer_identity: String,
    root_end_boottime_ns: u64,
    descriptor_digest: String,
    initial_descriptor_digest: String,
    publication_descriptor_digest: String,
    model_reservation_digest: String,
    progress_socket: PathBuf,
}

struct DeploymentFiles {
    config: MetadataFile,
    registration: MetadataFile,
    descriptor: MetadataFile,
    data: DeploymentData,
    model: MetadataFile,
    directories: Vec<DirectoryPin>,
    initial: RootGenerationInitialDeploymentFilesV1,
    current: OriginalCurrentPhaseFiles,
    current_directory: Arc<RootAuthorityDirectory>,
    consumer_uid: u32,
    session: DeploymentSession,
}

impl PreparedRootSameActorQ24PhaseV1 {
    /// Actual fresh-only Root CLI entry. Every late wait uses the deadline
    /// captured here before the original service is opened. The old deployment
    /// waiters are not used, and no mode silently falls back to Recover.
    pub async fn serve_fresh_original_deployment(
        config_file: &Path,
        registration_file: &Path,
        owner_pidfd: OwnedFd,
        deployment_file: &Path,
        handoffs: RootSameActorDeploymentHandoffsV1,
    ) -> io::Result<()> {
        crate::authority_host_service::generation_initial::original_root()?;
        let config: HostAuthorityServiceConfig = read_root_json(config_file)?;
        let deadline = SameActorPhaseDeadline::at_original_service_start(
            std::time::Duration::from_millis(config.lifetime_ms),
        )?;
        let (config_pin, _) = MetadataFile::open_metadata(config_file)?;
        let (registration_pin, _) = MetadataFile::open_metadata(registration_file)?;
        let (descriptor, bytes) = MetadataFile::open_metadata(deployment_file)?;
        let data: DeploymentData = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if data.schema_version != 1 {
            return Err(io::Error::other("original phase deployment version required"));
        }
        if data.root_worker_retirement.is_some()
            && serde_json::to_vec(&data).map_err(io::Error::other)? != bytes
        {
            return Err(io::Error::other("canonical Root-owned retirement deployment required"));
        }
        require_distinct_deployment_paths(&[
            config_file, registration_file, deployment_file, &data.initial_deployment,
            &data.publication_deployment, &data.q24_model_reservation,
            &data.learning_profile,
        ])?;
        let directories = vec![
            DirectoryPin::capture_root(files::parent(&data.learning_profile)?)?,
        ];
        let (model_pin, model_bytes) = MetadataFile::open_metadata(&data.q24_model_reservation)?;
        let model: crate::HostAuthorityQ24ModelFactoryReservationV1 =
            serde_json::from_slice(&model_bytes).map_err(io::Error::other)?;
        config_pin.require_metadata_unchanged()?;
        registration_pin.require_metadata_unchanged()?;
        descriptor.require_metadata_unchanged()?;
        model_pin.require_metadata_unchanged()?;
        require_original_startup_deadline(deadline)?;
        let original = PreparedHostAuthoritySession::prepare_fresh_from_registered(
            config_file, registration_file, owner_pidfd,
        ).await?;
        // The original filesystem handoff creates the consumer parent. Loading
        // Initial before this point would demand a nonexistent schema3 parent.
        // Any later error preserves the already prepared original state.
        let prepared = (|| {
            require_original_startup_deadline(deadline)?;
            let (original, consumer_root) = original.handoff_fresh_agent_filesystem()?;
            require_original_startup_deadline(deadline)?;
            let initial = RootGenerationInitialDeploymentFilesV1::open_original_initial_deployment(
                &data.initial_deployment,
            )?;
            if initial.original_phase_initial_consumer_root() != consumer_root {
                return Err(io::Error::other(
                    "Initial deployment must name the actual fresh consumer parent",
                ));
            }
            let current_directory = initial.original_phase_initial_current()?;
            let current = OriginalCurrentPhaseFiles::open_current_phase_descriptor(
                &data.publication_deployment,
                initial.original_phase_initial_current_path(),
                &consumer_root,
            )?;
            require_distinct_deployment_paths(&[
                config_file, registration_file, deployment_file, &data.initial_deployment,
                &data.publication_deployment, &data.q24_model_reservation,
                &data.learning_profile,
                initial.original_phase_initial_trigger(),
                current.current_phase_trigger(), current.current_phase_material(),
            ])?;
            require_original_startup_deadline(deadline)?;
            let phase = Self::capture_original_phase(
                original, config, deadline, Arc::clone(&current_directory),
                initial.deployment().clone(), model,
            )?;
            let session = DeploymentSession {
                purpose: DEPLOYMENT_PURPOSE.into(),
                schema_version: 1,
                phase: phase.descriptor.phase.clone(),
                root_pid: phase.descriptor.original.root.pid,
                root_boot_id: phase.descriptor.original.root.boot_id.clone(),
                root_start_ticks: phase.descriptor.original.root.process_start_ticks,
                consumer_identity: phase.descriptor.original.identity.clone(),
                root_end_boottime_ns: phase.gate.deadline().boottime_ns(),
                descriptor_digest: descriptor.digest().to_string(),
                initial_descriptor_digest: initial.original_phase_initial_digest().to_string(),
                publication_descriptor_digest: current.current_phase_descriptor_digest().to_string(),
                model_reservation_digest: model_pin.digest().to_string(),
                progress_socket: crate::same_actor_q24_deployment_protocol::original_deployment_socket(
                    &phase.descriptor,
                )?,
            };
            let files = DeploymentFiles {
                config: config_pin, registration: registration_pin, descriptor, data,
                model: model_pin, directories, initial, current, current_directory,
                consumer_uid: phase.original.config.peer_uid, session,
            };
            files.require_deployment_files()?;
            phase.gate.require_open()?;
            Ok::<_, io::Error>((phase, files, consumer_root))
        })().map_err(|error| deployment_uncertain("fresh original state preparation", error))?;
        let (phase, files, consumer_root) = prepared;
        serve_deployment(phase, files, consumer_root, handoffs)
    }
}

impl DeploymentFiles {
    fn require_deployment_files(&self) -> io::Result<()> {
        self.config.require_metadata_unchanged()?;
        self.registration.require_metadata_unchanged()?;
        self.descriptor.require_metadata_unchanged()?;
        self.model.require_metadata_unchanged()?;
        for directory in &self.directories {
            directory.require_directory()?;
        }
        self.initial.require_original_phase_initial_files()?;
        self.current.require_current_phase_files()
    }
}

fn require_original_startup_deadline(deadline: SameActorPhaseDeadline) -> io::Result<()> {
    let boot = crate::root_observation_cache::boottime_ns().map_err(io::Error::other)?;
    if Instant::now() >= deadline.instant() || boot >= deadline.boottime_ns() {
        return Err(io::Error::new(
            io::ErrorKind::TimedOut,
            "original phase startup deadline elapsed",
        ));
    }
    Ok(())
}

fn require_distinct_deployment_paths(paths: &[&Path]) -> io::Result<()> {
    for (index, path) in paths.iter().enumerate() {
        files::require_absolute(path)?;
        if paths[..index].contains(path) {
            return Err(io::Error::other("phase deployment slots require distinct original paths"));
        }
    }
    Ok(())
}

fn serve_deployment(
    phase: PreparedRootSameActorQ24PhaseV1,
    files: DeploymentFiles,
    consumer_root: PathBuf,
    handoffs: RootSameActorDeploymentHandoffsV1,
) -> io::Result<()> {
    if files.data.root_worker_retirement.is_some() {
        return serve_deployment_for_root_retirement(phase, files, consumer_root, handoffs);
    }
    let gate = Arc::clone(&phase.gate);
    let _closing = CloseSameActorPhaseOnDrop::new(&gate);
    files.require_deployment_files()?;
    gate.require_open()?;
    // Exactly this service's original held writer file, with the original full
    // peer verification before and after. Both checks use the captured end.
    verify_pinned_process(
        &phase.original.registration, phase.original.config.peer_uid,
        phase.original.config.peer_gid, &phase.original.owner_pidfd,
        gate.deadline().instant(),
    )?;
    let registered_writer = phase.original.service.original_root_writer_descriptor()?;
    verify_pinned_process(
        &phase.original.registration, phase.original.config.peer_uid,
        phase.original.config.peer_gid, &phase.original.owner_pidfd,
        gate.deadline().instant(),
    )?;
    gate.require_open()?;
    let progress = progress::BoundDeploymentProgress::bind(&phase)?;
    let timeout = std::time::Duration::from_millis(phase.original.config.timeout_ms.min(500));
    let (commands, received_commands) = mpsc::sync_channel(1);
    let (acknowledgements, received_acknowledgements) = mpsc::sync_channel(1);
    let inputs = RootSameActorHostInputsV1 {
        writer_handoff: handoffs.writer,
        phase_handoff: handoffs.phase,
        scoped_handoff: handoffs.scoped,
        registered_writer,
        root_pidfd: handoffs.root_pidfd,
        consumer_state_root: consumer_root,
        timeout,
        commands: received_commands,
        acknowledgements,
    };
    // Correlation is not readiness. The actual daemon first opens its original
    // five lanes, then connects and reports InputsOpened on the separate lane.
    report_original_session(&files.session)?;
    std::thread::scope(|threads| {
        let _scope_close = CloseSameActorPhaseOnDrop::new(&gate);
        let bridge_gate = Arc::clone(&gate);
        let material_bridge = threads.spawn(move || {
            progress.serve_original(
                files, commands, received_acknowledgements, bridge_gate,
            )
        });
        let served = phase.serve_original_same_actor_host(inputs);
        gate.close();
        let supplied = material_bridge.join()
            .map_err(|_| io::Error::other("original phase material bridge panicked"))?;
        match (served, supplied) {
            (Err(source), Err(bridge)) => Err(io::Error::other(DeploymentServeError {
                source, bridge,
            })),
            (Err(source), Ok(())) => Err(source),
            (Ok(()), result) => result,
        }
    })
}

fn report_original_session(session: &DeploymentSession) -> io::Result<()> {
    let stdout = std::io::stdout();
    let mut output = stdout.lock();
    let value = serde_json::to_string(session).map_err(io::Error::other)?;
    writeln!(output, "{{\"same_actor_deployment_session\":{value}}}")?;
    output.flush()
}

#[derive(Debug)]
struct DeploymentUncertain {
    stage: &'static str,
    source: io::Error,
}

impl std::fmt::Display for DeploymentUncertain {
    fn fmt(&self, output: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(output, "{} may already have taken effect; original outcome uncertain: {}",
            self.stage, self.source)
    }
}

impl std::error::Error for DeploymentUncertain {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(&self.source)
    }
}

fn deployment_uncertain(stage: &'static str, source: io::Error) -> io::Error {
    io::Error::other(DeploymentUncertain { stage, source })
}

#[derive(Debug)]
struct DeploymentServeError {
    source: io::Error,
    bridge: io::Error,
}

impl std::fmt::Display for DeploymentServeError {
    fn fmt(&self, output: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(output, "original Root serving failed: {}; material bridge: {}",
            self.source, self.bridge)
    }
}

impl std::error::Error for DeploymentServeError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(&self.source)
    }
}

#[cfg(test)]
#[path = "authority_host_same_actor_q24_deployment_tests.rs"]
mod tests;


pub(super) struct OriginalRootDeploymentJoined {
    // Both came back from actual scopes/threads. Keep real Root materials and
    // registrations until the final ACK; release the original service last.
    materials: progress::OriginalRootRetainedDeployment,
    host: host::OriginalRootHostJoined,
}

impl OriginalRootDeploymentJoined {
    pub(super) fn require_original(
        &self,
        retirement: &crate::OriginalRootRetirementScope,
    ) -> io::Result<()> {
        self.materials.require_original(retirement)?;
        self.host.require_original(retirement)
    }
}

/// Constructed below only after the actual deadline watcher has also joined.
pub(super) struct OriginalRootAllWorkersJoined {
    joined: OriginalRootDeploymentJoined,
}

impl OriginalRootAllWorkersJoined {
    pub(super) fn require_original(
        &self,
        retirement: &crate::OriginalRootRetirementScope,
    ) -> io::Result<()> {
        self.joined.require_original(retirement)
    }
}

fn serve_deployment_for_root_retirement(
    phase: PreparedRootSameActorQ24PhaseV1,
    files: DeploymentFiles,
    consumer_root: PathBuf,
    handoffs: RootSameActorDeploymentHandoffsV1,
) -> io::Result<()> {
    let gate = Arc::clone(&phase.gate);
    let mut closing = CloseSameActorPhaseOnDrop::new(&gate);
    files.require_deployment_files()?;
    if !matches!(
        files.data.root_worker_retirement,
        Some(RootWorkerRetirementMode::OriginalRootWorkers)
    ) {
        return Err(io::Error::other("explicit Root-owned worker retirement required"));
    }
    let retirement = retirement::OriginalRootRetirementScope::from_original_phase(&phase)?;
    verify_pinned_process(
        &phase.original.registration, phase.original.config.peer_uid,
        phase.original.config.peer_gid, &phase.original.owner_pidfd,
        gate.deadline().instant(),
    )?;
    let registered_writer = phase.original.service.original_root_writer_descriptor()?;
    verify_pinned_process(
        &phase.original.registration, phase.original.config.peer_uid,
        phase.original.config.peer_gid, &phase.original.owner_pidfd,
        gate.deadline().instant(),
    )?;
    gate.require_open()?;
    let progress = progress::BoundDeploymentProgress::bind(&phase)?;
    let timeout = std::time::Duration::from_millis(phase.original.config.timeout_ms.min(500));
    let (commands, received_commands) = mpsc::sync_channel(1);
    let (acknowledgements, received_acknowledgements) = mpsc::sync_channel(1);
    let inputs = RootSameActorHostInputsV1 {
        writer_handoff: handoffs.writer,
        phase_handoff: handoffs.phase,
        scoped_handoff: handoffs.scoped,
        registered_writer,
        root_pidfd: handoffs.root_pidfd,
        consumer_state_root: consumer_root,
        timeout,
        commands: received_commands,
        acknowledgements,
    };
    report_original_session(&files.session)?;
    let result = std::thread::scope(|threads| {
        let mut scope_close = CloseSameActorPhaseOnDrop::new(&gate);
        // This watcher remains live through every actual service, host and
        // material-bridge join. Its private stop input requires their owners.
        let watcher = threads.spawn(|| retirement.watch_original_deadline());
        let bridge_retirement = Arc::clone(&retirement);
        let material_bridge = threads.spawn(move || {
            progress.serve_for_original_root_retirement(
                files, commands, received_acknowledgements, bridge_retirement,
            )
        });
        let served = phase.serve_original_same_actor_host_for_retirement(inputs, &retirement);
        if served.is_err() {
            gate.close();
        }
        let supplied = join_original_retirement_thread(
            material_bridge,
            &gate,
            "original phase material bridge panicked",
        );
        let assembled = (|| {
            let host = match (served, supplied) {
                (Err(source), Err(bridge)) => {
                    return Err(io::Error::other(DeploymentServeError { source, bridge }));
                }
                (Err(source), Ok(_)) => return Err(source),
                (Ok(_), Err(bridge)) => return Err(bridge),
                (Ok(host), Ok(supplied)) => (host, supplied),
            };
            let (host, supplied) = host;
            let (peer, materials) =
                progress::OriginalRootRetirementHandoff::into_original_parts(supplied, &retirement)?;
            let joined = OriginalRootDeploymentJoined { materials, host };
            joined.require_original(&retirement)?;
            retirement.stop_original_deadline_worker(&joined)?;
            Ok::<_, io::Error>((peer, joined))
        })();
        if assembled.is_err() {
            gate.close();
        }
        let watched = join_original_retirement_thread(
            watcher,
            &gate,
            "original Root deadline worker panicked",
        );
        let (peer, joined) = assembled?;
        watched?;
        let joined = OriginalRootAllWorkersJoined { joined };
        joined.require_original(&retirement)?;
        // The same peer is still in the shutdown registry. Any validation,
        // framing, deadline or owner error consumes and closes it. No generic
        // EOF can become this explicit actual-worker acknowledgement.
        let acknowledged = peer.acknowledge_original_joined(&joined);
        gate.close();
        acknowledged?;
        drop(joined);
        scope_close.disarm();
        Ok::<_, io::Error>(())
    });
    if result.is_ok() {
        closing.disarm();
    }
    result
}

fn join_original_retirement_thread<T>(
    worker: std::thread::ScopedJoinHandle<'_, io::Result<T>>,
    gate: &Arc<SameActorPhaseGate>,
    panic_message: &'static str,
) -> io::Result<T> {
    // The actual owned handle is consumed here. A returned owner stays in T;
    // no status/count or peer message can replace this physical thread join.
    let joined = worker
        .join()
        .map_err(|_| io::Error::other(panic_message))
        .and_then(|result| result);
    if joined.is_err() {
        gate.close();
    }
    joined
}

#[cfg(test)]
#[path = "authority_host_same_actor_q24_retirement_tests.rs"]
mod retirement_tests;
