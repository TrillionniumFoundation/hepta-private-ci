use std::collections::BTreeMap;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::time::{Duration, Instant};

use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;
use tokio::sync::Notify;
use tokio::sync::Semaphore;
use tokio::sync::TryAcquireError;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tokio::task::JoinSet;
use tokio::time::{MissedTickBehavior, interval};
use tokio_util::sync::CancellationToken;

use super::super::persistence::archive_terminal_operations;
use super::super::{
    ProcessRuntimeCodexExecutorV1, RuntimeCodexExecutionInputV1, RuntimeCodexExecutorV1,
    RuntimeCodexOwnerV1,
};
use crate::canonical_runtime_bootstrap::CanonicalRuntimeInstallationTokenV1;
use crate::{AgentdError, AgentdIdentity, PreparedAgentdIntelligenceRunV1, RunPhase, RunReceipt};

#[path = "runtime_codex_supervisor_worker.rs"]
mod worker;
use worker::{cancel_queued, run_job};

const MAX_QUEUE_CAPACITY: usize = 256;
const MAX_CONCURRENT_JOBS: usize = 256;
const DEFAULT_RECOVERY_INTERVAL: Duration = Duration::from_secs(5);
const MIN_RECOVERY_INTERVAL: Duration = Duration::from_millis(100);
const MAX_RECOVERY_INTERVAL: Duration = Duration::from_secs(300);
const ARCHIVE_BATCH: usize = 64;

/// Host-owned derivation of the exact physical runtime.codex request. Request
/// bytes cannot install or replace this provider.
pub trait RuntimeCodexInputProviderV1: Send + Sync {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        prepared: &PreparedAgentdIntelligenceRunV1,
        receipt: &RunReceipt,
    ) -> Result<RuntimeCodexExecutionInputV1, AgentdError>;
}

impl<F> RuntimeCodexInputProviderV1 for F
where
    F: Fn(
            &AgentdIdentity,
            &RunStartRecordV1,
            &PreparedAgentdIntelligenceRunV1,
            &RunReceipt,
        ) -> Result<RuntimeCodexExecutionInputV1, AgentdError>
        + Send
        + Sync,
{
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        prepared: &PreparedAgentdIntelligenceRunV1,
        receipt: &RunReceipt,
    ) -> Result<RuntimeCodexExecutionInputV1, AgentdError> {
        self(identity, record, prepared, receipt)
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct RuntimeCodexSupervisorSnapshotV1 {
    pub ready: bool,
    pub degraded: bool,
    pub closed: bool,
    pub unresolved: usize,
    pub prepared_unfenced: usize,
    pub fenced_unresolved: usize,
    pub active: usize,
    pub reserved: usize,
    pub queued: usize,
    pub running: usize,
    pub oldest_queued_ms: Option<u64>,
    pub recovery_in_progress: bool,
    pub recovery_runs: usize,
    pub recovery_failures: usize,
    pub last_recovery_ms: Option<u64>,
    pub archived_terminal: usize,
    pub admission_blocker: Option<String>,
}

struct ActiveJob {
    digest: Digest32,
    cancellation: CancellationToken,
    queued_at: Instant,
    running: bool,
}

#[derive(Default)]
struct AdmissionState {
    closed: bool,
}

struct Installation {
    profile: RuntimeCodexInstallationProfileV1,
    executor: Arc<ProcessRuntimeCodexExecutorV1>,
    provider: Arc<dyn RuntimeCodexInputProviderV1>,
    sender: mpsc::Sender<Job>,
    receiver: std::sync::Mutex<Option<mpsc::Receiver<Job>>>,
    admission: std::sync::Mutex<AdmissionState>,
    active: std::sync::Mutex<BTreeMap<String, ActiveJob>>,
    started: AtomicBool,
    ready: AtomicBool,
    degraded: AtomicBool,
    closed: AtomicBool,
    unresolved: AtomicUsize,
    prepared_unfenced: AtomicUsize,
    fenced_unresolved: AtomicUsize,
    reserved: AtomicUsize,
    recovery_in_progress: AtomicBool,
    recovery_runs: AtomicUsize,
    recovery_failures: AtomicUsize,
    last_recovery_ms: AtomicU64,
    archived_terminal: AtomicUsize,
    terminal_failure: std::sync::Mutex<Option<String>>,
    maximum_concurrent_jobs: usize,
    recovery_interval: Duration,
}

struct Job {
    input: RuntimeCodexExecutionInputV1,
    cancellation: CancellationToken,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum DispatchState {
    Absent,
    Prepared,
    Fenced,
    Terminal,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum RuntimeCodexInstallationProfileV1 {
    Compatibility,
    Canonical,
}

impl RuntimeCodexInstallationProfileV1 {
    const fn is_canonical(self) -> bool {
        matches!(self, Self::Canonical)
    }
}

/// An owned queue slot acquired before canonical preparation mutates the run
/// coordinator. The admission lock linearizes reservation, final send and
/// shutdown. Dropping this value releases capacity without admitting work.
pub(crate) struct RuntimeCodexScheduleReservationV1 {
    installed: Arc<Installation>,
    permit: Option<mpsc::OwnedPermit<Job>>,
    counted: bool,
}

/// Agentd is a one-runtime-per-process binary. The process-global slot is a
/// deliberate fail-stop boundary, not a restartable service registry: after an
/// owner starts or fails, this process must exit and a new process generation
/// must construct a fresh slot. The explicit started/closed checks below make
/// that contract executable and prevent tests or embeddings from silently
/// reusing a failed owner.
static INSTALLATION: OnceLock<Arc<Installation>> = OnceLock::new();

impl Drop for RuntimeCodexScheduleReservationV1 {
    fn drop(&mut self) {
        if self.counted {
            self.installed.reserved.fetch_sub(1, Ordering::AcqRel);
            self.counted = false;
        }
    }
}

impl RuntimeCodexScheduleReservationV1 {
    pub(crate) fn schedule(
        mut self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        prepared: &PreparedAgentdIntelligenceRunV1,
        receipt: &RunReceipt,
    ) -> Result<bool, AgentdError> {
        if !self.installed.profile.is_canonical() {
            return Err(AgentdError::Invalid(
                "compatibility runtime.codex installation cannot schedule canonical work"
                    .to_string(),
            ));
        }

        // Owner input construction can be comparatively slow. It intentionally
        // runs outside the admission lock, then every mutable readiness fact is
        // rechecked at the single final commit boundary below.
        let input = self
            .installed
            .provider
            .build(identity, record, prepared, receipt)?;
        validate_input(record, prepared, receipt, &input)?;
        let digest = input.digest()?;
        let run_id = input.run_id().to_string();
        let cancellation = CancellationToken::new();

        let admission = self.installed.admission.lock().map_err(|_| {
            AgentdError::Protocol("runtime.codex admission gate is poisoned".to_string())
        })?;
        if admission.closed || self.installed.closed.load(Ordering::Acquire) {
            return Err(AgentdError::Protocol(
                "runtime.codex supervisor closed after capacity reservation".to_string(),
            ));
        }
        if !self.installed.ready.load(Ordering::Acquire) {
            return Err(AgentdError::Protocol(
                "runtime.codex supervisor lost readiness after capacity reservation".to_string(),
            ));
        }

        {
            let mut active = self.installed.active.lock().map_err(|_| {
                AgentdError::Protocol("runtime.codex active registry is poisoned".to_string())
            })?;
            match active.get(&run_id) {
                Some(existing) if existing.digest == digest => return Ok(false),
                Some(_) => {
                    return Err(AgentdError::Protocol(
                        "runtime.codex run identity has queued semantic drift".to_string(),
                    ));
                }
                None => {
                    active.insert(
                        run_id,
                        ActiveJob {
                            digest,
                            cancellation: cancellation.clone(),
                            queued_at: Instant::now(),
                            running: false,
                        },
                    );
                }
            }
        }

        let permit = match self.permit.take() {
            Some(permit) => permit,
            None => {
                remove_active(&self.installed, input.run_id().as_str(), digest)?;
                return Err(AgentdError::Protocol(
                    "runtime.codex queue reservation was already consumed".to_string(),
                ));
            }
        };
        let _sender = permit.send(Job {
            input,
            cancellation,
        });
        if self.counted {
            self.installed.reserved.fetch_sub(1, Ordering::AcqRel);
            self.counted = false;
        }
        drop(admission);
        Ok(true)
    }
}

impl ProcessRuntimeCodexExecutorV1 {
    /// Compatibility constructor for embeddings that exercise the executor
    /// outside Agentd product composition. This installation is intentionally
    /// invisible to daemon canonical readiness.
    pub fn install_agentd_supervisor<F>(
        self: Arc<Self>,
        queue_capacity: usize,
        provider: F,
    ) -> Result<(), AgentdError>
    where
        F: Fn(
                &AgentdIdentity,
                &RunStartRecordV1,
                &PreparedAgentdIntelligenceRunV1,
                &RunReceipt,
            ) -> Result<RuntimeCodexExecutionInputV1, AgentdError>
            + Send
            + Sync
            + 'static,
    {
        let maximum_concurrent_jobs = self.maximum_in_flight().min(MAX_CONCURRENT_JOBS);
        self.install_agentd_supervisor_with_limits(
            queue_capacity,
            maximum_concurrent_jobs,
            DEFAULT_RECOVERY_INTERVAL,
            Arc::new(provider),
        )
    }

    /// Compatibility-only bounded installation. The ordinary daemon refuses to
    /// treat this surface as its canonical physical execution owner.
    pub fn install_agentd_supervisor_with_limits(
        self: Arc<Self>,
        queue_capacity: usize,
        maximum_concurrent_jobs: usize,
        recovery_interval: Duration,
        provider: Arc<dyn RuntimeCodexInputProviderV1>,
    ) -> Result<(), AgentdError> {
        self.install_agentd_supervisor_profile(
            queue_capacity,
            maximum_concurrent_jobs,
            recovery_interval,
            provider,
            RuntimeCodexInstallationProfileV1::Compatibility,
        )
    }

    /// Canonical installation is callable only by the all-or-none typed
    /// bootstrap, which owns the private token required by this boundary.
    pub(crate) fn install_agentd_canonical_supervisor_with_limits(
        self: Arc<Self>,
        queue_capacity: usize,
        maximum_concurrent_jobs: usize,
        recovery_interval: Duration,
        provider: Arc<dyn RuntimeCodexInputProviderV1>,
        _token: CanonicalRuntimeInstallationTokenV1,
    ) -> Result<(), AgentdError> {
        self.install_agentd_supervisor_profile(
            queue_capacity,
            maximum_concurrent_jobs,
            recovery_interval,
            provider,
            RuntimeCodexInstallationProfileV1::Canonical,
        )
    }

    fn install_agentd_supervisor_profile(
        self: Arc<Self>,
        queue_capacity: usize,
        maximum_concurrent_jobs: usize,
        recovery_interval: Duration,
        provider: Arc<dyn RuntimeCodexInputProviderV1>,
        profile: RuntimeCodexInstallationProfileV1,
    ) -> Result<(), AgentdError> {
        if !(1..=MAX_QUEUE_CAPACITY).contains(&queue_capacity)
            || !(1..=MAX_CONCURRENT_JOBS).contains(&maximum_concurrent_jobs)
            || maximum_concurrent_jobs > self.maximum_in_flight()
            || !(MIN_RECOVERY_INTERVAL..=MAX_RECOVERY_INTERVAL).contains(&recovery_interval)
        {
            return Err(AgentdError::Invalid(
                "invalid runtime.codex supervisor queue, concurrency or recovery bounds"
                    .to_string(),
            ));
        }
        let (sender, receiver) = mpsc::channel(queue_capacity);
        INSTALLATION
            .set(Arc::new(Installation {
                profile,
                executor: self,
                provider,
                sender,
                receiver: std::sync::Mutex::new(Some(receiver)),
                admission: std::sync::Mutex::new(AdmissionState::default()),
                active: std::sync::Mutex::new(BTreeMap::new()),
                started: AtomicBool::new(false),
                ready: AtomicBool::new(false),
                degraded: AtomicBool::new(true),
                closed: AtomicBool::new(false),
                unresolved: AtomicUsize::new(0),
                prepared_unfenced: AtomicUsize::new(0),
                fenced_unresolved: AtomicUsize::new(0),
                reserved: AtomicUsize::new(0),
                recovery_in_progress: AtomicBool::new(false),
                recovery_runs: AtomicUsize::new(0),
                recovery_failures: AtomicUsize::new(0),
                last_recovery_ms: AtomicU64::new(0),
                archived_terminal: AtomicUsize::new(0),
                terminal_failure: std::sync::Mutex::new(None),
                maximum_concurrent_jobs,
                recovery_interval,
            }))
            .map_err(|_| {
                AgentdError::Invalid(
                    "runtime.codex supervisor was installed more than once; restart the process \
                     after any installation or owner failure"
                        .to_string(),
                )
            })
    }

    pub(crate) fn agentd_supervisor_installed() -> bool {
        INSTALLATION
            .get()
            .is_some_and(|installed| installed.profile.is_canonical())
    }

    pub(crate) fn agentd_supervisor_snapshot()
    -> Result<Option<RuntimeCodexSupervisorSnapshotV1>, AgentdError> {
        let Some(installed) = INSTALLATION
            .get()
            .filter(|installed| installed.profile.is_canonical())
        else {
            return Ok(None);
        };
        let active = installed.active.lock().map_err(|_| {
            AgentdError::Protocol("runtime.codex active registry is poisoned".to_string())
        })?;
        let now = Instant::now();
        let queued = active.values().filter(|job| !job.running).count();
        let running = active.values().filter(|job| job.running).count();
        let oldest_queued_ms = active
            .values()
            .filter(|job| !job.running)
            .map(|job| duration_millis(now.saturating_duration_since(job.queued_at)))
            .max();
        let terminal_failure = installed
            .terminal_failure
            .lock()
            .map_err(|_| {
                AgentdError::Protocol("runtime.codex failure state is poisoned".to_string())
            })?
            .clone();
        let closed = installed.closed.load(Ordering::Acquire);
        let ready = installed.ready.load(Ordering::Acquire);
        let recovery_in_progress = installed.recovery_in_progress.load(Ordering::Acquire);
        let fenced_unresolved = installed.fenced_unresolved.load(Ordering::Acquire);
        let unresolved = installed.unresolved.load(Ordering::Acquire);
        let admission_blocker = terminal_failure.or_else(|| {
            if closed {
                Some("closed".to_string())
            } else if recovery_in_progress {
                Some("recovery_in_progress".to_string())
            } else if fenced_unresolved != 0 {
                Some("fenced_unresolved".to_string())
            } else if !ready {
                Some("startup_reconciliation".to_string())
            } else if installed.sender.capacity() == 0 {
                Some("queue_capacity".to_string())
            } else if unresolved != 0 {
                Some("degraded_reconciliation".to_string())
            } else {
                None
            }
        });
        let last_recovery_ms = installed.last_recovery_ms.load(Ordering::Acquire);
        Ok(Some(RuntimeCodexSupervisorSnapshotV1 {
            ready,
            degraded: installed.degraded.load(Ordering::Acquire),
            closed,
            unresolved,
            prepared_unfenced: installed.prepared_unfenced.load(Ordering::Acquire),
            fenced_unresolved,
            active: active.len(),
            reserved: installed.reserved.load(Ordering::Acquire),
            queued,
            running,
            oldest_queued_ms,
            recovery_in_progress,
            recovery_runs: installed.recovery_runs.load(Ordering::Acquire),
            recovery_failures: installed.recovery_failures.load(Ordering::Acquire),
            last_recovery_ms: (last_recovery_ms != 0).then_some(last_recovery_ms),
            archived_terminal: installed.archived_terminal.load(Ordering::Acquire),
            admission_blocker,
        }))
    }

    pub(crate) fn reserve_canonical_run() -> Result<RuntimeCodexScheduleReservationV1, AgentdError>
    {
        let installed = Arc::clone(INSTALLATION.get().ok_or_else(|| {
            AgentdError::Invalid(
                "canonical intelligence has no installed runtime.codex supervisor".to_string(),
            )
        })?);
        if !installed.profile.is_canonical() {
            return Err(AgentdError::Invalid(
                "canonical intelligence requires the typed runtime bootstrap".to_string(),
            ));
        }
        let admission = installed.admission.lock().map_err(|_| {
            AgentdError::Protocol("runtime.codex admission gate is poisoned".to_string())
        })?;
        if admission.closed || installed.closed.load(Ordering::Acquire) {
            return Err(AgentdError::Protocol(
                "runtime.codex supervisor is closed".to_string(),
            ));
        }
        if !installed.ready.load(Ordering::Acquire) {
            return Err(AgentdError::Protocol(
                "runtime.codex supervisor recovery is not ready".to_string(),
            ));
        }
        let permit = installed
            .sender
            .clone()
            .try_reserve_owned()
            .map_err(|error| {
                AgentdError::Protocol(format!(
                    "runtime.codex supervisor has no reserved queue capacity: {error}"
                ))
            })?;
        installed.reserved.fetch_add(1, Ordering::AcqRel);
        drop(admission);
        Ok(RuntimeCodexScheduleReservationV1 {
            installed,
            permit: Some(permit),
            counted: true,
        })
    }

    pub(crate) fn schedule_canonical_run(
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        prepared: &PreparedAgentdIntelligenceRunV1,
        receipt: &RunReceipt,
    ) -> Result<bool, AgentdError> {
        Self::reserve_canonical_run()?.schedule(identity, record, prepared, receipt)
    }

    pub(crate) fn cancel_installed_runs() -> Result<(), AgentdError> {
        let Some(installed) = INSTALLATION
            .get()
            .filter(|installed| installed.profile.is_canonical())
        else {
            return Ok(());
        };
        close_admission(installed)?;
        cancel_active(installed)
    }

    pub(crate) async fn run_installed_agentd_supervisor(
        identity: AgentdIdentity,
        lifetime: CancellationToken,
    ) -> Result<(), AgentdError> {
        let installed = Arc::clone(INSTALLATION.get().ok_or_else(|| {
            AgentdError::Invalid(
                "runtime.codex supervisor owner started without installation".to_string(),
            )
        })?);
        if !installed.profile.is_canonical() {
            return Err(AgentdError::Invalid(
                "Agentd refuses a compatibility runtime.codex installation".to_string(),
            ));
        }
        claim_single_start(&installed.started)?;
        let mut receiver = installed
            .receiver
            .lock()
            .map_err(|_| AgentdError::Protocol("runtime.codex receiver is poisoned".to_string()))?
            .take()
            .ok_or_else(|| {
                AgentdError::Protocol(
                    "runtime.codex supervisor owner was started more than once".to_string(),
                )
            })?;
        let owner = RuntimeCodexOwnerV1::from_agentd(&identity);
        let mut jobs = JoinSet::new();
        let mut pending = None;

        let initial = perform_maintenance_once(
            Arc::clone(&installed),
            owner.clone(),
            lifetime.child_token(),
        )
        .await;
        if let Err(error) = initial {
            remember_terminal_failure(&installed, &error);
            let cleanup = cleanup_supervisor(
                &installed,
                &identity,
                &owner,
                &mut receiver,
                &mut pending,
                &mut jobs,
                None,
                None,
            )
            .await;
            return merge_results(Err(error), cleanup);
        }

        let concurrency = Arc::new(Semaphore::new(installed.maximum_concurrent_jobs));
        let maintenance_cancel = lifetime.child_token();
        let maintenance_wakeup = Arc::new(Notify::new());
        let mut maintenance = tokio::spawn(run_periodic_maintenance(
            Arc::clone(&installed),
            owner.clone(),
            maintenance_cancel.clone(),
            Arc::clone(&maintenance_wakeup),
        ));
        let mut maintenance_finished = false;

        let result = 'run: loop {
            if pending.is_some() {
                match Arc::clone(&concurrency).try_acquire_owned() {
                    Ok(permit) => {
                        let job = pending.take().expect("pending job checked above");
                        let run_id = job.input.run_id().to_string();
                        let digest = match job.input.digest() {
                            Ok(digest) => digest,
                            Err(error) => {
                                pending = Some(job);
                                break 'run Err(error);
                            }
                        };
                        if let Err(error) = mark_running(&installed, &run_id, digest) {
                            pending = Some(job);
                            break 'run Err(error);
                        }
                        let executor = Arc::clone(&installed.executor);
                        let job_owner = owner.clone();
                        let job_identity = identity.clone();
                        let job_lifetime = lifetime.clone();
                        jobs.spawn(async move {
                            let _permit = permit;
                            let outcome = run_job(
                                executor,
                                job_owner,
                                job_identity,
                                job,
                                job_lifetime,
                            )
                            .await;
                            (run_id, digest, outcome)
                        });
                    }
                    Err(TryAcquireError::NoPermits) => {}
                    Err(TryAcquireError::Closed) => {
                        break 'run Err(AgentdError::Protocol(
                            "runtime.codex execution semaphore closed".to_string(),
                        ));
                    }
                }
            }

            tokio::select! {
                biased;
                _ = lifetime.cancelled() => break 'run Ok(()),
                maintenance_result = &mut maintenance, if !maintenance_finished => {
                    maintenance_finished = true;
                    break 'run maintenance_outcome(maintenance_result, lifetime.is_cancelled());
                }
                joined = jobs.join_next(), if !jobs.is_empty() => {
                    let Some(joined) = joined else { continue; };
                    match joined {
                        Ok((run_id, digest, outcome)) => {
                            if let Err(error) = remove_active(&installed, &run_id, digest) {
                                break 'run Err(error);
                            }
                            maintenance_wakeup.notify_one();
                            if let Err(error) = outcome {
                                break 'run Err(error);
                            }
                        }
                        Err(error) => {
                            break 'run Err(AgentdError::Protocol(format!(
                                "runtime.codex supervised job failed to join: {error}"
                            )));
                        }
                    }
                }
                maybe_job = receiver.recv(), if pending.is_none() => {
                    match maybe_job {
                        Some(job) => pending = Some(job),
                        None => {
                            break 'run Err(AgentdError::Protocol(
                                "runtime.codex supervisor queue closed unexpectedly".to_string(),
                            ));
                        }
                    }
                }
            }
        };

        if let Err(error) = &result {
            remember_terminal_failure(&installed, error);
        }
        let cleanup = cleanup_supervisor(
            &installed,
            &identity,
            &owner,
            &mut receiver,
            &mut pending,
            &mut jobs,
            Some(maintenance_cancel),
            (!maintenance_finished).then_some(maintenance),
        )
        .await;
        merge_results(result, cleanup)
    }
}

async fn run_periodic_maintenance(
    installed: Arc<Installation>,
    owner: RuntimeCodexOwnerV1,
    lifetime: CancellationToken,
    wakeup: Arc<Notify>,
) -> Result<(), AgentdError> {
    let mut recovery = interval(installed.recovery_interval);
    recovery.set_missed_tick_behavior(MissedTickBehavior::Skip);
    recovery.tick().await;
    loop {
        tokio::select! {
            _ = lifetime.cancelled() => return Ok(()),
            _ = recovery.tick() => {}
            _ = wakeup.notified() => {}
        }
        if lifetime.is_cancelled() {
            return Ok(());
        }
        perform_maintenance_once(
            Arc::clone(&installed),
            owner.clone(),
            lifetime.child_token(),
        )
        .await?;
    }
}

async fn perform_maintenance_once(
    installed: Arc<Installation>,
    owner: RuntimeCodexOwnerV1,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    installed
        .recovery_in_progress
        .store(true, Ordering::Release);
    let started = Instant::now();
    let result = async {
        let report = installed
            .executor
            .reconcile_pending(owner.clone(), cancellation)
            .await?;
        let root = installed.executor.journal_root().to_path_buf();
        let worker_digest = installed.executor.worker_artifact_digest();
        let archived = tokio::task::spawn_blocking(move || {
            archive_terminal_operations(&root, &owner, worker_digest, ARCHIVE_BATCH)
        })
        .await
        .map_err(|error| {
            AgentdError::Protocol(format!(
                "runtime.codex archive maintenance failed to join: {error}"
            ))
        })??;
        publish_recovery_status(&installed, &report);
        installed
            .archived_terminal
            .fetch_add(archived, Ordering::AcqRel);
        Ok(())
    }
    .await;
    installed.recovery_in_progress.store(false, Ordering::Release);
    installed.recovery_runs.fetch_add(1, Ordering::AcqRel);
    installed
        .last_recovery_ms
        .store(duration_millis(started.elapsed()), Ordering::Release);
    if result.is_err() {
        installed.recovery_failures.fetch_add(1, Ordering::AcqRel);
        installed.ready.store(false, Ordering::Release);
        installed.degraded.store(true, Ordering::Release);
    }
    result
}

#[allow(clippy::too_many_arguments)]
async fn cleanup_supervisor(
    installed: &Arc<Installation>,
    identity: &AgentdIdentity,
    owner: &RuntimeCodexOwnerV1,
    receiver: &mut mpsc::Receiver<Job>,
    pending: &mut Option<Job>,
    jobs: &mut JoinSet<(String, Digest32, Result<(), AgentdError>)>,
    maintenance_cancel: Option<CancellationToken>,
    maintenance: Option<JoinHandle<Result<(), AgentdError>>>,
) -> Result<(), AgentdError> {
    let mut first_error = None;
    record_result(&mut first_error, close_admission(installed));
    receiver.close();
    record_result(&mut first_error, cancel_active(installed));

    if let Some(job) = pending.take() {
        record_result(
            &mut first_error,
            cancel_queued_job(installed, identity, &job).await,
        );
    }
    while let Ok(job) = receiver.try_recv() {
        record_result(
            &mut first_error,
            cancel_queued_job(installed, identity, &job).await,
        );
    }

    if let Some(cancel) = maintenance_cancel {
        cancel.cancel();
    }
    if let Some(maintenance) = maintenance {
        let result = maintenance.await.map_err(|error| {
            AgentdError::Protocol(format!(
                "runtime.codex maintenance task failed during shutdown: {error}"
            ))
        });
        match result {
            Ok(result) => record_result(&mut first_error, result),
            Err(error) => record_error(&mut first_error, error),
        }
    }

    while let Some(joined) = jobs.join_next().await {
        match joined {
            Ok((run_id, digest, outcome)) => {
                record_result(&mut first_error, remove_active(installed, &run_id, digest));
                record_result(&mut first_error, outcome);
            }
            Err(error) => record_error(
                &mut first_error,
                AgentdError::Protocol(format!(
                    "runtime.codex supervised job failed during shutdown: {error}"
                )),
            ),
        }
    }

    let root = installed.executor.journal_root().to_path_buf();
    let owner = owner.clone();
    let worker_digest = installed.executor.worker_artifact_digest();
    let archived = tokio::task::spawn_blocking(move || {
        archive_terminal_operations(&root, &owner, worker_digest, ARCHIVE_BATCH)
    })
    .await
    .map_err(|error| {
        AgentdError::Protocol(format!(
            "runtime.codex final archive failed to join: {error}"
        ))
    });
    match archived {
        Ok(Ok(count)) => {
            installed
                .archived_terminal
                .fetch_add(count, Ordering::AcqRel);
        }
        Ok(Err(error)) => record_error(&mut first_error, error),
        Err(error) => record_error(&mut first_error, error),
    }

    match first_error {
        Some(error) => Err(error),
        None => Ok(()),
    }
}

async fn cancel_queued_job(
    installed: &Installation,
    identity: &AgentdIdentity,
    job: &Job,
) -> Result<(), AgentdError> {
    let run_id = job.input.run_id().to_string();
    let digest = job.input.digest()?;
    let cancellation = cancel_queued(identity, job).await;
    let removal = remove_active(installed, &run_id, digest);
    match (cancellation, removal) {
        (Err(error), _) => Err(error),
        (Ok(()), Err(error)) => Err(error),
        (Ok(()), Ok(())) => Ok(()),
    }
}

fn maintenance_outcome(
    result: Result<Result<(), AgentdError>, tokio::task::JoinError>,
    stopping: bool,
) -> Result<(), AgentdError> {
    match result {
        Ok(Ok(())) if stopping => Ok(()),
        Ok(Ok(())) => Err(AgentdError::Protocol(
            "runtime.codex maintenance owner exited before shutdown".to_string(),
        )),
        Ok(Err(error)) => Err(error),
        Err(error) => Err(AgentdError::Protocol(format!(
            "runtime.codex maintenance owner failed to join: {error}"
        ))),
    }
}

fn merge_results(
    primary: Result<(), AgentdError>,
    cleanup: Result<(), AgentdError>,
) -> Result<(), AgentdError> {
    match (primary, cleanup) {
        (Err(error), _) => Err(error),
        (Ok(()), Err(error)) => Err(error),
        (Ok(()), Ok(())) => Ok(()),
    }
}

fn record_result(slot: &mut Option<AgentdError>, result: Result<(), AgentdError>) {
    if let Err(error) = result {
        record_error(slot, error);
    }
}

fn record_error(slot: &mut Option<AgentdError>, error: AgentdError) {
    if slot.is_none() {
        *slot = Some(error);
    }
}

fn remember_terminal_failure(installed: &Installation, _error: &AgentdError) {
    if let Ok(mut failure) = installed.terminal_failure.lock()
        && failure.is_none()
    {
        *failure = Some("owner_failed".to_string());
    }
}

fn close_admission(installed: &Installation) -> Result<(), AgentdError> {
    let mut admission = installed.admission.lock().map_err(|_| {
        AgentdError::Protocol("runtime.codex admission gate is poisoned".to_string())
    })?;
    admission.closed = true;
    installed.ready.store(false, Ordering::Release);
    installed.closed.store(true, Ordering::Release);
    installed.degraded.store(true, Ordering::Release);
    Ok(())
}

fn claim_single_start(started: &AtomicBool) -> Result<(), AgentdError> {
    if started.swap(true, Ordering::AcqRel) {
        return Err(AgentdError::Invalid(
            "runtime.codex supervisor is fail-stop and cannot be restarted in the same process"
                .to_string(),
        ));
    }
    Ok(())
}

fn publish_recovery_status(
    installed: &Installation,
    report: &super::super::RuntimeCodexReconcileReportV1,
) {
    installed
        .unresolved
        .store(report.unresolved, Ordering::Release);
    installed
        .prepared_unfenced
        .store(report.prepared_unfenced, Ordering::Release);
    installed
        .fenced_unresolved
        .store(report.fenced_unresolved, Ordering::Release);
    installed
        .degraded
        .store(report.unresolved != 0, Ordering::Release);
    installed.ready.store(
        !installed.closed.load(Ordering::Acquire) && report.fenced_unresolved == 0,
        Ordering::Release,
    );
}

fn cancel_active(installed: &Installation) -> Result<(), AgentdError> {
    let active = installed.active.lock().map_err(|_| {
        AgentdError::Protocol("runtime.codex active registry is poisoned".to_string())
    })?;
    for job in active.values() {
        job.cancellation.cancel();
    }
    Ok(())
}

fn mark_running(
    installed: &Installation,
    run_id: &str,
    digest: Digest32,
) -> Result<(), AgentdError> {
    let mut active = installed.active.lock().map_err(|_| {
        AgentdError::Protocol("runtime.codex active registry is poisoned".to_string())
    })?;
    let observed = active.get_mut(run_id).ok_or_else(|| {
        AgentdError::Protocol("runtime.codex queued job disappeared before execution".to_string())
    })?;
    if observed.digest != digest {
        return Err(AgentdError::Protocol(
            "runtime.codex queued job changed identity before execution".to_string(),
        ));
    }
    observed.running = true;
    Ok(())
}

fn validate_input(
    record: &RunStartRecordV1,
    prepared: &PreparedAgentdIntelligenceRunV1,
    receipt: &RunReceipt,
    input: &RuntimeCodexExecutionInputV1,
) -> Result<(), AgentdError> {
    let context = prepared.context_attachment();
    let context_digest = Digest32::from_str(&context.context_digest)
        .map_err(|_| AgentdError::Protocol("canonical context digest is invalid".to_string()))?;
    if record.snapshot.run_id.as_str() != prepared.envelope.run_id.as_str()
        || record.snapshot.run_id.as_str() != receipt.run_id
        || record.snapshot.run_id.as_str() != input.run_id().as_str()
        || receipt.phase != RunPhase::ContextAttached
        || receipt.revision != input.expected_revision()
        || receipt.context_digest.as_deref() != Some(context.context_digest.as_str())
        || receipt.deadline_ms != input.deadline_ms()
        || input.context_digest() != context_digest
        || input.envelope_digest() != prepared.envelope.envelope_digest
        || receipt.generation != record.snapshot.generation
    {
        return Err(AgentdError::GenerationFenced(
            "runtime.codex input does not match the sealed canonical run".to_string(),
        ));
    }
    Ok(())
}

fn remove_active(
    installed: &Installation,
    run_id: &str,
    digest: Digest32,
) -> Result<(), AgentdError> {
    let mut active = installed.active.lock().map_err(|_| {
        AgentdError::Protocol("runtime.codex active registry is poisoned".to_string())
    })?;
    if active
        .get(run_id)
        .is_some_and(|observed| observed.digest != digest)
    {
        return Err(AgentdError::Protocol(
            "runtime.codex active cleanup observed semantic drift".to_string(),
        ));
    }
    active.remove(run_id);
    Ok(())
}

fn duration_millis(duration: Duration) -> u64 {
    u64::try_from(duration.as_millis()).unwrap_or(u64::MAX)
}

#[cfg(test)]
mod installation_profile_tests {
    use std::sync::atomic::AtomicBool;

    use super::RuntimeCodexInstallationProfileV1;
    use super::claim_single_start;

    #[test]
    fn only_typed_profile_is_canonical() {
        assert!(!RuntimeCodexInstallationProfileV1::Compatibility.is_canonical());
        assert!(RuntimeCodexInstallationProfileV1::Canonical.is_canonical());
    }

    #[test]
    fn owner_is_fail_stop_inside_one_process() {
        let started = AtomicBool::new(false);
        claim_single_start(&started).expect("first owner start");
        let error = claim_single_start(&started).expect_err("second owner start must fail");
        assert!(error.to_string().contains("fail-stop"), "{error}");
    }
}
