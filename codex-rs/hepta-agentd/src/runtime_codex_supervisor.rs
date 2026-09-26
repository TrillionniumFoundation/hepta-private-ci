use std::collections::BTreeMap;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::atomic::{AtomicBool, Ordering};

use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

use super::super::{
    ProcessRuntimeCodexExecutorV1, RuntimeCodexExecutionInputV1, RuntimeCodexExecutorV1,
    RuntimeCodexOwnerV1,
};
use crate::{
    AgentdError, AgentdIdentity, PreparedAgentdIntelligenceRunV1, RunPhase, RunReceipt,
};

#[path = "runtime_codex_supervisor_worker.rs"]
mod worker;
use worker::{cancel_queued, run_job};

const MAX_QUEUE_CAPACITY: usize = 256;

trait InputProvider: Send + Sync {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        prepared: &PreparedAgentdIntelligenceRunV1,
        receipt: &RunReceipt,
    ) -> Result<RuntimeCodexExecutionInputV1, AgentdError>;
}

impl<F> InputProvider for F
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

struct Installation {
    executor: Arc<ProcessRuntimeCodexExecutorV1>,
    provider: Arc<dyn InputProvider>,
    sender: mpsc::Sender<Job>,
    receiver: std::sync::Mutex<Option<mpsc::Receiver<Job>>>,
    active: std::sync::Mutex<BTreeMap<String, Digest32>>,
    ready: AtomicBool,
    closed: AtomicBool,
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

static INSTALLATION: OnceLock<Arc<Installation>> = OnceLock::new();

impl ProcessRuntimeCodexExecutorV1 {
    /// Install the one process-local runtime.codex owner before `agentd::run`.
    /// The host provider, not request bytes, derives prompt, model and query.
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
                ready: AtomicBool::new(false),
                closed: AtomicBool::new(false),
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

    pub(crate) fn schedule_canonical_run(
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        prepared: &PreparedAgentdIntelligenceRunV1,
        receipt: &RunReceipt,
    ) -> Result<bool, AgentdError> {
        let installed = INSTALLATION.get().ok_or_else(|| {
            AgentdError::Invalid(
                "canonical intelligence has no installed runtime.codex supervisor".to_string(),
            )
        })?;
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
        let input = installed
            .provider
            .build(identity, record, prepared, receipt)?;
        validate_input(record, prepared, receipt, &input)?;
        let digest = input.digest()?;
        let run_id = input.run_id().to_string();
        {
            let mut active = installed.active.lock().map_err(|_| {
                AgentdError::Protocol("runtime.codex active registry is poisoned".to_string())
            })?;
            match active.get(&run_id) {
                Some(existing) if *existing == digest => return Ok(false),
                Some(_) => {
                    return Err(AgentdError::Protocol(
                        "runtime.codex run identity has queued semantic drift".to_string(),
                    ));
                }
                None => {
                    active.insert(run_id.clone(), digest);
                }
            }
        }
        let job = Job {
            input,
            cancellation: CancellationToken::new(),
        };
        if let Err(error) = installed.sender.try_send(job) {
            remove_active(installed, &run_id, digest)?;
            return Err(AgentdError::Protocol(format!(
                "runtime.codex supervisor rejected queued run: {error}"
            )));
        }
        Ok(true)
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
        installed
            .executor
            .reconcile_pending(owner.clone(), lifetime.child_token())
            .await?;
        installed.ready.store(true, Ordering::Release);

        loop {
            let job = tokio::select! {
                _ = lifetime.cancelled() => break,
                job = receiver.recv() => job.ok_or_else(|| {
                    AgentdError::Protocol("runtime.codex supervisor queue closed".to_string())
                })?,
            };
            let run_id = job.input.run_id().to_string();
            let digest = job.input.digest()?;
            let result = run_job(
                Arc::clone(&installed.executor),
                owner.clone(),
                identity.clone(),
                job,
                lifetime.clone(),
            )
            .await;
            remove_active(&installed, &run_id, digest)?;
            result?;
        }

        installed.ready.store(false, Ordering::Release);
        installed.closed.store(true, Ordering::Release);
        while let Ok(job) = receiver.try_recv() {
            cancel_queued(&identity, &job).await?;
            remove_active(&installed, job.input.run_id().as_str(), job.input.digest()?)?;
        }
        Ok(())
    }
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
    if active.get(run_id).is_some_and(|observed| *observed != digest) {
        return Err(AgentdError::Protocol(
            "runtime.codex active cleanup observed semantic drift".to_string(),
        ));
    }
    active.remove(run_id);
    Ok(())
}
