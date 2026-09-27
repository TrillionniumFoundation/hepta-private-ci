use std::collections::BTreeMap;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;
use tokio::sync::Notify;
use tokio::sync::Semaphore;
use tokio::sync::mpsc;
use tokio::task::JoinSet;
use tokio::time::Instant;
use tokio::time::MissedTickBehavior;
use tokio::time::interval;
use tokio::time::timeout;
use tokio::time::timeout_at;
use tokio_util::sync::CancellationToken;

use super::super::ProcessRuntimeCodexExecutorV1;
use super::super::RuntimeCodexExecutionInputV1;
use super::super::RuntimeCodexExecutorV1;
use super::super::RuntimeCodexOwnerV1;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::PreparedAgentdIntelligenceRunV1;
use crate::RunPhase;
use crate::RunReceipt;
use crate::RuntimeCodexInputProviderV1;
use crate::RuntimeCodexReconcileReportV1;

#[path = "runtime_codex_supervisor_worker.rs"]
mod worker;
use worker::cancel_queued;
use worker::run_job;

const MAX_QUEUE_CAPACITY: usize = 256;
const RECOVERY_RETRY_INTERVAL: Duration = Duration::from_secs(5);
const WORKER_DRAIN_GRACE: Duration = Duration::from_secs(35);

struct ActiveJob {
    digest: Digest32,
    cancellation: CancellationToken,
}

struct Installation {
    executor: Arc<ProcessRuntimeCodexExecutorV1>,
    provider: Arc<dyn RuntimeCodexInputProviderV1>,
    sender: mpsc::Sender<Job>,
    receiver: std::sync::Mutex<Option<mpsc::Receiver<Job>>>,
    active: std::sync::Mutex<BTreeMap<String, ActiveJob>>,
    started: AtomicBool,
    degraded: AtomicBool,
    unresolved: AtomicUsize,
    unresolved_post_dispatch: AtomicUsize,
    closed: AtomicBool,
    status_changed: Notify,
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeCodexSupervisorStatusV1 {
    pub started: bool,
    pub admission_ready: bool,
    pub degraded: bool,
    pub unresolved: usize,
    pub unresolved_post_dispatch: usize,
}

/// A queue slot reserved before canonical run admission.
///
/// The permit is non-cloneable. Dropping it releases capacity without creating
/// a run or durable process identity.
pub(crate) struct RuntimeCodexSchedulePermitV1 {
    installation: Arc<Installation>,
    permit: Option<mpsc::OwnedPermit<Job>>,
}

static INSTALLATION: OnceLock<Arc<Installation>> = OnceLock::new();

impl RuntimeCodexSchedulePermitV1 {
    pub(crate) fn commit(
        mut self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        prepared: &PreparedAgentdIntelligenceRunV1,
        receipt: &RunReceipt,
    ) -> Result<bool, AgentdError> {
        let current = status(&self.installation);
        if !current.admission_ready {
            return Err(AgentdError::Protocol(format!(
                "runtime.codex supervisor lost admission readiness before queue commit: started={} degraded={} unresolved={} post_dispatch={}",
                current.started,
                current.degraded,
                current.unresolved,
                current.unresolved_post_dispatch
            )));
        }
        let input = self
            .installation
            .provider
            .build(identity, record, prepared, receipt)?;
        validate_input(record, prepared, receipt, &input)?;
        let digest = input.digest()?;
        let run_id = input.run_id().to_string();
        let cancellation = CancellationToken::new();
        {
            let mut active = self.installation.active.lock().map_err(|_| {
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
            AgentdError::Protocol("runtime.codex queue permit was already consumed".to_string())
        })?;
        drop(permit.send(Job {
            input,
            cancellation,
        }));
        Ok(true)
    }
}

impl ProcessRuntimeCodexExecutorV1 {
    /// Install exactly one process-local runtime.codex owner before `agentd::run`.
    pub fn install_agentd_supervisor<F>(
        self: Arc<Self>,
        queue_capacity: usize,
        provider: F,
    ) -> Result<(), AgentdError>
    where
        F: RuntimeCodexInputProviderV1 + 'static,
    {
        if !(1..=MAX_QUEUE_CAPACITY).contains(&queue_capacity) {
            return Err(AgentdError::Invalid(format!(
                "runtime.codex supervisor queue capacity must be in 1..={MAX_QUEUE_CAPACITY}"
            )));
        }
        let (sender, receiver) = mpsc::channel(queue_capacity);
        INSTALLATION
            .set(Arc::new(Installation {
                executor: self,
                provider: Arc::new(provider),
                sender,
                receiver: std::sync::Mutex::new(Some(receiver)),
                active: std::sync::Mutex::new(BTreeMap::new()),
                started: AtomicBool::new(false),
                degraded: AtomicBool::new(false),
                unresolved: AtomicUsize::new(0),
                unresolved_post_dispatch: AtomicUsize::new(0),
                closed: AtomicBool::new(false),
                status_changed: Notify::new(),
            }))
            .map_err(|_| {
                AgentdError::Invalid(
                    "runtime.codex supervisor was installed more than once".to_string(),
                )
            })
    }

    pub(crate) fn agentd_supervisor_installed() -> bool {
        INSTALLATION.get().is_some()
    }

    pub(crate) fn agentd_supervisor_status() -> RuntimeCodexSupervisorStatusV1 {
        match INSTALLATION.get() {
            Some(installed) => status(installed),
            None => RuntimeCodexSupervisorStatusV1 {
                started: false,
                admission_ready: false,
                degraded: false,
                unresolved: 0,
                unresolved_post_dispatch: 0,
            },
        }
    }

    /// Latch post-dispatch uncertainty immediately when a physical worker loses
    /// its terminal acknowledgement. This closes new canonical admission even
    /// while unrelated workers are still draining and before the next periodic
    /// reconciliation pass can acquire the recovery write gate.
    pub(crate) fn mark_agentd_supervisor_recovery_required() -> Result<(), AgentdError> {
        let installed = INSTALLATION.get().ok_or_else(|| {
            AgentdError::Protocol(
                "runtime.codex supervisor recovery marker has no installation".to_string(),
            )
        })?;
        increment_atomic(&installed.unresolved, "runtime.codex unresolved counter overflow")?;
        increment_atomic(
            &installed.unresolved_post_dispatch,
            "runtime.codex post-dispatch counter overflow",
        )?;
        installed.degraded.store(true, Ordering::Release);
        installed.status_changed.notify_waiters();
        Ok(())
    }

    pub(crate) async fn wait_agentd_supervisor_started(
        maximum_wait: Duration,
    ) -> Result<RuntimeCodexSupervisorStatusV1, AgentdError> {
        if maximum_wait.is_zero() {
            return Err(AgentdError::Invalid(
                "runtime.codex supervisor startup wait must be non-zero".to_string(),
            ));
        }
        let installed = INSTALLATION.get().ok_or_else(|| {
            AgentdError::Invalid("runtime.codex supervisor is not installed".to_string())
        })?;
        let deadline = Instant::now() + maximum_wait;
        loop {
            let notified = installed.status_changed.notified();
            let current = status(installed);
            if current.started {
                return Ok(current);
            }
            timeout_at(deadline, notified).await.map_err(|_| {
                AgentdError::Protocol(
                    "runtime.codex supervisor startup reconciliation timed out".to_string(),
                )
            })?;
        }
    }

    pub(crate) async fn reserve_agentd_schedule(
        deadline_ms: u64,
    ) -> Result<RuntimeCodexSchedulePermitV1, AgentdError> {
        let installed = Arc::clone(INSTALLATION.get().ok_or_else(|| {
            AgentdError::Invalid(
                "canonical intelligence has no installed runtime.codex supervisor".to_string(),
            )
        })?);
        let current = status(&installed);
        if !current.admission_ready {
            return Err(AgentdError::Protocol(format!(
                "runtime.codex supervisor is not admission-ready: started={} degraded={} unresolved={} post_dispatch={}",
                current.started,
                current.degraded,
                current.unresolved,
                current.unresolved_post_dispatch
            )));
        }
        let now_ms = unix_time_ms()?;
        let remaining_ms = deadline_ms.checked_sub(now_ms).filter(|value| *value > 0).ok_or_else(
            || AgentdError::Invalid("runtime.codex schedule deadline has elapsed".to_string()),
        )?;
        let permit = timeout(
            Duration::from_millis(remaining_ms),
            installed.sender.clone().reserve_owned(),
        )
        .await
        .map_err(|_| {
            AgentdError::Protocol(
                "runtime.codex queue reservation exceeded the run deadline".to_string(),
            )
        })?
        .map_err(|_| AgentdError::Protocol("runtime.codex supervisor queue closed".to_string()))?;
        let current = status(&installed);
        if !current.admission_ready {
            return Err(AgentdError::Protocol(format!(
                "runtime.codex supervisor changed state while reserving capacity: started={} degraded={} unresolved={} post_dispatch={}",
                current.started,
                current.degraded,
                current.unresolved,
                current.unresolved_post_dispatch
            )));
        }
        Ok(RuntimeCodexSchedulePermitV1 {
            installation: installed,
            permit: Some(permit),
        })
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
        publish_recovery_status(&installed, &initial);

        let permits = Arc::new(Semaphore::new(installed.executor.maximum_in_flight()));
        let mut workers = JoinSet::new();
        let mut recovery = interval(RECOVERY_RETRY_INTERVAL);
        recovery.set_missed_tick_behavior(MissedTickBehavior::Skip);

        loop {
            tokio::select! {
                biased;
                _ = lifetime.cancelled() => break,
                joined = workers.join_next(), if !workers.is_empty() => {
                    observe_worker(&installed, joined).await?;
                    if workers.is_empty() {
                        let report = installed.executor
                            .reconcile_pending(owner.clone(), lifetime.child_token())
                            .await?;
                        publish_recovery_status(&installed, &report);
                    }
                }
                _ = recovery.tick(), if installed.degraded.load(Ordering::Acquire) && workers.is_empty() => {
                    let report = installed.executor
                        .reconcile_pending(owner.clone(), lifetime.child_token())
                        .await?;
                    publish_recovery_status(&installed, &report);
                }
                job = receiver.recv() => {
                    let job = job.ok_or_else(|| {
                        AgentdError::Protocol("runtime.codex supervisor queue closed".to_string())
                    })?;
                    let executor = Arc::clone(&installed.executor);
                    let owner = owner.clone();
                    let identity = identity.clone();
                    let lifetime = lifetime.clone();
                    let permits = Arc::clone(&permits);
                    workers.spawn(async move {
                        let permit = permits.acquire_owned().await.map_err(|_| {
                            AgentdError::Protocol("runtime.codex worker permits closed".to_string())
                        })?;
                        let run_id = job.input.run_id().to_string();
                        let digest = job.input.digest()?;
                        let result = run_job(executor, owner, identity, job, lifetime).await;
                        drop(permit);
                        Ok::<_, AgentdError>((run_id, digest, result))
                    });
                }
            }
        }

        installed.started.store(false, Ordering::Release);
        installed.closed.store(true, Ordering::Release);
        installed.status_changed.notify_waiters();
        cancel_active(&installed)?;
        while let Ok(job) = receiver.try_recv() {
            let run_id = job.input.run_id().to_string();
            let digest = job.input.digest()?;
            job.cancellation.cancel();
            if let Err(error) = cancel_queued(&identity, &job).await {
                eprintln!(
                    "runtime.codex queued run {run_id} could not publish shutdown cancellation: {error}"
                );
            }
            remove_active(&installed, &run_id, digest)?;
        }
        match timeout(WORKER_DRAIN_GRACE, async {
            while let Some(joined) = workers.join_next().await {
                observe_worker(&installed, Some(joined)).await?;
            }
            Ok::<(), AgentdError>(())
        })
        .await
        {
            Ok(result) => result?,
            Err(_) => {
                workers.abort_all();
                while let Some(joined) = workers.join_next().await {
                    let _ = observe_worker(&installed, Some(joined)).await;
                }
                return Err(AgentdError::Protocol(
                    "runtime.codex workers did not drain before the shutdown deadline"
                        .to_string(),
                ));
            }
        }
        Ok(())
    }
}

fn increment_atomic(counter: &AtomicUsize, message: &str) -> Result<(), AgentdError> {
    counter
        .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| value.checked_add(1))
        .map(|_| ())
        .map_err(|_| AgentdError::Protocol(message.to_string()))
}

fn status(installed: &Installation) -> RuntimeCodexSupervisorStatusV1 {
    let started = installed.started.load(Ordering::Acquire);
    let degraded = installed.degraded.load(Ordering::Acquire);
    let closed = installed.closed.load(Ordering::Acquire);
    let unresolved = installed.unresolved.load(Ordering::Acquire);
    let unresolved_post_dispatch = installed
        .unresolved_post_dispatch
        .load(Ordering::Acquire);
    RuntimeCodexSupervisorStatusV1 {
        started,
        // A pre-dispatch manifest is degraded historical work but cannot have
        // crossed the effect boundary. It may coexist with fresh admissions so
        // the exact authenticated retry can finish that first dispatch. Any
        // unresolved post-dispatch operation closes new admission.
        admission_ready: started && !closed && unresolved_post_dispatch == 0,
        degraded,
        unresolved,
        unresolved_post_dispatch,
    }
}

fn publish_recovery_status(
    installed: &Installation,
    report: &RuntimeCodexReconcileReportV1,
) {
    installed
        .unresolved
        .store(report.unresolved, Ordering::Release);
    installed
        .unresolved_post_dispatch
        .store(report.unresolved_post_dispatch, Ordering::Release);
    installed
        .degraded
        .store(report.unresolved > 0, Ordering::Release);
    installed.started.store(true, Ordering::Release);
    installed.status_changed.notify_waiters();
}

async fn observe_worker(
    installed: &Installation,
    joined: Option<
        Result<
            Result<(String, Digest32, Result<(), AgentdError>), AgentdError>,
            tokio::task::JoinError,
        >,
    >,
) -> Result<(), AgentdError> {
    let joined = joined.ok_or_else(|| {
        AgentdError::Protocol("runtime.codex worker set unexpectedly became empty".to_string())
    })?;
    let (run_id, digest, result) = joined
        .map_err(|error| AgentdError::Protocol(format!("runtime.codex worker task failed: {error}")))??;
    remove_active(installed, &run_id, digest)?;
    result
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

fn cancel_active(installed: &Installation) -> Result<(), AgentdError> {
    let active = installed.active.lock().map_err(|_| {
        AgentdError::Protocol("runtime.codex active registry is poisoned".to_string())
    })?;
    for job in active.values() {
        job.cancellation.cancel();
    }
    Ok(())
}

fn unix_time_ms() -> Result<u64, AgentdError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AgentdError::Protocol("system clock predates Unix epoch".to_string()))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|_| AgentdError::Protocol("system clock exceeds u64 milliseconds".to_string()))
}
