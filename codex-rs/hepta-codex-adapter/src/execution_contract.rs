//! Versioned execution contracts shared by every Hepta cell and execution
//! backend.
//!
//! The contracts deliberately carry no model client, runtime handle, process
//! capability, or effect authority. A cell can propose an intent; only a
//! separately configured adapter can execute it and return a receipt bound to
//! the same payload and generation.

#![allow(clippy::module_name_repetitions)]

use std::fmt;
use std::future::Future;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub const EXECUTION_CONTRACT_VERSION_V1: &str = "hepta.execution.contract.v1";

/// The execution surface requested by a cell.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExecutionIntentKindV1 {
    CodexTurn,
    RuntimeTool,
}

/// Backend observation status independent of recovery posture.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExecutionStatusV1 {
    Completed,
    Failed,
    Indeterminate,
    Rejected,
}

/// Recovery posture recorded when a receipt is not a normal terminal success.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RecoveryDispositionV1 {
    None,
    RetryBeforeAdmission,
    ReconcileSameOperation,
    Quarantine,
    RollbackToPredecessor,
}

/// Digest of the exact bytes an adapter is about to submit to its backend.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalPayloadDigestV1 {
    pub scope_id: StableId,
    pub generation: Generation,
    pub payload_kind: StableId,
    pub digest: Digest32,
}

impl FinalPayloadDigestV1 {
    pub fn validate(&self) -> Result<(), ExecutionContractError> {
        if self.digest.is_zero() {
            return Err(ExecutionContractError::ZeroDigest("final payload"));
        }
        Ok(())
    }
}

/// A generation/fence witness for a write or route handoff.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GenerationFenceWitnessV1 {
    pub scope_id: StableId,
    pub generation: Generation,
    pub predecessor_generation: Option<Generation>,
    pub old_writer_id: StableId,
    pub new_writer_id: StableId,
    pub fence_digest: Digest32,
    pub migration_digest: Digest32,
    pub old_writer_fenced: bool,
    pub route_cutover_observed: bool,
}

impl GenerationFenceWitnessV1 {
    pub fn validate(&self) -> Result<(), ExecutionContractError> {
        if self.fence_digest.is_zero() {
            return Err(ExecutionContractError::ZeroDigest("generation fence"));
        }
        if self.migration_digest.is_zero() {
            return Err(ExecutionContractError::ZeroDigest("state migration"));
        }
        if self.old_writer_id == self.new_writer_id {
            return Err(ExecutionContractError::WriterIdentityCollision);
        }
        if self.predecessor_generation == Some(self.generation) {
            return Err(ExecutionContractError::GenerationSelfPredecessor);
        }
        // A writer handoff must identify exactly which preceding generation
        // was fenced. None would bypass the successor check and allow a
        // self-asserted cutover receipt without a predecessor identity.
        let Some(predecessor) = self.predecessor_generation else {
            return Err(ExecutionContractError::NonSuccessorGeneration);
        };
        if predecessor.get().checked_add(1) != Some(self.generation.get()) {
            return Err(ExecutionContractError::NonSuccessorGeneration);
        }
        if !self.old_writer_fenced || !self.route_cutover_observed {
            return Err(ExecutionContractError::FenceNotComplete);
        }
        Ok(())
    }
}

/// Codex App Server identity bound to one turn request.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexTurnBindingV1 {
    pub source_admission_digest: Digest32,
    pub session_id: StableId,
    pub thread_id: StableId,
    pub client_user_message_id: StableId,
    pub user_input_digest: Digest32,
    pub protocol_id: StableId,
    pub app_server_version: String,
    pub codex_home_digest: Digest32,
    pub connection_id: u64,
}

impl CodexTurnBindingV1 {
    pub fn validate(&self) -> Result<(), ExecutionContractError> {
        if self.protocol_id.as_str() != crate::APP_SERVER_V2_PROTOCOL_ID {
            return Err(ExecutionContractError::UnsupportedCodexProtocol);
        }
        if self.app_server_version.is_empty() {
            return Err(ExecutionContractError::EmptyText("app server version"));
        }
        if self.app_server_version.len() > crate::MAX_APP_SERVER_VERSION_BYTES
            || self
                .app_server_version
                .bytes()
                .any(|byte| byte.is_ascii_control())
        {
            return Err(ExecutionContractError::InvalidAppServerVersion);
        }
        if self.source_admission_digest.is_zero() {
            return Err(ExecutionContractError::ZeroDigest("source admission"));
        }
        if self.user_input_digest.is_zero() {
            return Err(ExecutionContractError::ZeroDigest("user input"));
        }
        if self.codex_home_digest.is_zero() {
            return Err(ExecutionContractError::ZeroDigest("codex home"));
        }
        if self.connection_id == 0 {
            return Err(ExecutionContractError::ZeroConnection);
        }
        Ok(())
    }
}

/// The common intent envelope emitted by a cell.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellExecutionIntentV1 {
    pub operation_id: StableId,
    pub cell_id: StableId,
    pub organ_id: StableId,
    pub generation: Generation,
    pub kind: ExecutionIntentKindV1,
    pub codex_binding: Option<CodexTurnBindingV1>,
    pub input_digest: Digest32,
    pub final_payload: FinalPayloadDigestV1,
    pub deadline_ms: u64,
}

impl CellExecutionIntentV1 {
    pub fn validate(&self) -> Result<(), ExecutionContractError> {
        match (self.kind, self.codex_binding.as_ref()) {
            (ExecutionIntentKindV1::CodexTurn, Some(binding)) => binding.validate()?,
            (ExecutionIntentKindV1::CodexTurn, None) => {
                return Err(ExecutionContractError::MissingCodexBinding);
            }
            (ExecutionIntentKindV1::RuntimeTool, Some(_)) => {
                return Err(ExecutionContractError::UnexpectedCodexBinding);
            }
            (ExecutionIntentKindV1::RuntimeTool, None) => {}
        }
        if self.input_digest.is_zero() {
            return Err(ExecutionContractError::ZeroDigest("cell input"));
        }
        if self.deadline_ms == 0 {
            return Err(ExecutionContractError::ExpiredDeadline);
        }
        if self.final_payload.scope_id != self.organ_id
            || self.final_payload.generation != self.generation
        {
            return Err(ExecutionContractError::PayloadScopeMismatch);
        }
        self.final_payload.validate()
    }

    #[must_use]
    pub fn intent_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(EXECUTION_CONTRACT_VERSION_V1.as_bytes());
        push_id(&mut bytes, &self.operation_id);
        push_id(&mut bytes, &self.cell_id);
        push_id(&mut bytes, &self.organ_id);
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.push(match self.kind {
            ExecutionIntentKindV1::CodexTurn => 0,
            ExecutionIntentKindV1::RuntimeTool => 1,
        });
        if let Some(binding) = &self.codex_binding {
            bytes.extend_from_slice(binding.source_admission_digest.as_array());
            push_id(&mut bytes, &binding.session_id);
            push_id(&mut bytes, &binding.thread_id);
            push_id(&mut bytes, &binding.client_user_message_id);
            bytes.extend_from_slice(binding.user_input_digest.as_array());
            push_id(&mut bytes, &binding.protocol_id);
            push_text(&mut bytes, &binding.app_server_version);
            bytes.extend_from_slice(binding.codex_home_digest.as_array());
            bytes.extend_from_slice(&binding.connection_id.to_be_bytes());
        }
        bytes.extend_from_slice(self.input_digest.as_array());
        bytes.extend_from_slice(self.final_payload.digest.as_array());
        push_id(&mut bytes, &self.final_payload.payload_kind);
        bytes.extend_from_slice(&self.deadline_ms.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

/// Runtime-specific tool intent. The adapter can send this in-process or over
/// MCP/SSH, but the contract is identical at both boundaries.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeToolIntentV1 {
    pub cell: CellExecutionIntentV1,
    pub tool_id: StableId,
    pub arguments_digest: Digest32,
    pub idempotency_key: StableId,
    pub host_scope: StableId,
}

impl RuntimeToolIntentV1 {
    pub fn validate(&self) -> Result<(), ExecutionContractError> {
        if self.cell.kind != ExecutionIntentKindV1::RuntimeTool {
            return Err(ExecutionContractError::WrongIntentKind);
        }
        self.cell.validate()?;
        if self.arguments_digest.is_zero() {
            return Err(ExecutionContractError::ZeroDigest("tool arguments"));
        }
        Ok(())
    }

    /// Binds the entire native tool operation, not only its Cell envelope.
    /// A receipt for the same Cell with a different tool, arguments, host or
    /// idempotency key cannot be reused as the proof of this operation.
    #[must_use]
    pub fn intent_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.runtime.tool.intent.v1");
        bytes.extend_from_slice(self.cell.intent_digest().as_array());
        push_id(&mut bytes, &self.tool_id);
        bytes.extend_from_slice(self.arguments_digest.as_array());
        push_id(&mut bytes, &self.idempotency_key);
        push_id(&mut bytes, &self.host_scope);
        Digest32::of_bytes(&bytes)
    }
}

/// Observed terminal or indeterminate tool result.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ToolOutcomeV1 {
    pub terminal_observed: bool,
    pub exit_code: Option<i32>,
    pub stdout_digest: Option<Digest32>,
    pub stderr_digest: Option<Digest32>,
    pub retryable: bool,
}

impl ToolOutcomeV1 {
    pub fn validate(&self) -> Result<(), ExecutionContractError> {
        if self.terminal_observed && self.stdout_digest.is_none() && self.stderr_digest.is_none() {
            return Err(ExecutionContractError::MissingTerminalOutcome);
        }
        // An exit status is a terminal process observation. Accepting it with
        // terminal_observed=false would turn conflicting evidence into a
        // digest-valid indeterminate outcome.
        if !self.terminal_observed && self.exit_code.is_some() {
            return Err(ExecutionContractError::StatusOutcomeMismatch);
        }
        if self.stdout_digest.is_some_and(Digest32::is_zero)
            || self.stderr_digest.is_some_and(Digest32::is_zero)
        {
            return Err(ExecutionContractError::ZeroDigest("tool output"));
        }
        Ok(())
    }

    #[must_use]
    pub fn outcome_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.tool.outcome.v1");
        bytes.push(self.terminal_observed as u8);
        match self.exit_code {
            Some(value) => {
                bytes.push(1);
                bytes.extend_from_slice(&value.to_be_bytes());
            }
            None => bytes.push(0),
        }
        push_optional_digest(&mut bytes, self.stdout_digest);
        push_optional_digest(&mut bytes, self.stderr_digest);
        bytes.push(self.retryable as u8);
        Digest32::of_bytes(&bytes)
    }
}

/// Receipt returned by any execution adapter.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionReceiptV1 {
    pub operation_id: StableId,
    pub intent_digest: Digest32,
    pub generation: Generation,
    pub final_payload_digest: FinalPayloadDigestV1,
    pub outcome_digest: Option<Digest32>,
    pub status: ExecutionStatusV1,
    pub recovery: RecoveryDispositionV1,
    pub authority: AuthorityPosture,
}

impl ExecutionReceiptV1 {
    pub fn validate_against(
        &self,
        intent: &CellExecutionIntentV1,
    ) -> Result<(), ExecutionContractError> {
        intent.validate()?;
        if self.operation_id != intent.operation_id
            || self.intent_digest != intent.intent_digest()
            || self.generation != intent.generation
            || self.final_payload_digest != intent.final_payload
        {
            return Err(ExecutionContractError::ReceiptBindingMismatch);
        }
        if self.final_payload_digest.validate().is_err() {
            return Err(ExecutionContractError::ReceiptBindingMismatch);
        }
        if self.outcome_digest.is_some_and(Digest32::is_zero) {
            return Err(ExecutionContractError::ZeroDigest("execution outcome"));
        }
        if matches!(
            self.status,
            ExecutionStatusV1::Completed | ExecutionStatusV1::Failed
        ) && self.outcome_digest.is_none()
        {
            return Err(ExecutionContractError::MissingTerminalOutcome);
        }
        // Exhaustively classify every status/recovery pair. In particular,
        // rejection cannot request a rollback or reconcile an effect that was
        // never admitted; an admitted failure may still require reconciliation.
        // Do not interpret a new enum variant as implicitly permitted.
        let recovery_allowed = matches!(
            (self.status, self.recovery),
            (ExecutionStatusV1::Completed, RecoveryDispositionV1::None)
                | (ExecutionStatusV1::Failed, RecoveryDispositionV1::None)
                | (ExecutionStatusV1::Failed, RecoveryDispositionV1::ReconcileSameOperation)
                | (ExecutionStatusV1::Failed, RecoveryDispositionV1::Quarantine)
                | (ExecutionStatusV1::Failed, RecoveryDispositionV1::RollbackToPredecessor)
                | (
                    ExecutionStatusV1::Indeterminate,
                    RecoveryDispositionV1::ReconcileSameOperation
                )
                | (ExecutionStatusV1::Indeterminate, RecoveryDispositionV1::Quarantine)
                | (ExecutionStatusV1::Rejected, RecoveryDispositionV1::None)
                | (ExecutionStatusV1::Rejected, RecoveryDispositionV1::RetryBeforeAdmission)
                | (ExecutionStatusV1::Rejected, RecoveryDispositionV1::Quarantine)
        );
        if !recovery_allowed {
            return Err(ExecutionContractError::StatusRecoveryMismatch);
        }
        Ok(())
    }
}

/// Native execution result used by the in-process hepta-runtime fast path.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeReceiptV1 {
    pub execution: ExecutionReceiptV1,
    /// Exact binding to tool identity, arguments, idempotency key and host.
    pub runtime_intent_digest: Digest32,
    pub tool_outcome: ToolOutcomeV1,
}

impl RuntimeReceiptV1 {
    pub fn validate_against(
        &self,
        intent: &RuntimeToolIntentV1,
    ) -> Result<(), ExecutionContractError> {
        intent.validate()?;
        self.tool_outcome.validate()?;
        self.execution.validate_against(&intent.cell)?;
        if self.runtime_intent_digest != intent.intent_digest() {
            return Err(ExecutionContractError::ReceiptBindingMismatch);
        }
        if self.execution.outcome_digest != Some(self.tool_outcome.outcome_digest()) {
            return Err(ExecutionContractError::OutcomeDigestMismatch);
        }
        if matches!(
            self.execution.status,
            ExecutionStatusV1::Completed | ExecutionStatusV1::Failed
        ) && !self.tool_outcome.terminal_observed
        {
            return Err(ExecutionContractError::StatusOutcomeMismatch);
        }
        // Process-backed tools must not report success when the observed
        // process exit is nonzero. A missing exit code is valid for tools
        // without a process, and is not treated as an implicit success code.
        if self.execution.status == ExecutionStatusV1::Completed
            && self.tool_outcome.exit_code.is_some_and(|code| code != 0)
        {
            return Err(ExecutionContractError::StatusOutcomeMismatch);
        }
        // Rejection is strictly pre-admission: neither a terminal result nor
        // partial stdout/stderr may have been observed from a native tool.
        // Otherwise a side-effecting, interrupted operation could be mislabeled
        // retry-safe even with a correctly recomputed outcome digest.
        if self.execution.status == ExecutionStatusV1::Rejected
            && (self.tool_outcome.terminal_observed
                || self.tool_outcome.stdout_digest.is_some()
                || self.tool_outcome.stderr_digest.is_some())
        {
            return Err(ExecutionContractError::StatusOutcomeMismatch);
        }
        // A native retry hint and a recovery directive must agree. A tool that
        // may have been admitted cannot authorize a fresh attempt through a
        // lower-level retryable bit, even when the observed outcome digest is
        // valid. Only a pre-admission rejection with no native evidence may
        // claim RetryBeforeAdmission; all other states are non-retryable here.
        let safe_to_retry = self.execution.status == ExecutionStatusV1::Rejected
            && self.execution.recovery == RecoveryDispositionV1::RetryBeforeAdmission;
        if self.tool_outcome.retryable != safe_to_retry {
            return Err(ExecutionContractError::StatusOutcomeMismatch);
        }
        Ok(())
    }
}

/// Errors which keep a runtime adapter from manufacturing a receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeExecutionError {
    InvalidIntent(ExecutionContractError),
    InvalidReceipt(ExecutionContractError),
    Rejected,
    Indeterminate,
    Transport(String),
}

impl fmt::Display for RuntimeExecutionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for RuntimeExecutionError {}

/// Typed boundary for hepta-runtime and other native execution backends.
///
/// Implementations should validate the intent before dispatch, preserve the
/// exact payload digest, and return a receipt only after observing a terminal
/// result. The in-process implementation is the intended hot path; MCP/SSH
/// adapters can implement the same trait at a remote boundary.
pub trait NativeExecutionAdapter: Send + Sync {
    fn execute(
        &self,
        intent: RuntimeToolIntentV1,
    ) -> impl Future<Output = Result<RuntimeReceiptV1, RuntimeExecutionError>> + Send;
}

/// Admit a native tool call through the shared structural safety gate.
///
/// Unlike calling `NativeExecutionAdapter::execute` directly, this entry
/// rejects an invalid or expired intent before any backend invocation and
/// rechecks the returned receipt against the exact tool, arguments, host,
/// idempotency key, generation and payload before forwarding it to the caller.
///
/// This does not authenticate physical host evidence, grant Final-use, or
/// replace the production writer / independent observer.
pub async fn execute_native_tool_intent<A: NativeExecutionAdapter>(
    adapter: &A,
    now_ms: u64,
    intent: RuntimeToolIntentV1,
) -> Result<RuntimeReceiptV1, RuntimeExecutionError> {
    intent
        .validate()
        .map_err(RuntimeExecutionError::InvalidIntent)?;
    if now_ms >= intent.cell.deadline_ms {
        return Err(RuntimeExecutionError::InvalidIntent(
            ExecutionContractError::ExpiredDeadline,
        ));
    }

    let receipt = adapter.execute(intent.clone()).await?;
    receipt
        .validate_against(&intent)
        .map_err(RuntimeExecutionError::InvalidReceipt)?;
    Ok(receipt)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExecutionContractError {
    EmptyText(&'static str),
    ExpiredDeadline,
    ZeroDigest(&'static str),
    ZeroConnection,
    UnsupportedCodexProtocol,
    InvalidAppServerVersion,
    PayloadScopeMismatch,
    WrongIntentKind,
    MissingTerminalOutcome,
    MissingCodexBinding,
    UnexpectedCodexBinding,
    ReceiptBindingMismatch,
    OutcomeDigestMismatch,
    StatusOutcomeMismatch,
    StatusRecoveryMismatch,
    WriterIdentityCollision,
    GenerationSelfPredecessor,
    NonSuccessorGeneration,
    FenceNotComplete,
}

impl fmt::Display for ExecutionContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ExecutionContractError {}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
}

#[cfg(test)]
#[path = "execution_contract_tests.rs"]
mod tests;
