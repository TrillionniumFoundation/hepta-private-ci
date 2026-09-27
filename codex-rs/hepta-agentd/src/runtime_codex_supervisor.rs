use std::collections::BTreeMap;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::time::Duration;

use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;
use tokio::sync::Semaphore;
use tokio::sync::mpsc;
use tokio::task::JoinSet;
use tokio::time::{MissedTickBehavior, interval};
use tokio_util::sync::CancellationToken;

use super::super::persistence::archive_terminal_operations;
use super::super::{
    ProcessRuntimeCodexExecutorV1, RuntimeCodexExecutionInputV1, RuntimeCodexExecutorV1,
    RuntimeCodexOwnerV1,
};
use crate::canonical_runtime_bootstrap::CanonicalRuntimeInstallationTokenV1;
use crate::{
    AgentdError, AgentdIdentity, PreparedAgentdIntelligenceRunV1, RunPhase, RunReceipt,
};

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
}

struct ActiveJob {
    digest: Digest32,
    cancellation: CancellationToken,
}

struct Installation {
    profile: RuntimeCodexInstallationProfileV1,
    executor: Arc<ProcessRuntimeCodexExecutorV1>,
    provider: Arc<dyn RuntimeCodexInputProviderV1>,
    sender: mpsc::Sender<Job>,
    receiver: std::sync::Mutex<Option<mpsc::Receiver<Job>>>,
    active: std::sync::Mutex<BTreeMap<String, ActiveJob>>,
    ready: AtomicBool,
    degraded: AtomicBool,
    closed: AtomicBool,
    unresolved: AtomicUsize,
    prepared_unfenced: AtomicUsize,
    fenced_unresolved: AtomicUsize,
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
/// coordinator. Dropping this value releases capacity without admitting work.
pub(crate) struct RuntimeCodexScheduleReservationV1 {
    installed: Arc<Installation>,
    permit: Option<mpsc::OwnedPermit<Job>>,
}

static INSTALLATION: OnceLock<Arc<Installation>> = OnceLock::new();

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
        if self.installed.closed.load(Ordering::Acquire) {
            return Err(AgentdError::Protocol(
                "runtime.codex supervisor closed after capacity reservation".to_string(),
            ));
        }
        if !self.installed.ready.load(Ordering::Acquire) {
            return Err(AgentdError::Protocol(
                "runtime.codex supervisor lost readiness after capacity reservation".to_string(),
            ));
        }
        let input = self
            .installed
            .provider
            .build(identity, record, prepared, receipt)?;
        validate_input(record, prepared, receipt, &input)?;
        let digest = input.digest()?;
        let run_id = input.run_id().to_string();
        let cancellation = CancellationToken::new();
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
                        },
                    );
                }
            }
        }
        let permit = self.permit.take().ok_or_else(|| {
            AgentdError::Protocol("runtime.codex queue reservation was already consumed".to_string())
        })?;
        let _sender = permit.send(Job {
            input,
            cancellation,
        });
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
                active: std::sync::Mutex::new(BTreeMap::new()),
                ready: AtomicBool::new(false),
                degraded: AtomicBool::new(true),
                closed: AtomicBool::new(false),
                unresolved: AtomicUsize::new(0),
                prepared_unfenced: AtomicUsize::new(0),
                fenced_unresolved: AtomicUsize::new(0),
                maximum_concurrent_jobs,
                recovery_interval,
            }))
            .map_err(|_| {
                AgentdError::Invalid(
                    "runtime.codex supervisor was installed more than once".to_string(),
                )
            })
    }

    pub(crate) fn agentd_supervisor_installed() -> bool {
        INSTALLATION
            .get()
            .is_some_and(|installed| installed.profile.is_canonical())
    }

    pub(crate) fn agentd_supervisor_snapshot(
    ) -> Result<Option<RuntimeCodexSupervisorSnapshotV1>, AgentdError> {
        let Some(installed) = INSTALLATION
            .get()
            .filter(|installed| installed.profile.is_canonical())
        else {
            return Ok(None);
        };
        let active = installed
            .active
            .lock()
            .map_err(|_| {
                AgentdError::Protocol("runtime.codex active registry is poisoned".to_string())
            })?
            .len();
        Ok(Some(RuntimeCodexSupervisorSnapshotV1 {
            ready: installed.ready.load(Ordering::Acquire),
            degraded: installed.degraded.load(Ordering::Acquire),
            closed: installed.closed.load(Ordering::Acquire),
            unresolved: installed.unresolved.load(Ordering::Acquire),
            prepared_unfenced: installed.prepared_unfenced.load(Ordering::Acquire),
            fenced_unresolved: installed.fenced_unresolved.load(Ordering::Acquire),
            active,
        }))
    }

    pub(crate) fn reserve_canonical_run(
    ) -> Result<RuntimeCodexScheduleReservationV1, AgentdError> {
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
        if installed.closed.load(Ordering::Acquire) {
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
        Ok(RuntimeCodexScheduleReservationV1 {
            installed,
            permit: Some(permit),
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
        installed.ready.store(false, Ordering::Release);
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
        let mut receiver = installed
            .receiver
            .lock()
            .map_err(|_| {
                AgentdError::Protocol("runtime.codex receiver is poisoned".to_string())
            })?
            .take()
            .ok_or_else(|| {
                AgentdError::Protocol(
                    "runtime.codex supervisor owner was started more than once".to_string(),
                )
            })?;
        let owner = RuntimeCodexOwnerV1::from_agentd(&identity);
        let initial = installed
            .executor
            .reconcile_pending(owner.clone(), lifetime.child_token())
            .await?;
        archive_terminal_operations(
            installed.executor.journal_root(),
            &owner,
            installed.executor.worker_artifact_digest(),
            ARCHIVE_BATCH,
        )?;
        publish_recovery_status(&installed, &initial);

        let concurrency = Arc::new(Semaphore::new(installed.maximum_concurrent_jobs));
        let mut jobs = JoinSet::new();
        let mut recovery = interval(installed.recovery_interval);
        recovery.set_missed_tick_behavior(MissedTickBehavior::Skip);
        recovery.tick().await;

        let result = loop {
            tokio::select! {
                biased;
                _ = lifetime.cancelled() => break Ok(()),
                joined = jobs.join_next(), if !jobs.is_empty() => {
                    let Some(joined) = joined else { continue; };
                    match joined {
                        Ok((run_id, digest, outcome)) => {
                            remove_active(&installed, &run_id, digest)?;
                            if let Err(error) = outcome {
                                break Err(error);
                            }
                            if jobs.is_empty() {
                                archive_terminal_operations(
                                    installed.executor.journal_root(),
                                    &owner,
                                    installed.executor.worker_artifact_digest(),
                                    ARCHIVE_BATCH,
                                )?;
                            }
                        }
                        Err(error) => {
                            break Err(AgentdError::Protocol(format!(
                                "runtime.codex supervised job failed to join: {error}"
                            )));
                        }
                    }
                }
                _ = recovery.tick() => {
                    let report = installed
                        .executor
                        .reconcile_pending(owner.clone(), lifetime.child_token())
                        .await?;
                    if jobs.is_empty() {
                        archive_terminal_operations(
                            installed.executor.journal_root(),
                            &owner,
                            installed.executor.worker_artifact_digest(),
                            ARCHIVE_BATCH,
                        )?;
                    }
                    publish_recovery_status(&installed, &report);
                }
                maybe_job = receiver.recv() => {
                    let job = match maybe_job {
                        Some(job) => job,
                        None => break Err(AgentdError::Protocol(
                            "runtime.codex supervisor queue closed unexpectedly".to_string(),
                        )),
                    };
                    let permit = tokio::select! {
                        _ = lifetime.cancelled() => {
                            job.cancellation.cancel();
                            break Ok(());
                        }
                        permit = Arc::clone(&concurrency).acquire_owned() => permit.map_err(|_| {
                            AgentdError::Protocol("runtime.codex execution semaphore closed".to_string())
                        })?,
                    };
                    let run_id = job.input.run_id().to_string();
                    let digest = job.input.digest()?;
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
            }
        };

        installed.ready.store(false, Ordering::Release);
        installed.closed.store(true, Ordering::Release);
        installed.degraded.store(true, Ordering::Release);
        receiver.close();
        cancel_active(&installed)?;
        while let Ok(job) = receiver.try_recv() {
            let run_id = job.input.run_id().to_string();
            let digest = job.input.digest()?;
            cancel_queued(&identity, &job).await?;
            remove_active(&installed, &run_id, digest)?;
        }
        while let Some(joined) = jobs.join_next().await {
            match joined {
                Ok((run_id, digest, outcome)) => {
                    remove_active(&installed, &run_id, digest)?;
                    outcome?;
                }
                Err(error) => {
                    return Err(AgentdError::Protocol(format!(
                        "runtime.codex supervised job failed during shutdown: {error}"
                    )));
                }
            }
        }
        archive_terminal_operations(
            installed.executor.journal_root(),
            &owner,
            installed.executor.worker_artifact_digest(),
            ARCHIVE_BATCH,
        )?;
        result
    }
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

fn validate_input(
    record: &RunStartRecordV1,
    prepared: &PreparedAgentdIntelligenceRunV1,
    receipt: &RunReceipt,
    input: &RuntimeCodexExecutionInputV1,
) -> Result<(), AgentdError> {
    let context = prepared.context_attachment();
    let context_digest = Digest32::from_str(&context.context_digest).map_err(|_| {
        AgentdError::Protocol("canonical context digest is invalid".to_string())
    })?;
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

#[cfg(test)]
mod installation_profile_tests {
    use super::RuntimeCodexInstallationProfileV1;

    #[test]
    fn only_typed_profile_is_canonical() {
        assert!(!RuntimeCodexInstallationProfileV1::Compatibility.is_canonical());
        assert!(RuntimeCodexInstallationProfileV1::Canonical.is_canonical());
    }
}
