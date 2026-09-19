//! Final-use authority seam for durable TaskFlow steps.
//!
//! This module never issues grants and has no permissive/default authority.
//! It derives the exact binding from a claimed durable step and delegates
//! nonce/signature/revocation enforcement to kernel.authority's
//! FinalUseAuthority. A caller cannot turn queue admission into effect
//! authority by constructing metadata locally.

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;

use crate::AutomationStore;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowStepState;

const FINAL_USE_REQUEST_DOMAIN: &[u8] = b"hepta.automation.taskflow.final-use.v1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TaskFlowFinalUseBindingReceipt {
    pub run_id: String,
    pub step_id: String,
    pub attempt: u32,
    pub intent_digest: Sha256Digest,
    pub payload_digest: Sha256Digest,
    pub binding: FinalUseBinding,
}

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum TaskFlowFinalUseError {
    #[error("TaskFlow final-use step is not currently claimable: {0}")]
    TaskFlow(String),
    #[error("TaskFlow final-use subject/destination is invalid")]
    InvalidIdentity,
    #[error("TaskFlow final-use digest is invalid")]
    InvalidDigest,
    #[error("final-use authority rejected the grant: {0}")]
    Authority(FinalUseError),
}

impl From<TaskFlowError> for TaskFlowFinalUseError {
    fn from(error: TaskFlowError) -> Self {
        Self::TaskFlow(error.to_string())
    }
}

impl AutomationStore {
    /// Derives an effect binding only from the durable claimed step receipt.
    /// The caller supplies identity/scope owned by the destination contract;
    /// intent and final payload digests are read back from the append-only
    /// TaskFlow outbox and therefore cannot be substituted by request metadata.
    pub async fn taskflow_final_use_binding(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        fence: &TaskFlowFence,
        subject_id: &str,
        destination_id: &str,
        scope_digest: &Sha256Digest,
    ) -> Result<TaskFlowFinalUseBindingReceipt, TaskFlowFinalUseError> {
        if !final_use_identifier(subject_id) || !final_use_identifier(destination_id) {
            return Err(TaskFlowFinalUseError::InvalidIdentity);
        }
        let step = self
            .read_taskflow_step(run_id, step_id, attempt, fence)
            .await?
            .ok_or_else(|| {
                TaskFlowFinalUseError::TaskFlow(
                    "durable step receipt is missing".to_string(),
                )
            })?;
        if step.state != TaskFlowStepState::Claimed {
            return Err(TaskFlowFinalUseError::TaskFlow(
                "final-use binding requires a claimed durable step".to_string(),
            ));
        }

        let intent_bytes = digest_bytes(&step.intent_digest)?;
        let payload_bytes = digest_bytes(&step.payload_digest)?;
        let scope_bytes = digest_bytes(scope_digest)?;

        let mut request = Vec::with_capacity(512);
        request.extend_from_slice(FINAL_USE_REQUEST_DOMAIN);
        for value in [
            self.owner_agent_id().as_str(),
            run_id,
            step_id,
            subject_id,
            destination_id,
        ] {
            request.extend_from_slice(value.as_bytes());
            request.push(0);
        }
        request.extend_from_slice(&attempt.to_be_bytes());
        request.extend_from_slice(&intent_bytes);
        request.extend_from_slice(&payload_bytes);
        let request_digest = Sha256Digest::for_bytes(&request);
        let request_bytes = digest_bytes(&request_digest)?;

        Ok(TaskFlowFinalUseBindingReceipt {
            run_id: run_id.to_string(),
            step_id: step_id.to_string(),
            attempt,
            intent_digest: step.intent_digest,
            payload_digest: step.payload_digest,
            binding: FinalUseBinding {
                subject_id: subject_id.to_string(),
                destination_id: destination_id.to_string(),
                request_sha256: request_bytes,
                scope_sha256: scope_bytes,
                payload_sha256: payload_bytes,
            },
        })
    }
}

/// Consumes the real kernel.authority grant immediately before adapter entry.
/// The returned token is the existing non-cloneable/non-serializable token;
/// this module has no signing key and cannot mint a substitute.
pub fn claim_taskflow_final_use(
    authority: &FinalUseAuthority,
    signed: &SignedFinalUseGrant,
    receipt: &TaskFlowFinalUseBindingReceipt,
) -> Result<VerifiedUseToken, TaskFlowFinalUseError> {
    authority
        .claim(signed, &receipt.binding)
        .map_err(TaskFlowFinalUseError::Authority)
}

fn final_use_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
}

fn digest_bytes(digest: &Sha256Digest) -> Result<[u8; 32], TaskFlowFinalUseError> {
    let value = digest.as_str().as_bytes();
    if value.len() != 64 {
        return Err(TaskFlowFinalUseError::InvalidDigest);
    }
    let mut out = [0_u8; 32];
    for (index, byte) in out.iter_mut().enumerate() {
        let high = hex(value[index * 2]).ok_or(TaskFlowFinalUseError::InvalidDigest)?;
        let low = hex(value[index * 2 + 1]).ok_or(TaskFlowFinalUseError::InvalidDigest)?;
        *byte = (high << 4) | low;
    }
    if out == [0; 32] {
        return Err(TaskFlowFinalUseError::InvalidDigest);
    }
    Ok(out)
}

fn hex(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}
