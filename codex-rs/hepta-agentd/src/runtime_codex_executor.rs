//! Agentd-owned process adapter for the existing `runtime.codex` worker.
//!
//! The adapter deliberately does not implement another model runtime. It owns
//! exact process invocation, immutable operation identities, bounded I/O,
//! restart reconciliation and terminal archive publication. `hepta-infer-worker`
//! remains the physical App Server caller and final-use authority consumer.

use std::collections::BTreeMap;
use std::fmt;
use std::future::Future;
use std::path::Path;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Weak;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use tokio::sync::Mutex as AsyncMutex;
use tokio::sync::RwLock;
use tokio::sync::Semaphore;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdIdentity;

#[path = "runtime_codex_archive.rs"]
mod archive;
#[path = "runtime_codex_executor_persistence.rs"]
mod persistence;
#[path = "runtime_codex_executor_process.rs"]
mod process;
pub use process::RuntimeCodexSupervisorStatusV1;

const JOB_SCHEMA_VERSION: u32 = 1;
const MAX_EXECUTABLE_BYTES: u64 = 2 * 1024 * 1024 * 1024;
const MAX_PROMPT_BYTES: usize = 32 * 1024;
const MAX_CONTEXT_QUERY_BYTES: usize = 2 * 1024;
const MAX_MODEL_BYTES: usize = 256;
const MAX_PROCESS_OUTPUT_BYTES: usize = 2 * 1024 * 1024;
const MAX_PROCESS_ERROR_BYTES: usize = 128 * 1024;
const MAX_RECONCILE_OPERATIONS: usize = 1_024;
const MAXIMUM_IN_FLIGHT_LIMIT: usize = 16_384;
const MAX_EXECUTION_TIMEOUT: Duration = Duration::from_secs(3_600);
const MIN_INTERRUPT_GRACE: Duration = Duration::from_millis(100);
const MAX_INTERRUPT_GRACE: Duration = Duration::from_secs(30);

pub type RuntimeCodexExecutionFuture<'a> = Pin<
    Box<
        dyn Future<Output = Result<RuntimeCodexExecutionReceiptV1, AgentdError>>
            + Send
            + 'a,
    >,
>;

pub type RuntimeCodexReconcileFuture<'a> = Pin<
    Box<
        dyn Future<Output = Result<RuntimeCodexReconcileReportV1, AgentdError>>
            + Send
            + 'a,
    >,
>;

/// Minimal immutable owner identity required by the process boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeCodexOwnerV1 {
    agent_id: AgentId,
    generation: u64,
    agentd_socket: PathBuf,
    home_root: PathBuf,
}

impl RuntimeCodexOwnerV1 {
    pub fn new(
        agent_id: AgentId,
        generation: u64,
        agentd_socket: PathBuf,
        home_root: PathBuf,
    ) -> Result<Self, AgentdError> {
        if generation == 0 || !agentd_socket.is_absolute() || !home_root.is_absolute() {
            return Err(AgentdError::Invalid(
                "runtime.codex owner requires a non-zero generation and absolute paths"
                    .to_string(),
            ));
        }
        Ok(Self {
            agent_id,
            generation,
            agentd_socket,
            home_root,
        })
    }

    pub fn from_agentd(identity: &AgentdIdentity) -> Self {
        Self {
            agent_id: identity.agent_id.clone(),
            generation: identity.spawn_generation,
            agentd_socket: identity.control_socket.clone(),
            home_root: identity.home_root.clone(),
        }
    }

    pub fn agent_id(&self) -> &AgentId {
        &self.agent_id
    }

    pub const fn generation(&self) -> u64 {
        self.generation
    }

    pub fn agentd_socket(&self) -> &Path {
        &self.agentd_socket
    }

    pub fn home_root(&self) -> &Path {
        &self.home_root
    }
}

/// Host-derived physical input. Request bytes cannot construct this value in
/// the Agentd product path; its constructor validates every bounded field.
#[derive(Clone, Eq, PartialEq)]
pub struct RuntimeCodexExecutionInputV1 {
    run_id: StableId,
    expected_revision: u64,
    context_digest: Digest32,
    envelope_digest: Digest32,
    prompt: String,
    context_query: Option<String>,
    model: String,
    deadline_ms: u64,
}

impl fmt::Debug for RuntimeCodexExecutionInputV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RuntimeCodexExecutionInputV1")
            .field("run_id", &self.run_id)
            .field("expected_revision", &self.expected_revision)
            .field("context_digest", &self.context_digest)
            .field("envelope_digest", &self.envelope_digest)
            .field("prompt_bytes", &self.prompt.len())
            .field(
                "context_query_bytes",
                &self.context_query.as_ref().map(String::len),
            )
            .field("model", &self.model)
            .field("deadline_ms", &self.deadline_ms)
            .finish()
    }
}

impl RuntimeCodexExecutionInputV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        run_id: StableId,
        expected_revision: u64,
        context_digest: Digest32,
        envelope_digest: Digest32,
        prompt: String,
        context_query: Option<String>,
        model: String,
        deadline_ms: u64,
    ) -> Result<Self, AgentdError> {
        if expected_revision == 0
            || context_digest.is_zero()
            || envelope_digest.is_zero()
            || prompt.is_empty()
            || prompt.len() > MAX_PROMPT_BYTES
            || context_query
                .as_ref()
                .is_some_and(|query| query.is_empty() || query.len() > MAX_CONTEXT_QUERY_BYTES)
            || model.is_empty()
            || model.len() > MAX_MODEL_BYTES
            || model.as_bytes().contains(&0)
            || deadline_ms == 0
        {
            return Err(AgentdError::Invalid(
                "invalid bounded runtime.codex execution input".to_string(),
            ));
        }
        Ok(Self {
            run_id,
            expected_revision,
            context_digest,
            envelope_digest,
            prompt,
            context_query,
            model,
            deadline_ms,
        })
    }

    pub fn run_id(&self) -> &StableId {
        &self.run_id
    }

    pub const fn expected_revision(&self) -> u64 {
        self.expected_revision
    }

    pub const fn context_digest(&self) -> Digest32 {
        self.context_digest
    }

    pub const fn envelope_digest(&self) -> Digest32 {
        self.envelope_digest
    }

    pub fn prompt(&self) -> &str {
        &self.prompt
    }

    pub fn context_query(&self) -> Option<&str> {
        self.context_query.as_deref()
    }

    pub fn model(&self) -> &str {
        &self.model
    }

    pub const fn deadline_ms(&self) -> u64 {
        self.deadline_ms
    }

    fn digest(&self) -> Result<Digest32, AgentdError> {
        #[derive(Serialize)]
        struct DigestInput<'a> {
            domain: &'static str,
            run_id: &'a str,
            expected_revision: u64,
            context_digest: String,
            envelope_digest: String,
            prompt: &'a str,
            context_query: Option<&'a str>,
            model: &'a str,
            deadline_ms: u64,
        }
        let bytes = serde_json::to_vec(&DigestInput {
            domain: "hepta.runtime-codex.execution-input.v1",
            run_id: self.run_id.as_str(),
            expected_revision: self.expected_revision,
            context_digest: self.context_digest.to_string(),
            envelope_digest: self.envelope_digest.to_string(),
            prompt: &self.prompt,
            context_query: self.context_query.as_deref(),
            model: &self.model,
            deadline_ms: self.deadline_ms,
        })?;
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeCodexExecutionReceiptV1 {
    pub schema_version: u32,
    pub run_id: String,
    pub input_digest: String,
    pub worker_artifact_digest: String,
    pub reconciled: bool,
    pub idempotent: bool,
    pub process_exit_code: Option<i32>,
    pub output_digest: String,
    pub output: NativeRunOutput,
}

impl RuntimeCodexExecutionReceiptV1 {
    pub fn succeeded(&self) -> bool {
        self.output.succeeded()
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct RuntimeCodexReconcileReportV1 {
    pub scanned: usize,
    pub already_terminal: usize,
    pub reconciled_terminal: usize,
    pub unresolved: usize,
    pub unresolved_pre_dispatch: usize,
    pub unresolved_post_dispatch: usize,
    pub archived_terminal: usize,
}

pub trait RuntimeCodexExecutorV1: Send + Sync {
    fn execute<'a>(
        &'a self,
        owner: RuntimeCodexOwnerV1,
        input: RuntimeCodexExecutionInputV1,
        cancellation: CancellationToken,
    ) -> RuntimeCodexExecutionFuture<'a>;

    fn reconcile_pending<'a>(
        &'a self,
        owner: RuntimeCodexOwnerV1,
        cancellation: CancellationToken,
    ) -> RuntimeCodexReconcileFuture<'a>;
}

/// Exact process configuration selected by the trusted host.
pub struct ProcessRuntimeCodexExecutorV1 {
    worker_executable: PathBuf,
    worker_artifact_digest: Digest32,
    final_use_authority_config: PathBuf,
    final_use_authority_digest: Digest32,
    journal_root: PathBuf,
    archive_root: PathBuf,
    maximum_in_flight: usize,
    interrupt_grace: Duration,
    /// Startup/periodic reconciliation excludes fresh execution. Once recovery
    /// has completed, unrelated run identities may execute concurrently.
    recovery_gate: RwLock<()>,
    execution_permits: Arc<Semaphore>,
    operation_locks: std::sync::Mutex<BTreeMap<String, Weak<AsyncMutex<()>>>>,
}

impl fmt::Debug for ProcessRuntimeCodexExecutorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProcessRuntimeCodexExecutorV1")
            .field("worker_executable", &self.worker_executable)
            .field("worker_artifact_digest", &self.worker_artifact_digest)
            .field(
                "final_use_authority_config",
                &self.final_use_authority_config,
            )
            .field("final_use_authority_digest", &self.final_use_authority_digest)
            .field("journal_root", &self.journal_root)
            .field("archive_root", &self.archive_root)
            .field("maximum_in_flight", &self.maximum_in_flight)
            .field("interrupt_grace", &self.interrupt_grace)
            .finish_non_exhaustive()
    }
}

impl ProcessRuntimeCodexExecutorV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        worker_executable: PathBuf,
        worker_artifact_digest: Digest32,
        final_use_authority_config: PathBuf,
        final_use_authority_digest: Digest32,
        journal_root: PathBuf,
        maximum_in_flight: usize,
        interrupt_grace: Duration,
    ) -> Result<Self, AgentdError> {
        if worker_artifact_digest.is_zero()
            || final_use_authority_digest.is_zero()
            || !(1..=MAXIMUM_IN_FLIGHT_LIMIT).contains(&maximum_in_flight)
            || !(MIN_INTERRUPT_GRACE..=MAX_INTERRUPT_GRACE).contains(&interrupt_grace)
        {
            return Err(AgentdError::Invalid(
                "invalid runtime.codex process executor limits or digest".to_string(),
            ));
        }
        persistence::validate_protected_file(
            &worker_executable,
            /*executable*/ true,
            worker_artifact_digest,
        )?;
        persistence::validate_protected_file(
            &final_use_authority_config,
            /*executable*/ false,
            final_use_authority_digest,
        )?;
        persistence::prepare_private_directory(&journal_root)?;
        let archive_root = archive::archive_root_for(&journal_root)?;
        persistence::prepare_private_directory(&archive_root)?;
        Ok(Self {
            worker_executable,
            worker_artifact_digest,
            final_use_authority_config,
            final_use_authority_digest,
            journal_root,
            archive_root,
            maximum_in_flight,
            interrupt_grace,
            recovery_gate: RwLock::new(()),
            execution_permits: Arc::new(Semaphore::new(maximum_in_flight)),
            operation_locks: std::sync::Mutex::new(BTreeMap::new()),
        })
    }

    pub const fn worker_artifact_digest(&self) -> Digest32 {
        self.worker_artifact_digest
    }

    pub const fn final_use_authority_digest(&self) -> Digest32 {
        self.final_use_authority_digest
    }

    pub const fn maximum_in_flight(&self) -> usize {
        self.maximum_in_flight
    }

    pub fn journal_root(&self) -> &Path {
        &self.journal_root
    }

    pub fn archive_root(&self) -> &Path {
        &self.archive_root
    }

    fn operation_lock(&self, run_id: &str) -> Result<Arc<AsyncMutex<()>>, AgentdError> {
        let mut locks = self.operation_locks.lock().map_err(|_| {
            AgentdError::Protocol("runtime.codex operation-lock registry is poisoned".to_string())
        })?;
        locks.retain(|_, lock| lock.strong_count() > 0);
        if let Some(lock) = locks.get(run_id).and_then(Weak::upgrade) {
            return Ok(lock);
        }
        let lock = Arc::new(AsyncMutex::new(()));
        locks.insert(run_id.to_string(), Arc::downgrade(&lock));
        Ok(lock)
    }

    async fn execute_inner(
        &self,
        owner: RuntimeCodexOwnerV1,
        input: RuntimeCodexExecutionInputV1,
        cancellation: CancellationToken,
    ) -> Result<RuntimeCodexExecutionReceiptV1, AgentdError> {
        let _recovery_guard = self.recovery_gate.read().await;
        let _execution_permit = Arc::clone(&self.execution_permits)
            .acquire_owned()
            .await
            .map_err(|_| AgentdError::Protocol("runtime.codex execution is closed".to_string()))?;
        let operation_lock = self.operation_lock(input.run_id().as_str())?;
        let _operation_guard = operation_lock.lock().await;

        persistence::validate_owner(self, &owner)?;
        persistence::revalidate_external_files(self)?;
        let input_digest = input.digest()?;
        if let Some(receipt) =
            archive::read_archived_receipt(self, &owner, &input, input_digest)?
        {
            return Ok(RuntimeCodexExecutionReceiptV1 {
                idempotent: true,
                ..receipt
            });
        }
        archive::compact_terminal_operations(self, &owner)?;
        let prepared = persistence::prepare_operation(self, &owner, &input, input_digest)?;
        if let Some(receipt) =
            persistence::read_receipt_if_present(&prepared.paths.receipt, &prepared.manifest)?
        {
            return Ok(RuntimeCodexExecutionReceiptV1 {
                idempotent: true,
                ..receipt
            });
        }
        let fresh_input = if persistence::dispatch_is_fenced(
            &prepared.paths,
            &prepared.manifest,
        )? {
            None
        } else {
            Some(&input)
        };
        let receipt = process::spawn_worker(
            self,
            &owner,
            &prepared.manifest,
            &prepared.paths,
            fresh_input,
            cancellation,
        )
        .await?;
        persistence::write_receipt(
            &prepared.paths.receipt,
            &prepared.manifest,
            &receipt,
        )?;
        archive::compact_terminal_operations(self, &owner)?;
        Ok(receipt)
    }

    async fn reconcile_pending_inner(
        &self,
        owner: RuntimeCodexOwnerV1,
        cancellation: CancellationToken,
    ) -> Result<RuntimeCodexReconcileReportV1, AgentdError> {
        let _recovery_guard = self.recovery_gate.write().await;
        persistence::validate_owner(self, &owner)?;
        persistence::revalidate_external_files(self)?;
        let archived_terminal = archive::compact_terminal_operations(self, &owner)?;
        let directories = persistence::list_operation_directories(&self.journal_root)?;
        let mut report = RuntimeCodexReconcileReportV1 {
            archived_terminal,
            ..RuntimeCodexReconcileReportV1::default()
        };
        for directory in directories {
            if cancellation.is_cancelled() {
                break;
            }
            report.scanned = report
                .scanned
                .checked_add(1)
                .ok_or_else(|| AgentdError::Protocol("recovery counter overflow".to_string()))?;
            let paths = persistence::OperationPaths::for_directory(&directory);
            let manifest = persistence::read_manifest(&paths.manifest)?;
            persistence::validate_manifest_owner(
                &manifest,
                &owner,
                self.worker_artifact_digest,
            )?;
            if persistence::read_receipt_if_present(&paths.receipt, &manifest)?.is_some() {
                report.already_terminal = report
                    .already_terminal
                    .checked_add(1)
                    .ok_or_else(|| {
                        AgentdError::Protocol("recovery counter overflow".to_string())
                    })?;
                continue;
            }
            if !persistence::dispatch_is_fenced(&paths, &manifest)? {
                report.unresolved = report.unresolved.checked_add(1).ok_or_else(|| {
                    AgentdError::Protocol("recovery counter overflow".to_string())
                })?;
                report.unresolved_pre_dispatch = report
                    .unresolved_pre_dispatch
                    .checked_add(1)
                    .ok_or_else(|| {
                        AgentdError::Protocol("recovery counter overflow".to_string())
                    })?;
                continue;
            }
            match process::spawn_worker(
                self,
                &owner,
                &manifest,
                &paths,
                None,
                cancellation.child_token(),
            )
            .await
            {
                Ok(receipt) => {
                    persistence::write_receipt(&paths.receipt, &manifest, &receipt)?;
                    report.reconciled_terminal = report
                        .reconciled_terminal
                        .checked_add(1)
                        .ok_or_else(|| {
                            AgentdError::Protocol("recovery counter overflow".to_string())
                        })?;
                }
                Err(_) => {
                    report.unresolved = report.unresolved.checked_add(1).ok_or_else(|| {
                        AgentdError::Protocol("recovery counter overflow".to_string())
                    })?;
                    report.unresolved_post_dispatch = report
                        .unresolved_post_dispatch
                        .checked_add(1)
                        .ok_or_else(|| {
                            AgentdError::Protocol("recovery counter overflow".to_string())
                        })?;
                }
            }
        }
        report.archived_terminal = report
            .archived_terminal
            .checked_add(archive::compact_terminal_operations(self, &owner)?)
            .ok_or_else(|| AgentdError::Protocol("archive counter overflow".to_string()))?;
        Ok(report)
    }
}

impl RuntimeCodexExecutorV1 for ProcessRuntimeCodexExecutorV1 {
    fn execute<'a>(
        &'a self,
        owner: RuntimeCodexOwnerV1,
        input: RuntimeCodexExecutionInputV1,
        cancellation: CancellationToken,
    ) -> RuntimeCodexExecutionFuture<'a> {
        Box::pin(async move { self.execute_inner(owner, input, cancellation).await })
    }

    fn reconcile_pending<'a>(
        &'a self,
        owner: RuntimeCodexOwnerV1,
        cancellation: CancellationToken,
    ) -> RuntimeCodexReconcileFuture<'a> {
        Box::pin(async move { self.reconcile_pending_inner(owner, cancellation).await })
    }
}

#[cfg(test)]
#[path = "runtime_codex_executor_tests.rs"]
mod tests;
