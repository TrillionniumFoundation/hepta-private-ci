//! Owner-local, authority-free TaskFlow execution-boundary assessment.
//!
//! This is a bounded structural calculator, not a registered wire contract,
//! capability verifier, approval record, complete task-graph view, durable
//! receipt, dispatcher, or terminal observer. Every input is caller supplied.
//! A content digest only binds those local bytes; it never authenticates their
//! owner or upgrades them to `OperationIntentV1`, `VerifiedUseTokenWitnessV1`,
//! or `ActuatorReconciliationReceiptV1`.
//!
//! The automation owner is not a registered consumer/verifier for the required
//! final-use capability, and the terminal observer belongs to another owner.
//! Consequently the output type can represent only `Unavailable`, always has
//! [`TaskFlowBoundaryAuthority::DENY_ALL`], and exposes no dispatch or state
//! mutation. A positive path remains residual on cross-owner protocol admission,
//! an owner-authenticated adapter, and a current-fence terminal observer.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

/// Exact local input version accepted by this calculator.
pub const TASKFLOW_EXECUTION_BOUNDARY_SCHEMA_VERSION: u32 = 1;
/// One assessed step plus these predecessor references fits the 128-step cap.
pub const MAX_TASKFLOW_BOUNDARY_PREDECESSORS: usize = 127;
/// Maximum encoded local request accepted before JSON parsing.
pub const MAX_TASKFLOW_BOUNDARY_ENCODED_BYTES: usize = 64 * 1024;

const MAX_STABLE_ID_BYTES: usize = 128;
const MAX_ATTEMPT: u32 = 1_000_000;
const MAX_RUN_REVISION: u64 = 9_223_372_036_854_775_807;
const ZERO_DIGEST: &str =
    "0000000000000000000000000000000000000000000000000000000000000000";
const REQUEST_DIGEST_DOMAIN: &[u8] =
    b"hepta.automation.taskflow.local-execution-boundary.request.v1\0";
const ASSESSMENT_DIGEST_DOMAIN: &[u8] =
    b"hepta.automation.taskflow.local-execution-boundary.unavailable.v1\0";

/// Caller-supplied predecessor reference. Presence is not proof that the list
/// is complete, fresh, owner-authenticated, or causally satisfied.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalTaskFlowPredecessorReferenceV1 {
    pub step_id: String,
    pub state_digest: Sha256Digest,
}

/// Requested terminal state, represented only as caller intent.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalTaskFlowTerminalStateV1 {
    Succeeded,
    Failed,
    Cancelled,
}

/// The boundary the caller asks this local calculator to assess.
///
/// Reference digests are untrusted checksums. In particular, no field can
/// carry an approval, final-use capability, terminal observation, or a claim
/// that the supplied graph is complete.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum LocalTaskFlowBoundaryActionV1 {
    ExternalEffect {
        operation_intent_reference_digest: Sha256Digest,
        final_payload_digest: Sha256Digest,
        destination_digest: Sha256Digest,
        idempotency_key_digest: Sha256Digest,
    },
    TerminalState {
        proposed_state: LocalTaskFlowTerminalStateV1,
        result_digest: Sha256Digest,
    },
}

/// Exact, untrusted input to the local structural boundary.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalTaskFlowBoundaryRequestV1 {
    pub schema_version: u32,
    pub owner_agent_id: AgentId,
    pub workflow_id: String,
    pub workflow_version: u32,
    pub definition_digest: Sha256Digest,
    pub run_id: String,
    pub run_revision: u64,
    pub run_state_digest: Sha256Digest,
    pub step_id: String,
    pub attempt: u32,
    pub predecessor_references: Vec<LocalTaskFlowPredecessorReferenceV1>,
    pub action: LocalTaskFlowBoundaryActionV1,
}

/// Scope disclosure carried by every assessment.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TaskFlowBoundaryScope {
    /// Only one step and the caller's supplied predecessor references were read.
    SuppliedStepAndPredecessorsOnly,
}

/// The unavailable owner boundary selected by the requested action.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TaskFlowBoundaryUnavailableReason {
    /// Dispatch requires a registered effect owner and final-use verifier.
    RegisteredEffectOwnerUnavailable,
    /// Terminal state requires a trusted, current-fence terminal observer.
    TrustedTerminalObserverUnavailable,
}

/// All-negative authority marker for this owner-local primitive. There is
/// deliberately no positive state or public data field.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TaskFlowBoundaryAuthority;

impl TaskFlowBoundaryAuthority {
    pub const DENY_ALL: Self = Self;

    #[must_use]
    pub const fn grants_any(self) -> bool {
        false
    }
}

/// Deterministic fail-closed result for a structurally valid local request.
///
/// The private representation has no `Ready`, `Authorized`, `Verified`, or
/// terminal outcome variant. It is not a receipt and cannot be promoted into
/// one by matching caller-supplied digests.
#[derive(Clone, Debug, Eq, PartialEq)]
#[must_use = "an unavailable assessment never authorizes execution"]
pub struct TaskFlowExecutionUnavailableV1 {
    request_digest: Sha256Digest,
    assessment_digest: Sha256Digest,
    reason: TaskFlowBoundaryUnavailableReason,
}

impl TaskFlowExecutionUnavailableV1 {
    #[must_use]
    pub fn request_digest(&self) -> &Sha256Digest {
        &self.request_digest
    }

    #[must_use]
    pub fn assessment_digest(&self) -> &Sha256Digest {
        &self.assessment_digest
    }

    #[must_use]
    pub const fn scope(&self) -> TaskFlowBoundaryScope {
        TaskFlowBoundaryScope::SuppliedStepAndPredecessorsOnly
    }

    #[must_use]
    pub const fn reason(&self) -> TaskFlowBoundaryUnavailableReason {
        self.reason
    }

    /// A local assessment never grants runtime, writer, dispatch, effect,
    /// selection, promotion, or release authority.
    #[must_use]
    pub const fn authority(&self) -> TaskFlowBoundaryAuthority {
        TaskFlowBoundaryAuthority::DENY_ALL
    }
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum TaskFlowBoundaryError {
    #[error("encoded TaskFlow boundary request exceeds {max_bytes} bytes")]
    EncodedSizeExceeded { max_bytes: usize },
    #[error("TaskFlow boundary request is not exact valid JSON")]
    MalformedInput,
    #[error("unsupported TaskFlow boundary schema version")]
    UnsupportedSchemaVersion,
    #[error("invalid TaskFlow boundary field: {0}")]
    InvalidField(&'static str),
    #[error("TaskFlow boundary resource limit exceeded for {field}: maximum {maximum}")]
    ResourceLimit {
        field: &'static str,
        maximum: usize,
    },
    #[error("TaskFlow predecessor references must be strictly ordered by step id")]
    NonCanonicalPredecessors,
    #[error("TaskFlow predecessor references contain the current step")]
    CurrentStepAsPredecessor,
}

/// Parse and assess one exact, bounded local JSON request.
///
/// Unknown, duplicate, or missing fields and unknown enum values fail before
/// any digest is produced. This function performs no write or external call.
pub fn assess_local_taskflow_boundary_json(
    encoded: &[u8],
) -> Result<TaskFlowExecutionUnavailableV1, TaskFlowBoundaryError> {
    if encoded.len() > MAX_TASKFLOW_BOUNDARY_ENCODED_BYTES {
        return Err(TaskFlowBoundaryError::EncodedSizeExceeded {
            max_bytes: MAX_TASKFLOW_BOUNDARY_ENCODED_BYTES,
        });
    }
    let request = serde_json::from_slice(encoded)
        .map_err(|_| TaskFlowBoundaryError::MalformedInput)?;
    assess_local_taskflow_boundary(&request)
}

/// Assess one typed request without mutation or ambient authority.
pub fn assess_local_taskflow_boundary(
    request: &LocalTaskFlowBoundaryRequestV1,
) -> Result<TaskFlowExecutionUnavailableV1, TaskFlowBoundaryError> {
    validate(request)?;
    let request_digest = digest_request(request);
    let reason = match &request.action {
        LocalTaskFlowBoundaryActionV1::ExternalEffect { .. } => {
            TaskFlowBoundaryUnavailableReason::RegisteredEffectOwnerUnavailable
        }
        LocalTaskFlowBoundaryActionV1::TerminalState { .. } => {
            TaskFlowBoundaryUnavailableReason::TrustedTerminalObserverUnavailable
        }
    };
    let assessment_digest = digest_assessment(&request_digest, reason);
    Ok(TaskFlowExecutionUnavailableV1 {
        request_digest,
        assessment_digest,
        reason,
    })
}

fn validate(request: &LocalTaskFlowBoundaryRequestV1) -> Result<(), TaskFlowBoundaryError> {
    if request.schema_version != TASKFLOW_EXECUTION_BOUNDARY_SCHEMA_VERSION {
        return Err(TaskFlowBoundaryError::UnsupportedSchemaVersion);
    }
    validate_id(&request.workflow_id, "workflow_id")?;
    validate_id(&request.run_id, "run_id")?;
    validate_id(&request.step_id, "step_id")?;
    if request.workflow_version == 0 {
        return Err(TaskFlowBoundaryError::InvalidField("workflow_version"));
    }
    if !(1..=MAX_RUN_REVISION).contains(&request.run_revision) {
        return Err(TaskFlowBoundaryError::InvalidField("run_revision"));
    }
    if !(1..=MAX_ATTEMPT).contains(&request.attempt) {
        return Err(TaskFlowBoundaryError::InvalidField("attempt"));
    }
    for (digest, field) in [
        (&request.definition_digest, "definition_digest"),
        (&request.run_state_digest, "run_state_digest"),
    ] {
        validate_digest(digest, field)?;
    }
    if request.predecessor_references.len() > MAX_TASKFLOW_BOUNDARY_PREDECESSORS {
        return Err(TaskFlowBoundaryError::ResourceLimit {
            field: "predecessor_references",
            maximum: MAX_TASKFLOW_BOUNDARY_PREDECESSORS,
        });
    }
    let mut previous_id: Option<&str> = None;
    for predecessor in &request.predecessor_references {
        validate_id(&predecessor.step_id, "predecessor.step_id")?;
        validate_digest(&predecessor.state_digest, "predecessor.state_digest")?;
        if predecessor.step_id == request.step_id {
            return Err(TaskFlowBoundaryError::CurrentStepAsPredecessor);
        }
        if previous_id.is_some_and(|previous| previous >= predecessor.step_id.as_str()) {
            return Err(TaskFlowBoundaryError::NonCanonicalPredecessors);
        }
        previous_id = Some(&predecessor.step_id);
    }
    match &request.action {
        LocalTaskFlowBoundaryActionV1::ExternalEffect {
            operation_intent_reference_digest,
            final_payload_digest,
            destination_digest,
            idempotency_key_digest,
        } => {
            for (digest, field) in [
                (
                    operation_intent_reference_digest,
                    "action.operation_intent_reference_digest",
                ),
                (final_payload_digest, "action.final_payload_digest"),
                (destination_digest, "action.destination_digest"),
                (idempotency_key_digest, "action.idempotency_key_digest"),
            ] {
                validate_digest(digest, field)?;
            }
        }
        LocalTaskFlowBoundaryActionV1::TerminalState { result_digest, .. } => {
            validate_digest(result_digest, "action.result_digest")?;
        }
    }
    Ok(())
}

fn validate_id(value: &str, field: &'static str) -> Result<(), TaskFlowBoundaryError> {
    if value.is_empty()
        || value.len() > MAX_STABLE_ID_BYTES
        || !value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-' | b':')
        })
    {
        return Err(TaskFlowBoundaryError::InvalidField(field));
    }
    Ok(())
}

fn validate_digest(
    digest: &Sha256Digest,
    field: &'static str,
) -> Result<(), TaskFlowBoundaryError> {
    let value = digest.as_str();
    if value == ZERO_DIGEST
        || value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(TaskFlowBoundaryError::InvalidField(field));
    }
    Ok(())
}

fn digest_request(request: &LocalTaskFlowBoundaryRequestV1) -> Sha256Digest {
    let mut bytes = Vec::with_capacity(/*capacity*/ 4096);
    bytes.extend_from_slice(REQUEST_DIGEST_DOMAIN);
    bytes.extend_from_slice(&request.schema_version.to_be_bytes());
    push_text(&mut bytes, request.owner_agent_id.as_str());
    push_text(&mut bytes, &request.workflow_id);
    bytes.extend_from_slice(&request.workflow_version.to_be_bytes());
    push_digest(&mut bytes, &request.definition_digest);
    push_text(&mut bytes, &request.run_id);
    bytes.extend_from_slice(&request.run_revision.to_be_bytes());
    push_digest(&mut bytes, &request.run_state_digest);
    push_text(&mut bytes, &request.step_id);
    bytes.extend_from_slice(&request.attempt.to_be_bytes());
    bytes.extend_from_slice(
        &u32::try_from(request.predecessor_references.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for predecessor in &request.predecessor_references {
        push_text(&mut bytes, &predecessor.step_id);
        push_digest(&mut bytes, &predecessor.state_digest);
    }
    match &request.action {
        LocalTaskFlowBoundaryActionV1::ExternalEffect {
            operation_intent_reference_digest,
            final_payload_digest,
            destination_digest,
            idempotency_key_digest,
        } => {
            bytes.push(/*value*/ 0);
            push_digest(&mut bytes, operation_intent_reference_digest);
            push_digest(&mut bytes, final_payload_digest);
            push_digest(&mut bytes, destination_digest);
            push_digest(&mut bytes, idempotency_key_digest);
        }
        LocalTaskFlowBoundaryActionV1::TerminalState {
            proposed_state,
            result_digest,
        } => {
            bytes.push(/*value*/ 1);
            bytes.push(match proposed_state {
                LocalTaskFlowTerminalStateV1::Succeeded => 0,
                LocalTaskFlowTerminalStateV1::Failed => 1,
                LocalTaskFlowTerminalStateV1::Cancelled => 2,
            });
            push_digest(&mut bytes, result_digest);
        }
    }
    Sha256Digest::for_bytes(&bytes)
}

fn digest_assessment(
    request_digest: &Sha256Digest,
    reason: TaskFlowBoundaryUnavailableReason,
) -> Sha256Digest {
    let mut bytes = Vec::with_capacity(ASSESSMENT_DIGEST_DOMAIN.len() + 66);
    bytes.extend_from_slice(ASSESSMENT_DIGEST_DOMAIN);
    push_digest(&mut bytes, request_digest);
    bytes.push(/*value*/ 0); // SuppliedStepAndPredecessorsOnly.
    bytes.push(match reason {
        TaskFlowBoundaryUnavailableReason::RegisteredEffectOwnerUnavailable => 0,
        TaskFlowBoundaryUnavailableReason::TrustedTerminalObserverUnavailable => 1,
    });
    bytes.push(/*value*/ 0); // TaskFlowBoundaryAuthority::DENY_ALL.
    Sha256Digest::for_bytes(&bytes)
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(
        &u32::try_from(value.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
}

fn push_digest(bytes: &mut Vec<u8>, digest: &Sha256Digest) {
    bytes.extend_from_slice(digest.as_str().as_bytes());
}
