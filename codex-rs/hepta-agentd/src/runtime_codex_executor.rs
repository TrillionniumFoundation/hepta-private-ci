//! Agentd-owned process adapter for the existing `runtime.codex` worker.
//!
//! The adapter deliberately does not implement another model runtime. It owns
//! only the exact process invocation, an immutable operation manifest, bounded
//! process I/O, and restart reconciliation. The `hepta-infer-worker` remains the
//! physical App Server caller and therefore retains final-use authorization,
//! dispatch fencing, terminal observation, and its native no-replay journal.
//!
//! A normal invocation is permitted only when the operation directory is first
//! created. Any duplicate, crash recovery, or unknown acknowledgement is routed
//! through `--resume`; this module never recreates a physical `turn/start` for an
//! operation whose first process might already have crossed the effect boundary.

use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::future::Future;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::pin::Pin;
use std::process::ExitStatus;
use std::process::Stdio;
use std::str::FromStr;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use tokio::io::AsyncRead;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::process::Child;
use tokio::process::Command;
use tokio::time::Instant;
use tokio::time::sleep;
use tokio::time::sleep_until;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdIdentity;

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
const MANIFEST_FILE: &str = "manifest.json";
const RECEIPT_FILE: &str = "receipt.json";
const NATIVE_JOURNAL_FILE: &str = "native-control.journal";

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

    pub(crate) fn from_agentd(identity: &AgentdIdentity) -> Self {
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

/// Exact process configuration selected by the trusted host. Both external
/// files are digest-pinned and re-observed immediately before every spawn.
pub struct ProcessRuntimeCodexExecutorV1 {
    worker_executable: PathBuf,
    worker_artifact_digest: Digest32,
    final_use_authority_config: PathBuf,
    final_use_authority_digest: Digest32,
    journal_root: PathBuf,
    maximum_in_flight: usize,
    interrupt_grace: Duration,
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
            .field("maximum_in_flight", &self.maximum_in_flight)
            .field("interrupt_grace", &self.interrupt_grace)
            .finish()
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
        validate_protected_file(
            &worker_executable,
            /*executable*/ true,
            worker_artifact_digest,
        )?;
        validate_protected_file(
            &final_use_authority_config,
            /*executable*/ false,
            final_use_authority_digest,
        )?;
        prepare_private_directory(&journal_root)?;
        Ok(Self {
            worker_executable,
            worker_artifact_digest,
            final_use_authority_config,
            final_use_authority_digest,
            journal_root,
            maximum_in_flight,
            interrupt_grace,
        })
    }

    pub fn worker_artifact_digest(&self) -> Digest32 {
        self.worker_artifact_digest
    }

    pub fn journal_root(&self) -> &Path {
        &self.journal_root
    }

    async fn execute_inner(
        &self,
        owner: RuntimeCodexOwnerV1,
        input: RuntimeCodexExecutionInputV1,
        cancellation: CancellationToken,
    ) -> Result<RuntimeCodexExecutionReceiptV1, AgentdError> {
        self.validate_owner(&owner)?;
        validate_input_deadline(&input)?;
        self.revalidate_external_files()?;
        let input_digest = input.digest()?;
        let (paths, manifest, existing) = self.prepare_operation(&owner, &input, input_digest)?;
        if let Some(receipt) = read_receipt_if_present(&paths.receipt, &manifest)? {
            return Ok(RuntimeCodexExecutionReceiptV1 {
                idempotent: true,
                ..receipt
            });
        }
        let reconciled = existing;
        let result = self
            .spawn_worker(
                &owner,
                &manifest,
                &paths,
                if reconciled { None } else { Some(&input) },
                cancellation,
            )
            .await?;
        if !result.output.terminal_observed {
            return Err(AgentdError::Protocol(
                "runtime.codex worker returned an indeterminate observation; recovery is reconcile-only"
                    .to_string(),
            ));
        }
        write_json_atomic(&paths.receipt, &result)?;
        Ok(result)
    }

    async fn reconcile_pending_inner(
        &self,
        owner: RuntimeCodexOwnerV1,
        cancellation: CancellationToken,
    ) -> Result<RuntimeCodexReconcileReportV1, AgentdError> {
        self.validate_owner(&owner)?;
        self.revalidate_external_files()?;
        let mut entries = std::fs::read_dir(&self.journal_root)?
            .collect::<Result<Vec<_>, _>>()?;
        entries.sort_by_key(std::fs::DirEntry::file_name);
        if entries.len() > MAX_RECONCILE_OPERATIONS {
            return Err(AgentdError::Protocol(format!(
                "runtime.codex recovery found {} operations, exceeding the bounded scan of {MAX_RECONCILE_OPERATIONS}",
                entries.len()
            )));
        }
        let mut report = RuntimeCodexReconcileReportV1::default();
        for entry in entries {
            if cancellation.is_cancelled() {
                break;
            }
            let metadata = entry.metadata()?;
            if !metadata.is_dir() {
                return Err(AgentdError::Protocol(format!(
                    "unexpected non-directory entry in runtime.codex journal root: {}",
                    entry.path().display()
                )));
            }
            report.scanned = report
                .scanned
                .checked_add(1)
                .ok_or_else(|| AgentdError::Protocol("recovery counter overflow".to_string()))?;
            let paths = OperationPaths::for_directory(entry.path());
            let manifest = read_manifest(&paths.manifest)?;
            validate_manifest_owner(&manifest, &owner, self.worker_artifact_digest)?;
            if read_receipt_if_present(&paths.receipt, &manifest)?.is_some() {
                report.already_terminal = report.already_terminal.checked_add(1).ok_or_else(|| {
                    AgentdError::Protocol("recovery counter overflow".to_string())
                })?;
                continue;
            }
            match self
                .spawn_worker(&owner, &manifest, &paths, None, cancellation.child_token())
                .await
            {
                Ok(receipt) if receipt.output.terminal_observed => {
                    write_json_atomic(&paths.receipt, &receipt)?;
                    report.reconciled_terminal = report
                        .reconciled_terminal
                        .checked_add(1)
                        .ok_or_else(|| {
                            AgentdError::Protocol("recovery counter overflow".to_string())
                        })?;
                }
                Ok(_) | Err(_) => {
                    // Do not turn one unresolved historical operation into a
                    // daemon-wide replay or startup failure. The durable job is
                    // retained and the report remains explicit.
                    report.unresolved = report.unresolved.checked_add(1).ok_or_else(|| {
                        AgentdError::Protocol("recovery counter overflow".to_string())
                    })?;
                }
            }
        }
        Ok(report)
    }

    fn validate_owner(&self, owner: &RuntimeCodexOwnerV1) -> Result<(), AgentdError> {
        require_canonical_directory(owner.home_root(), "runtime.codex owner home")?;
        if !owner.agentd_socket().is_absolute()
            || !self.journal_root.starts_with(owner.home_root())
            || self.journal_root == owner.home_root()
        {
            return Err(AgentdError::Invalid(
                "runtime.codex journal root must be a private descendant of Agent home"
                    .to_string(),
            ));
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            let home = std::fs::metadata(owner.home_root())?;
            let worker = std::fs::metadata(&self.worker_executable)?;
            let authority = std::fs::metadata(&self.final_use_authority_config)?;
            if worker.uid() != home.uid() || authority.uid() != home.uid() {
                return Err(AgentdError::Invalid(
                    "runtime.codex executable and authority config must share the Agent owner uid"
                        .to_string(),
                ));
            }
        }
        Ok(())
    }

    fn revalidate_external_files(&self) -> Result<(), AgentdError> {
        validate_protected_file(
            &self.worker_executable,
            /*executable*/ true,
            self.worker_artifact_digest,
        )?;
        validate_protected_file(
            &self.final_use_authority_config,
            /*executable*/ false,
            self.final_use_authority_digest,
        )
    }

    fn prepare_operation(
        &self,
        owner: &RuntimeCodexOwnerV1,
        input: &RuntimeCodexExecutionInputV1,
        input_digest: Digest32,
    ) -> Result<(OperationPaths, RuntimeCodexJobManifestV1, bool), AgentdError> {
        let operation_key = Digest32::of_bytes(input.run_id().as_str().as_bytes()).to_string();
        let directory = self.journal_root.join(operation_key);
        let paths = OperationPaths::for_directory(directory.clone());
        let timeout_ms = remaining_timeout_ms(input.deadline_ms())?;
        let expected = RuntimeCodexJobManifestV1 {
            schema_version: JOB_SCHEMA_VERSION,
            owner_agent_id: owner.agent_id().to_string(),
            owner_generation: owner.generation(),
            run_id: input.run_id().to_string(),
            expected_revision: input.expected_revision(),
            context_digest: input.context_digest().to_string(),
            envelope_digest: input.envelope_digest().to_string(),
            model: input.model().to_string(),
            deadline_ms: input.deadline_ms(),
            timeout_ms,
            input_digest: input_digest.to_string(),
            worker_artifact_digest: self.worker_artifact_digest.to_string(),
        };
        match std::fs::create_dir(&directory) {
            Ok(()) => {
                set_private_directory(&directory)?;
                write_new_json(&paths.manifest, &expected)?;
                sync_directory(&directory)?;
                Ok((paths, expected, false))
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                let observed = read_manifest(&paths.manifest)?;
                if observed != expected {
                    return Err(AgentdError::Protocol(
                        "runtime.codex operation identity already exists with semantic drift"
                            .to_string(),
                    ));
                }
                Ok((paths, observed, true))
            }
            Err(error) => Err(error.into()),
        }
    }

    async fn spawn_worker(
        &self,
        owner: &RuntimeCodexOwnerV1,
        manifest: &RuntimeCodexJobManifestV1,
        paths: &OperationPaths,
        fresh_input: Option<&RuntimeCodexExecutionInputV1>,
        cancellation: CancellationToken,
    ) -> Result<RuntimeCodexExecutionReceiptV1, AgentdError> {
        validate_manifest_owner(manifest, owner, self.worker_artifact_digest)?;
        self.revalidate_external_files()?;
        let reconciled = fresh_input.is_none();
        let mut command = Command::new(&self.worker_executable);
        command
            .current_dir(owner.home_root())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .arg("--profile")
            .arg("native-app-server")
            .arg("--agentd-socket")
            .arg(owner.agentd_socket())
            .arg("--agent-id")
            .arg(owner.agent_id().as_str())
            .arg("--generation")
            .arg(owner.generation().to_string())
            .arg("--model")
            .arg(&manifest.model)
            .arg("--journal")
            .arg(&paths.native_journal)
            .arg("--request-id")
            .arg(&manifest.run_id)
            .arg("--maximum-in-flight")
            .arg(self.maximum_in_flight.to_string())
            .arg("--final-use-authority-config")
            .arg(&self.final_use_authority_config)
            .arg("--timeout-ms")
            .arg(manifest.timeout_ms.to_string());
        if let Some(input) = fresh_input {
            if input.digest()?.to_string() != manifest.input_digest {
                return Err(AgentdError::Protocol(
                    "runtime.codex fresh input no longer matches its durable manifest"
                        .to_string(),
                ));
            }
            command
                .arg("--intelligence-run-id")
                .arg(input.run_id().as_str())
                .arg("--intelligence-revision")
                .arg(input.expected_revision().to_string())
                .arg("--intelligence-context-digest")
                .arg(input.context_digest().to_string())
                .arg("--intelligence-envelope-digest")
                .arg(input.envelope_digest().to_string());
            if let Some(query) = input.context_query() {
                command.arg("--context-query").arg(query);
            }
        } else {
            command.arg("--resume");
        }
        let mut child = command.spawn()?;
        let mut stdin = child.stdin.take().ok_or_else(|| {
            AgentdError::Protocol("runtime.codex worker stdin was not piped".to_string())
        })?;
        let stdout = child.stdout.take().ok_or_else(|| {
            AgentdError::Protocol("runtime.codex worker stdout was not piped".to_string())
        })?;
        let stderr = child.stderr.take().ok_or_else(|| {
            AgentdError::Protocol("runtime.codex worker stderr was not piped".to_string())
        })?;
        let prompt = fresh_input.map(|input| input.prompt().as_bytes().to_vec());
        let stdin_task = tokio::spawn(async move {
            if let Some(prompt) = prompt {
                stdin.write_all(&prompt).await?;
            }
            stdin.shutdown().await
        });
        let stdout_task = tokio::spawn(read_bounded(stdout, MAX_PROCESS_OUTPUT_BYTES));
        let stderr_task = tokio::spawn(read_bounded(stderr, MAX_PROCESS_ERROR_BYTES));

        let deadline = deadline_instant(manifest.deadline_ms, reconciled)?;
        let (status, stop) = wait_for_worker(
            &mut child,
            &cancellation,
            deadline,
            self.interrupt_grace,
        )
        .await?;
        stdin_task
            .await
            .map_err(|error| AgentdError::Protocol(format!("runtime.codex stdin task failed: {error}")))??;
        let stdout = stdout_task
            .await
            .map_err(|error| AgentdError::Protocol(format!("runtime.codex stdout task failed: {error}")))??;
        let stderr = stderr_task
            .await
            .map_err(|error| AgentdError::Protocol(format!("runtime.codex stderr task failed: {error}")))??;

        let output = parse_worker_output(&stdout).map_err(|parse_error| {
            let stderr = String::from_utf8_lossy(&stderr);
            AgentdError::Protocol(format!(
                "runtime.codex worker {stop} with status {status}; no valid bounded receipt: {parse_error}; stderr={}",
                bounded_text(&stderr, 1_024)
            ))
        })?;
        let output_digest = Digest32::of_bytes(&serde_json::to_vec(&output)?);
        let receipt = RuntimeCodexExecutionReceiptV1 {
            schema_version: JOB_SCHEMA_VERSION,
            run_id: manifest.run_id.clone(),
            input_digest: manifest.input_digest.clone(),
            worker_artifact_digest: manifest.worker_artifact_digest.clone(),
            reconciled,
            idempotent: false,
            process_exit_code: status.code(),
            output_digest: output_digest.to_string(),
            output,
        };
        if !receipt.output.terminal_observed {
            return Err(AgentdError::Protocol(format!(
                "runtime.codex worker {stop} without terminal observation; operation remains reconcile-only"
            )));
        }
        Ok(receipt)
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

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct RuntimeCodexJobManifestV1 {
    schema_version: u32,
    owner_agent_id: String,
    owner_generation: u64,
    run_id: String,
    expected_revision: u64,
    context_digest: String,
    envelope_digest: String,
    model: String,
    deadline_ms: u64,
    timeout_ms: u64,
    input_digest: String,
    worker_artifact_digest: String,
}

struct OperationPaths {
    directory: PathBuf,
    manifest: PathBuf,
    receipt: PathBuf,
    native_journal: PathBuf,
}

impl OperationPaths {
    fn for_directory(directory: PathBuf) -> Self {
        Self {
            manifest: directory.join(MANIFEST_FILE),
            receipt: directory.join(RECEIPT_FILE),
            native_journal: directory.join(NATIVE_JOURNAL_FILE),
            directory,
        }
    }
}

async fn wait_for_worker(
    child: &mut Child,
    cancellation: &CancellationToken,
    deadline: Instant,
    interrupt_grace: Duration,
) -> Result<(ExitStatus, &'static str), AgentdError> {
    tokio::select! {
        status = child.wait() => Ok((status?, "exited")),
        () = cancellation.cancelled() => {
            interrupt_and_wait(child, interrupt_grace).await.map(|status| (status, "cancelled"))
        }
        () = sleep_until(deadline) => {
            interrupt_and_wait(child, interrupt_grace).await.map(|status| (status, "deadline elapsed"))
        }
    }
}

async fn interrupt_and_wait(
    child: &mut Child,
    grace: Duration,
) -> Result<ExitStatus, AgentdError> {
    signal_interrupt(child)?;
    match timeout(grace, child.wait()).await {
        Ok(status) => Ok(status?),
        Err(_) => {
            child.start_kill()?;
            Ok(child.wait().await?)
        }
    }
}

#[cfg(unix)]
fn signal_interrupt(child: &mut Child) -> Result<(), AgentdError> {
    let pid = child
        .id()
        .ok_or_else(|| AgentdError::Protocol("runtime.codex child has no pid".to_string()))?;
    let pid = i32::try_from(pid)
        .map_err(|_| AgentdError::Protocol("runtime.codex child pid overflow".to_string()))?;
    // SAFETY: `pid` is the live child returned by Tokio and SIGINT carries no
    // pointer arguments. The return value is checked immediately.
    let result = unsafe { libc::kill(pid, libc::SIGINT) };
    if result == 0 {
        Ok(())
    } else {
        let error = std::io::Error::last_os_error();
        if error.kind() == std::io::ErrorKind::NotFound {
            Ok(())
        } else {
            Err(error.into())
        }
    }
}

#[cfg(not(unix))]
fn signal_interrupt(child: &mut Child) -> Result<(), AgentdError> {
    child.start_kill().map_err(Into::into)
}

async fn read_bounded<R>(mut reader: R, maximum: usize) -> Result<Vec<u8>, AgentdError>
where
    R: AsyncRead + Unpin,
{
    let limit = u64::try_from(maximum)
        .map_err(|_| AgentdError::Protocol("process output bound overflow".to_string()))?
        .saturating_add(1);
    let mut bytes = Vec::new();
    reader.take(limit).read_to_end(&mut bytes).await?;
    if bytes.len() > maximum {
        return Err(AgentdError::Protocol(
            "runtime.codex process output exceeded its bound".to_string(),
        ));
    }
    Ok(bytes)
}

fn parse_worker_output(bytes: &[u8]) -> Result<NativeRunOutput, AgentdError> {
    let last = bytes
        .split(|byte| *byte == b'\n')
        .rev()
        .find(|line| !line.iter().all(u8::is_ascii_whitespace))
        .ok_or_else(|| AgentdError::Protocol("runtime.codex worker emitted no receipt".to_string()))?;
    Ok(serde_json::from_slice(last)?)
}

fn validate_input_deadline(input: &RuntimeCodexExecutionInputV1) -> Result<(), AgentdError> {
    let now = unix_time_ms()?;
    if input.deadline_ms() <= now {
        return Err(AgentdError::Invalid(
            "runtime.codex execution deadline has elapsed".to_string(),
        ));
    }
    Ok(())
}

fn remaining_timeout_ms(deadline_ms: u64) -> Result<u64, AgentdError> {
    let remaining = deadline_ms.checked_sub(unix_time_ms()?).ok_or_else(|| {
        AgentdError::Invalid("runtime.codex execution deadline has elapsed".to_string())
    })?;
    let maximum = u64::try_from(MAX_EXECUTION_TIMEOUT.as_millis())
        .map_err(|_| AgentdError::Protocol("runtime.codex timeout bound overflow".to_string()))?;
    Ok(remaining.clamp(1, maximum))
}

fn deadline_instant(deadline_ms: u64, reconciled: bool) -> Result<Instant, AgentdError> {
    let now_ms = unix_time_ms()?;
    let duration = if deadline_ms > now_ms {
        Duration::from_millis(deadline_ms - now_ms)
    } else if reconciled {
        // A past execution deadline cannot authorize a new effect, but a
        // bounded thread/read reconciliation must still be allowed.
        Duration::from_secs(30)
    } else {
        return Err(AgentdError::Invalid(
            "runtime.codex execution deadline has elapsed".to_string(),
        ));
    };
    Ok(Instant::now() + duration.min(MAX_EXECUTION_TIMEOUT))
}

fn unix_time_ms() -> Result<u64, AgentdError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AgentdError::Protocol("system clock predates the Unix epoch".to_string()))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|_| AgentdError::Protocol("system clock exceeds u64 milliseconds".to_string()))
}

fn validate_manifest_owner(
    manifest: &RuntimeCodexJobManifestV1,
    owner: &RuntimeCodexOwnerV1,
    worker_digest: Digest32,
) -> Result<(), AgentdError> {
    if manifest.schema_version != JOB_SCHEMA_VERSION
        || manifest.owner_agent_id != owner.agent_id().to_string()
        || manifest.owner_generation != owner.generation()
        || manifest.worker_artifact_digest != worker_digest.to_string()
        || manifest.expected_revision == 0
        || StableId::new(manifest.run_id.clone()).is_err()
        || Digest32::from_str(&manifest.context_digest).is_err()
        || Digest32::from_str(&manifest.envelope_digest).is_err()
        || Digest32::from_str(&manifest.input_digest).is_err()
        || manifest.model.is_empty()
        || manifest.model.len() > MAX_MODEL_BYTES
        || manifest.timeout_ms == 0
        || manifest.timeout_ms
            > u64::try_from(MAX_EXECUTION_TIMEOUT.as_millis()).unwrap_or(u64::MAX)
    {
        return Err(AgentdError::Protocol(
            "runtime.codex durable manifest failed owner or semantic validation".to_string(),
        ));
    }
    Ok(())
}

fn read_manifest(path: &Path) -> Result<RuntimeCodexJobManifestV1, AgentdError> {
    read_bounded_json(path, 64 * 1024)
}

fn read_receipt_if_present(
    path: &Path,
    manifest: &RuntimeCodexJobManifestV1,
) -> Result<Option<RuntimeCodexExecutionReceiptV1>, AgentdError> {
    let receipt = match read_bounded_json(path, MAX_PROCESS_OUTPUT_BYTES + 64 * 1024) {
        Ok(value) => value,
        Err(AgentdError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok(None);
        }
        Err(error) => return Err(error),
    };
    if receipt.schema_version != JOB_SCHEMA_VERSION
        || receipt.run_id != manifest.run_id
        || receipt.input_digest != manifest.input_digest
        || receipt.worker_artifact_digest != manifest.worker_artifact_digest
        || !receipt.output.terminal_observed
    {
        return Err(AgentdError::Protocol(
            "runtime.codex durable receipt does not match its operation manifest".to_string(),
        ));
    }
    Ok(Some(receipt))
}

fn read_bounded_json<T>(path: &Path, maximum: usize) -> Result<T, AgentdError>
where
    T: for<'de> Deserialize<'de>,
{
    validate_read_path(path)?;
    let mut file = File::open(path)?;
    let metadata = file.metadata()?;
    let maximum_u64 = u64::try_from(maximum)
        .map_err(|_| AgentdError::Protocol("JSON read bound overflow".to_string()))?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > maximum_u64 {
        return Err(AgentdError::Protocol(format!(
            "invalid bounded runtime.codex file: {}",
            path.display()
        )));
    }
    let mut bytes = Vec::with_capacity(usize::try_from(metadata.len()).unwrap_or(maximum));
    file.take(maximum_u64.saturating_add(1))
        .read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        return Err(AgentdError::Protocol(
            "runtime.codex JSON exceeded its read bound".to_string(),
        ));
    }
    Ok(serde_json::from_slice(&bytes)?)
}

fn validate_read_path(path: &Path) -> Result<(), AgentdError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(AgentdError::Protocol(format!(
            "runtime.codex path is not a regular non-symlink file: {}",
            path.display()
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o022 != 0 {
            return Err(AgentdError::Protocol(format!(
                "runtime.codex file is group/other writable: {}",
                path.display()
            )));
        }
    }
    Ok(())
}

fn validate_protected_file(
    path: &Path,
    executable: bool,
    expected_digest: Digest32,
) -> Result<(), AgentdError> {
    if !path.is_absolute() || path.canonicalize()? != path {
        return Err(AgentdError::Invalid(format!(
            "runtime.codex protected path must be absolute, canonical and symlink-free: {}",
            path.display()
        )));
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > MAX_EXECUTABLE_BYTES
    {
        return Err(AgentdError::Invalid(format!(
            "invalid runtime.codex protected file: {}",
            path.display()
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = metadata.permissions().mode();
        if mode & 0o022 != 0 || (executable && mode & 0o100 == 0) {
            return Err(AgentdError::Invalid(format!(
                "runtime.codex protected file permissions are unsafe: {}",
                path.display()
            )));
        }
    }
    let observed = digest_file(path, metadata.len())?;
    if observed != expected_digest {
        return Err(AgentdError::GenerationFenced(format!(
            "runtime.codex protected file digest drifted: {}",
            path.display()
        )));
    }
    Ok(())
}

fn digest_file(path: &Path, expected_len: u64) -> Result<Digest32, AgentdError> {
    let mut file = File::open(path)?;
    let before = file.metadata()?;
    if before.len() != expected_len {
        return Err(AgentdError::GenerationFenced(
            "runtime.codex protected file changed before observation".to_string(),
        ));
    }
    let digest = Digest32::of_reader(&mut file, expected_len)?;
    let after = file.metadata()?;
    if before.len() != after.len() || before.modified()? != after.modified()? {
        return Err(AgentdError::GenerationFenced(
            "runtime.codex protected file changed during observation".to_string(),
        ));
    }
    Ok(digest)
}

fn prepare_private_directory(path: &Path) -> Result<(), AgentdError> {
    if !path.is_absolute() {
        return Err(AgentdError::Invalid(
            "runtime.codex journal root must be absolute".to_string(),
        ));
    }
    std::fs::create_dir_all(path)?;
    set_private_directory(path)?;
    require_canonical_directory(path, "runtime.codex journal root")
}

fn require_canonical_directory(path: &Path, label: &str) -> Result<(), AgentdError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_dir()
        || path.canonicalize()? != path
    {
        return Err(AgentdError::Invalid(format!(
            "{label} must be an absolute canonical non-symlink directory: {}",
            path.display()
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(AgentdError::Invalid(format!(
                "{label} must be owner-only: {}",
                path.display()
            )));
        }
    }
    Ok(())
}

fn set_private_directory(path: &Path) -> Result<(), AgentdError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}

fn write_new_json<T>(path: &Path, value: &T) -> Result<(), AgentdError>
where
    T: Serialize,
{
    let bytes = serde_json::to_vec(value)?;
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    Ok(())
}

fn write_json_atomic<T>(path: &Path, value: &T) -> Result<(), AgentdError>
where
    T: Serialize,
{
    let parent = path.parent().ok_or_else(|| {
        AgentdError::Protocol("runtime.codex receipt has no parent directory".to_string())
    })?;
    let bytes = serde_json::to_vec(value)?;
    let mut staging = None;
    for suffix in 0_u8..16 {
        let candidate = parent.join(format!(
            ".{}.{}.{}.tmp",
            path.file_name().and_then(|name| name.to_str()).unwrap_or("receipt"),
            std::process::id(),
            suffix
        ));
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        match options.open(&candidate) {
            Ok(mut file) => {
                file.write_all(&bytes)?;
                file.sync_all()?;
                staging = Some(candidate);
                break;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.into()),
        }
    }
    let staging = staging.ok_or_else(|| {
        AgentdError::Io(std::io::Error::new(
            std::io::ErrorKind::AlreadyExists,
            "unable to allocate runtime.codex receipt staging path",
        ))
    })?;
    std::fs::rename(&staging, path)?;
    sync_directory(parent)
}

fn sync_directory(path: &Path) -> Result<(), AgentdError> {
    File::open(path)?.sync_all()?;
    Ok(())
}

fn bounded_text(value: &str, maximum_chars: usize) -> String {
    value.chars().take(maximum_chars).collect()
}

#[cfg(test)]
#[path = "runtime_codex_executor_tests.rs"]
mod tests;
