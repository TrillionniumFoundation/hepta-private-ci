//! Backend-neutral, shadow-only typed boundaries for the native Agent migration.
//!
//! These types deliberately carry references/digests, not prompts, credentials,
//! authority tokens or inferred tool success. No implementation in this crate
//! contacts a model, runs a tool, or persists an effect. The independent host
//! must revalidate FinalUse, policy, generation and effect identity at physical
//! entry, and durably write its dispatch before invoking any backend.

use std::future::Future;
use std::pin::Pin;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{
    Currentness, ExecutionBinding, ExecutionError, ExecutionJournal, ExecutionStarted,
    ExecutionVerifier, FinalUse,
};

/// Object-safe transport for Codex, native inference and future providers.
pub type PortFuture<'a, T> = Pin<Box<dyn Future<Output = Result<T, PortError>> + Send + 'a>>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PortError {
    Invalid(&'static str),
    Denied,
    Cancelled,
    Unavailable,
    Indeterminate,
    Execution(ExecutionError),
}

impl From<ExecutionError> for PortError {
    fn from(value: ExecutionError) -> Self {
        Self::Execution(value)
    }
}

fn valid_digest(digest: &str) -> bool {
    digest.len() == 64
        && digest.bytes().any(|byte| byte != b'0')
        && digest
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn check_digest(value: &str) -> Result<(), PortError> {
    if valid_digest(value) {
        Ok(())
    } else {
        Err(PortError::Invalid("digest"))
    }
}

fn envelope_digest<T: Serialize>(domain: &'static [u8], value: &T) -> Result<String, PortError> {
    let bytes = serde_json::to_vec(value).map_err(|_| PortError::Invalid("serialization"))?;
    let mut hasher = Sha256::new();
    hasher.update(domain);
    hasher.update(bytes);
    Ok(format!("{:x}", hasher.finalize()))
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelInvocationV1 {
    pub binding: ExecutionBinding,
    pub model_artifact_digest: String,
    pub input_digest: String,
    pub max_input_tokens: u32,
    pub max_output_tokens: u32,
    pub deadline_unix_ms: u64,
}

impl ModelInvocationV1 {
    pub fn validate(&self) -> Result<(), PortError> {
        self.binding.validate()?;
        if self.binding.currentness != Currentness::Current {
            return Err(PortError::Invalid("model generation not current"));
        }
        check_digest(&self.model_artifact_digest)?;
        check_digest(&self.input_digest)?;
        if !(1..=1_048_576).contains(&self.max_input_tokens)
            || !(1..=1_048_576).contains(&self.max_output_tokens)
            || self.deadline_unix_ms == 0
        {
            return Err(PortError::Invalid("model resource envelope"));
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<String, PortError> {
        self.validate()?;
        envelope_digest(b"hepta.model-invocation.v1\0", self)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PortTerminal {
    Succeeded,
    Failed,
    Rejected,
    Cancelled,
    Indeterminate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelObservationV1 {
    pub request_digest: String,
    pub model_artifact_digest: String,
    pub status: PortTerminal,
    pub output_digest: Option<String>,
    pub input_tokens: u32,
    pub output_tokens: u32,
    pub provider_receipt_digest: Option<String>,
}

impl ModelObservationV1 {
    /// Syntax and correlation only. The independent provider observer owns truth.
    pub fn validate_against(&self, request: &ModelInvocationV1) -> Result<(), PortError> {
        if self.request_digest != request.digest()?
            || self.model_artifact_digest != request.model_artifact_digest
            || self.input_tokens > request.max_input_tokens
            || self.output_tokens > request.max_output_tokens
        {
            return Err(PortError::Invalid("model observation binding"));
        }
        if let Some(value) = &self.output_digest {
            check_digest(value)?;
        }
        if let Some(value) = &self.provider_receipt_digest {
            check_digest(value)?;
        }
        if self.status == PortTerminal::Succeeded
            && (self.output_digest.is_none() || self.provider_receipt_digest.is_none())
        {
            return Err(PortError::Invalid("unobserved model success"));
        }
        Ok(())
    }
}

/// The model admission verifier is an independent owner-side authority.
/// It must check a real, current, signed, operation- and payload-bound FinalUse,
/// issuer revocation frontier, resource grant, deadlines, generation and cancellation.
/// A model backend must independently recheck immediately before physical turn/start.
pub trait ModelStartVerifier: Send + Sync {
    fn verify_model_start(&self, request: &ModelInvocationV1) -> Result<(), PortError>;
}

/// A non-serializable model-start handle. Unlike a raw model request this
/// requires a verified FinalUse claim and an independent verifier invocation.
/// The handle alone is neither a physical token nor a durable dispatch receipt.
#[derive(Debug)]
pub struct CheckedModelInvocationV1 {
    request: ModelInvocationV1,
    request_digest: String,
}

impl CheckedModelInvocationV1 {
    pub fn admit(
        request: ModelInvocationV1,
        verifier: &impl ModelStartVerifier,
    ) -> Result<Self, PortError> {
        let request_digest = request.digest()?;
        if !matches!(request.binding.final_use, FinalUse::Verified { .. }) {
            return Err(PortError::Denied);
        }
        verifier.verify_model_start(&request)?;
        Ok(Self {
            request,
            request_digest,
        })
    }

    pub fn request(&self) -> &ModelInvocationV1 {
        &self.request
    }

    pub fn request_digest(&self) -> &str {
        &self.request_digest
    }
}

/// The physical ModelPort accepts only a checked, non-serializable handle.
/// Provider dispatch still requires a durable owner WAL and a final-use recheck.
pub trait ModelPort: Send + Sync {
    fn infer<'a>(&'a self, checked: &'a CheckedModelInvocationV1)
        -> PortFuture<'a, ModelObservationV1>;
}

/// In-memory verifier-invocation evidence, not an authority token or durable WAL.
/// Its private fields prevent callers from constructing a dispatch through JSON.
#[derive(Debug)]
pub struct CheckedStartHandleV1 {
    binding: ExecutionBinding,
    start_record_digest: String,
}

impl CheckedStartHandleV1 {
    pub fn binding(&self) -> &ExecutionBinding {
        &self.binding
    }

    pub fn start_record_digest(&self) -> &str {
        &self.start_record_digest
    }

    /// The verifier MUST be independent and verify the real signed, current,
    /// exact-payload FinalUse before returning Ok. The execution owner must
    /// durably commit this result and revalidate at physical effect entry.
    pub fn admit(
        journal: &mut ExecutionJournal,
        started: ExecutionStarted,
        verifier: &impl ExecutionVerifier,
    ) -> Result<Self, ExecutionError> {
        let binding = started.binding.clone();
        let start_record_digest = journal.append_started(started, verifier)?;
        Ok(Self {
            binding,
            start_record_digest,
        })
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionObservationV1 {
    pub operation_id: String,
    pub start_record_digest: String,
    pub status: PortTerminal,
    pub terminal_observation_digest: Option<String>,
}

impl ExecutionObservationV1 {
    /// A success claim alone cannot replace EffectReceiptVerifier or reconciliation.
    pub fn validate_against(&self, checked: &CheckedStartHandleV1) -> Result<(), PortError> {
        if self.operation_id != checked.binding.operation_id
            || self.start_record_digest != checked.start_record_digest
        {
            return Err(PortError::Invalid("execution observation binding"));
        }
        check_digest(&self.start_record_digest)?;
        if let Some(digest) = &self.terminal_observation_digest {
            check_digest(digest)?;
        }
        if self.status == PortTerminal::Succeeded && self.terminal_observation_digest.is_none() {
            return Err(PortError::Invalid("unobserved execution success"));
        }
        Ok(())
    }
}

/// Effect-owner implementation MUST durably admit, enforce independent FinalUse
/// at physical entry, and reconcile unknown effects without blind replay.
pub trait ExecutionPort: Send + Sync {
    fn dispatch<'a>(
        &'a self,
        checked: &'a CheckedStartHandleV1,
    ) -> PortFuture<'a, ExecutionObservationV1>;

    fn cancel<'a>(
        &'a self,
        binding: &'a ExecutionBinding,
    ) -> PortFuture<'a, ExecutionObservationV1>;

    fn reconcile<'a>(
        &'a self,
        binding: &'a ExecutionBinding,
    ) -> PortFuture<'a, ExecutionObservationV1>;
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentStepRequestV1 {
    pub binding: ExecutionBinding,
    pub step: u32,
    pub max_steps: u32,
    pub state_digest: String,
    pub deadline_unix_ms: u64,
}

impl AgentStepRequestV1 {
    pub fn digest(&self) -> Result<String, PortError> {
        self.binding.validate()?;
        check_digest(&self.state_digest)?;
        if self.binding.currentness != Currentness::Current
            || self.step >= self.max_steps
            || !(1..=1024).contains(&self.max_steps)
            || self.deadline_unix_ms == 0
        {
            return Err(PortError::Invalid("agent step envelope"));
        }
        envelope_digest(b"hepta.agent-step.v1\0", self)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentStepDisposition {
    InvokeModel,
    ProposeTool,
    Waiting,
    Completed,
    Abstained,
    Cancelled,
    Indeterminate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentStepObservationV1 {
    pub request_digest: String,
    pub disposition: AgentStepDisposition,
    pub next_state_digest: Option<String>,
    /// Hash of the proposed exact ModelInvocation or ExecutionIntent; never authority.
    pub action_digest: Option<String>,
    pub observation_digest: String,
}

impl AgentStepObservationV1 {
    pub fn validate_against(&self, request: &AgentStepRequestV1) -> Result<(), PortError> {
        if self.request_digest != request.digest()? {
            return Err(PortError::Invalid("agent step identity"));
        }
        check_digest(&self.observation_digest)?;
        if let Some(value) = &self.next_state_digest {
            check_digest(value)?;
        }
        if let Some(value) = &self.action_digest {
            check_digest(value)?;
        }
        let has_action = matches!(
            self.disposition,
            AgentStepDisposition::InvokeModel | AgentStepDisposition::ProposeTool
        );
        if has_action != self.action_digest.is_some() {
            return Err(PortError::Invalid("unbound model or tool proposal"));
        }
        let continues = matches!(
            self.disposition,
            AgentStepDisposition::InvokeModel
                | AgentStepDisposition::ProposeTool
                | AgentStepDisposition::Waiting
        );
        if continues != self.next_state_digest.is_some()
            || (continues && request.step + 1 >= request.max_steps)
        {
            return Err(PortError::Invalid("agent step termination or budget"));
        }
        Ok(())
    }
}

/// Agentd owns the durable loop cursor; this protocol does NOT implement a loop
/// or permit a model's proposed tool action to bypass the execution owner.
pub trait AgentLoopPort: Send + Sync {
    fn step<'a>(
        &'a self,
        request: &'a AgentStepRequestV1,
    ) -> PortFuture<'a, AgentStepObservationV1>;
}
