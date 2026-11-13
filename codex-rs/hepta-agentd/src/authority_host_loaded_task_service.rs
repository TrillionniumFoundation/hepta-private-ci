//! The loaded callback stays inside this private subtree. Only the original
//! remote task pump and its strengthened feature control can consume it.
//! All normally returning branches join the actual owned service threads.

use std::os::fd::OwnedFd;
use std::os::unix::net::{UnixDatagram, UnixStream};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use serde::Deserialize;
use tokio_util::sync::CancellationToken;

use super::PreparedRootHostLoadedQ24TaskV1;
use super::super::root_task::OriginalLoadedTaskFollowups;
use crate::{AgentdError, RootResidentCandidateEnrollmentInputsV3,
    RootResidentCandidateEnrollmentServiceV3, PreparedRootHostCircuitTaskV1,
    PreparedRootMaterialSourceHostV1};
use crate::authority_host_config::read_root_json;
use crate::authority_host_runtime::{OriginalTaskResidentInputs,
    OriginalTaskResidentPaths, OriginalTaskResidentPurpose};

/// Supervisor-owned descriptors only. Material must be a distinct actual
/// non-Root peer; an inherited socketpair created as Root cannot attest it.
/// The ten original roles arrive through the unchanged separate 21-right frame.
pub struct RootHostOriginalTaskLearningFilesV1 {
    pub production_handoff: UnixDatagram,
    pub task_handoff: UnixDatagram,
    pub original_task_root_pidfd: OwnedFd,
    pub resident: RootResidentCandidateEnrollmentInputsV3,
    pub material_stream: UnixStream,
    pub original_material_pidfd: OwnedFd,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ServiceFile {
    schema_version: u32,
    purpose: String,
    consumer_state_root: PathBuf,
    task_socket: PathBuf,
    loan_socket: PathBuf,
    task_nonce: [u8; 16],
    resident_deployment: PathBuf,
    resident_evidence_trust: PathBuf,
    prefreeze_disclosure: PathBuf,
}

impl PreparedRootHostLoadedQ24TaskV1 {
    /// Run the real ordinary task and enroll its later original candidate on
    /// the SAME Root session. This requires the real post-A Generator/Observer
    /// intake and signed freeze supplied by their owners; no data is invented
    /// when those owners have not completed that distinct stage.
    pub fn serve_loaded_original_task_and_resident(
        self, service_file: &Path, files: RootHostOriginalTaskLearningFilesV1,
    ) -> Result<(), AgentdError> {
        self.run_loaded_original_services(service_file, files, OriginalTaskResidentPurpose::Fresh)
    }

    /// The original existing task and V3 checkpoint remain readback-only where
    /// their original factories require it. Failure never selects Fresh again.
    pub fn recover_loaded_original_task_and_resident(
        self, service_file: &Path, files: RootHostOriginalTaskLearningFilesV1,
        original_resident_readback: &Path,
    ) -> Result<(), AgentdError> {
        self.run_loaded_original_services(service_file, files,
            OriginalTaskResidentPurpose::Readback(original_resident_readback.to_owned()))
    }

    fn run_loaded_original_services(
        mut self, service_file: &Path, files: RootHostOriginalTaskLearningFilesV1,
        purpose: OriginalTaskResidentPurpose,
    ) -> Result<(), AgentdError> {
        self.clock_status.require_healthy()?;
        self.read_loaded_original_root_task_generation()?;
        let specification: ServiceFile = read_root_json(service_file)?;
        if specification.schema_version != 1
            || specification.purpose != "hepta.root.same-task-material-resident.service.v1"
            || specification.task_nonce == [0; 16]
        { return Err(protocol("original Root service purpose differs")); }
        let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
        let (material_host, followups) = self.task.take_original_loader_followups()?;
        let startup_end = OriginalLoadedTaskFollowups::require_startup_end(&followups, Instant::now() + Duration::from_secs(30))?;
        self.clock_status.require_healthy()?;
        let RootHostOriginalTaskLearningFilesV1 { production_handoff, task_handoff,
            original_task_root_pidfd, resident, material_stream, original_material_pidfd } = files;
        let (material_registration, prefreeze) = OriginalLoadedTaskFollowups::prepare_prefreeze(&followups,
            &specification.prefreeze_disclosure, &specification.resident_evidence_trust,
            material_stream, original_material_pidfd, startup_end,
        )?;
        self.clock_status.require_healthy()?;
        let paths = OriginalTaskResidentPaths { deployment: specification.resident_deployment };
        let clock_status = self.clock_status;
        let mut task = self.task;
        std::thread::scope(|scope| {
            let (task_done_sender, mut task_done) = tokio::sync::oneshot::channel();
            let task_thread = scope.spawn(move || {
                let result = PreparedRootHostCircuitTaskV1::handoff_and_serve_original_root_circuit_task_before(
                    &mut task, production_handoff, task_handoff, original_task_root_pidfd,
                    &specification.consumer_state_root, specification.task_socket,
                    specification.loan_socket, specification.task_nonce, startup_end,
                );
                let _ = task_done_sender.send(());
                result
            });
            // Start the only Source lane before the late signed freeze is
            // required. The same client later enters the actual Material pair;
            // this export cannot also create a post-freeze Source connection.
            let (material_done_sender, mut material_done) = tokio::sync::oneshot::channel();
            let material_thread = scope.spawn(move || {
                let result = PreparedRootMaterialSourceHostV1::serve_original_prefreeze(material_host, material_registration);
                let _ = material_done_sender.send(());
                result
            });
            let work_result = runtime.block_on(async {
                let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
                let prepare = async {
                    let RootResidentCandidateEnrollmentInputsV3 { stage_handoff, enrollment_handoff,
                        original_root_pidfd, original_consumer_pidfd, baseline_files } = resident;
                    // Readability only wakes the receiver. The complete
                    // original frame, Root pin, purpose, recipient and roles
                    // must authenticate before any late deployment is read.
                    let stage_handoff = wait_original_stage_message(stage_handoff, startup_end).await?;
                    let remaining = startup_end.checked_duration_since(Instant::now())
                        .filter(|value| !value.is_zero()).ok_or_else(|| protocol("original stage deadline elapsed"))?;
                    let stage_transport = crate::root_production_handoff::receive_original_candidate_stage_transport(
                        stage_handoff, remaining)?;
                    clock_status.require_healthy()?;
                    let original = OriginalTaskResidentInputs {
                        stage_transport, enrollment_handoff, original_root_pidfd,
                        original_consumer_pidfd, baseline_files,
                    };
                    let prepared = OriginalLoadedTaskFollowups::prepare_resident(&followups, paths, original, &prefreeze, purpose, startup_end)?;
                    clock_status.require_healthy()?;
                    let service = crate::authority_host_runtime::OriginalTaskResidentPrepared::enroll(prepared).await?;
                    OriginalLoadedTaskFollowups::require_original_task_followups(&followups)?;
                    crate::authority_host_runtime::OriginalTaskPrefreezeState::require_original_prefreeze_trust(&prefreeze)?;
                    clock_status.require_healthy()?;
                    Ok::<_, AgentdError>(service)
                };
                tokio::pin!(prepare);
                let resident = tokio::select! {
                    biased;
                    value = &mut prepare => value?,
                    _ = &mut task_done => return Err(protocol("task service ended before resident enrollment; same-operation readback required")),
                    _ = &mut material_done => return Err(protocol("original Source service ended before resident enrollment; same-operation readback required")),
                    signal = tokio::signal::ctrl_c() => {
                        return merge_results(signal.map_err(AgentdError::from),
                            Err(protocol("original enrollment interrupted; effects Unknown, same-operation readback required")));
                    }
                    _ = terminate.recv() => return Err(protocol("original enrollment terminated; effects Unknown, same-operation readback required")),
                };
                let cancellation = CancellationToken::new();
                let resident_work = RootResidentCandidateEnrollmentServiceV3::run(resident, cancellation.clone());
                tokio::pin!(resident_work);
                let result = tokio::select! {
                    biased;
                    value = &mut resident_work => value,
                    _ = &mut task_done => {
                        cancellation.cancel();
                        merge_results(resident_work.await, Err(protocol("task service ended while candidate service was active")))
                    }
                    _ = &mut material_done => {
                        cancellation.cancel();
                        merge_results(resident_work.await, Err(protocol("Material service ended while candidate service was active")))
                    }
                    signal = tokio::signal::ctrl_c() => {
                        cancellation.cancel();
                        let result = resident_work.await;
                        merge_results(merge_results(result, signal.map_err(AgentdError::from)),
                            Err(protocol("original services interrupted; effects Unknown")))
                    }
                    _ = terminate.recv() => {
                        cancellation.cancel();
                        merge_results(resident_work.await, Err(protocol("original services terminated; effects Unknown")))
                    }
                };
                merge_results(merge_results(result, OriginalLoadedTaskFollowups::require_original_task_followups(&followups)), crate::authority_host_runtime::OriginalTaskPrefreezeState::require_original_prefreeze_trust(&prefreeze))
            });
            // Join actual submitted work, including error paths. No timeout,
            // abort or dropped future is relabeled as a completed thread.
            // Deadlines reject late results. Synchronous original I/O may
            // still block; no physical termination bound is asserted here.
            let task_result = task_thread.join().map_err(|_| protocol("original task service panicked; effects Unknown"))
                .and_then(|value| value.map(|_| ()));
            let material_result = material_thread.join().map_err(|_| protocol("original Material service panicked; effects Unknown"))
                .and_then(|value| value.map(|_| ()));
            merge_results(merge_results(merge_results(work_result, task_result), material_result),
                clock_status.require_healthy())
        })
    }
}

async fn wait_original_stage_message(socket: UnixDatagram, end: Instant) -> Result<UnixDatagram, AgentdError> {
    let remaining = end.checked_duration_since(Instant::now()).filter(|value| !value.is_zero())
        .ok_or_else(|| protocol("original stage startup ended"))?;
    crate::root_production_handoff::root_pair(&socket, remaining.min(Duration::from_secs(30)))?;
    socket.set_nonblocking(true)?;
    let original = tokio::io::unix::AsyncFd::new(socket)?;
    let ready = tokio::time::timeout_at(end.into(), original.readable()).await
        .map_err(|_| protocol("original stage handoff deadline elapsed"))??;
    drop(ready);
    let socket = original.into_inner();
    socket.set_nonblocking(false)?;
    if Instant::now() >= end { return Err(protocol("original stage handoff ended")); }
    Ok(socket)
}

fn merge_results(first: Result<(), AgentdError>, second: Result<(), AgentdError>) -> Result<(), AgentdError> {
    match (first, second) {
        (Ok(()), Ok(())) => Ok(()),
        (Err(error), Ok(())) | (Ok(()), Err(error)) => Err(error),
        (Err(first), Err(second)) => Err(protocol(format!("{first}; additional original failure: {second}"))),
    }
}

fn protocol(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Protocol(format!("loaded original task assembly: {error}"))
}
