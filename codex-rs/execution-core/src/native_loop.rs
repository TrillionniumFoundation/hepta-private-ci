//! Deterministic, non-authorizing native Agent loop checkpoint transitions.
//!
//! This module is deliberately **not** a tool driver or durable writer. It cannot
//! construct a FinalUse grant, open a model session or execute a process.
//! Agentd must persist the returned checkpoint with revision CAS before another
//! step is admitted. External outcomes require an independent observer, never a
//! model-authored "succeeded" string. Unknown effects stay quarantined.

use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::ports::{
    AgentStepDisposition, AgentStepObservationV1, AgentStepRequestV1, PortError, PortTerminal,
};
use crate::{Currentness, ExecutionBinding};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeExternalKindV1 {
    Model,
    Tool,
    Wake,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "phase", rename_all = "snake_case")]
pub enum NativeLoopPhaseV1 {
    Ready,
    AwaitingExternal {
        kind: NativeExternalKindV1,
        action_digest: Option<String>,
        step_observation_digest: String,
        continuation_digest: String,
    },
    CompletionCandidate {
        step_observation_digest: String,
    },
    Completed {
        independent_receipt_digest: String,
    },
    Abstained,
    Cancelled,
    Quarantined {
        reason_digest: String,
    },
}

/// A model-provided response is not independent effect evidence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeExternalObservationV1 {
    pub operation_id: String,
    pub generation: u64,
    pub kind: NativeExternalKindV1,
    pub action_digest: Option<String>,
    pub step_observation_digest: String,
    pub status: PortTerminal,
    pub observation_digest: String,
}

/// The implementation must consult the real provider/host outcome and current
/// generation. It must not approve its own proposed action or accept a replayed
/// serialized signature as authority. The effect owner remains responsible for
/// FinalUse, durable dispatch, receipt attestation and unknown-effect recovery.
pub trait NativeLoopObserver: Send + Sync {
    fn verify_external(
        &self,
        cursor: &NativeLoopCursorV1,
        observation: &NativeExternalObservationV1,
    ) -> Result<(), PortError>;

    fn verify_completion(
        &self,
        cursor: &NativeLoopCursorV1,
        independent_receipt_digest: &str,
    ) -> Result<(), PortError>;
}

/// Pure next-checkpoint proposal. Only the run owner can store or promote it.
/// Private fields prevent ordinary callers from rewriting a phase to "completed".
/// Deserialization is intentionally absent: a JSON snapshot has no authority.
#[must_use]
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NativeLoopCursorV1 {
    binding: ExecutionBinding,
    next_step: u32,
    max_steps: u32,
    state_digest: String,
    deadline_unix_ms: u64,
    phase: NativeLoopPhaseV1,
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && value.bytes().any(|byte| byte != b'0')
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

// Variable-length run and operation identities must use an unambiguous
// encoding. Concatenation aliases (run="a", operation="bc") with
// (run="ab", operation="c") and can reuse a state digest across runs.
fn hash_text_field(hasher: &mut Sha256, text: &str) {
    hasher.update((text.len() as u64).to_le_bytes());
    hasher.update(text.as_bytes());
}

fn hash_transition(
    cursor: &NativeLoopCursorV1,
    next: &str,
    observed: &NativeExternalObservationV1,
) -> String {
    let mut hasher = Sha256::new();
    // V2 binds all observed causal data and frames variable-length fields.
    // No deployed V1 transition has been qualified or promoted.
    hasher.update(b"hepta.native-loop.external-v2\0");
    hash_text_field(&mut hasher, &cursor.binding.run_id);
    hash_text_field(&mut hasher, &cursor.binding.operation_id);
    hasher.update(cursor.binding.generation.to_le_bytes());
    hasher.update(cursor.next_step.to_le_bytes());
    hash_text_field(&mut hasher, &cursor.state_digest);
    hash_text_field(&mut hasher, next);
    let kind = match observed.kind {
        NativeExternalKindV1::Model => "model",
        NativeExternalKindV1::Tool => "tool",
        NativeExternalKindV1::Wake => "wake",
    };
    hash_text_field(&mut hasher, kind);
    if let Some(action) = &observed.action_digest {
        hasher.update([1]);
        hash_text_field(&mut hasher, action);
    } else {
        hasher.update([0]);
    }
    hash_text_field(&mut hasher, &observed.step_observation_digest);
    hash_text_field(&mut hasher, &observed.observation_digest);
    format!("{:x}", hasher.finalize())
}

impl NativeLoopCursorV1 {
    pub fn begin(
        binding: ExecutionBinding,
        state_digest: String,
        max_steps: u32,
        deadline_unix_ms: u64,
    ) -> Result<Self, PortError> {
        if binding.currentness != Currentness::Current || !valid_digest(&state_digest) {
            return Err(PortError::Invalid("native run identity"));
        }
        AgentStepRequestV1 {
            binding: binding.clone(),
            step: 0,
            max_steps,
            state_digest: state_digest.clone(),
            deadline_unix_ms,
        }
        .digest()?;
        Ok(Self {
            binding,
            next_step: 0,
            max_steps,
            state_digest,
            deadline_unix_ms,
            phase: NativeLoopPhaseV1::Ready,
        })
    }

    pub fn phase(&self) -> &NativeLoopPhaseV1 {
        &self.phase
    }

    pub fn next_step(&self) -> u32 {
        self.next_step
    }

    pub fn state_digest(&self) -> &str {
        &self.state_digest
    }

    pub fn checkpoint_digest(&self) -> Result<String, PortError> {
        let bytes = serde_json::to_vec(self)
            .map_err(|_| PortError::Invalid("checkpoint encoding"))?;
        let mut hasher = Sha256::new();
        hasher.update(b"hepta.native-loop.checkpoint-v1\0");
        hasher.update(bytes);
        Ok(format!("{:x}", hasher.finalize()))
    }

    pub fn next_request(&self, now_unix_ms: u64) -> Result<AgentStepRequestV1, PortError> {
        if !matches!(&self.phase, NativeLoopPhaseV1::Ready) {
            return Err(PortError::Invalid("loop has outstanding step or terminal state"));
        }
        if now_unix_ms >= self.deadline_unix_ms {
            return Err(PortError::Cancelled);
        }
        let request = AgentStepRequestV1 {
            binding: self.binding.clone(),
            step: self.next_step,
            max_steps: self.max_steps,
            state_digest: self.state_digest.clone(),
            deadline_unix_ms: self.deadline_unix_ms,
        };
        request.digest()?;
        Ok(request)
    }

    /// Propose a checkpoint after one AgentLoopPort response. Model or tool
    /// proposals block; they never trigger a physical effect in this crate.
    pub fn accept_step(
        &self,
        observed: &AgentStepObservationV1,
        now_unix_ms: u64,
    ) -> Result<Self, PortError> {
        let request = self.next_request(now_unix_ms)?;
        observed.validate_against(&request)?;
        let mut next = self.clone();
        next.phase = match observed.disposition {
            AgentStepDisposition::InvokeModel
            | AgentStepDisposition::ProposeTool
            | AgentStepDisposition::Waiting => {
                let kind = match observed.disposition {
                    AgentStepDisposition::InvokeModel => NativeExternalKindV1::Model,
                    AgentStepDisposition::ProposeTool => NativeExternalKindV1::Tool,
                    AgentStepDisposition::Waiting => NativeExternalKindV1::Wake,
                    _ => unreachable!("checked continuations"),
                };
                NativeLoopPhaseV1::AwaitingExternal {
                    kind,
                    action_digest: observed.action_digest.clone(),
                    step_observation_digest: observed.observation_digest.clone(),
                    continuation_digest: observed
                        .next_state_digest
                        .clone()
                        .ok_or(PortError::Invalid("missing continuation"))?,
                }
            }
            AgentStepDisposition::Completed => NativeLoopPhaseV1::CompletionCandidate {
                step_observation_digest: observed.observation_digest.clone(),
            },
            AgentStepDisposition::Abstained => NativeLoopPhaseV1::Abstained,
            AgentStepDisposition::Cancelled => NativeLoopPhaseV1::Cancelled,
            AgentStepDisposition::Indeterminate => NativeLoopPhaseV1::Quarantined {
                reason_digest: observed.observation_digest.clone(),
            },
        };
        Ok(next)
    }

    /// Incorporate exactly one independently verified external outcome. An
    /// indeterminate/failed/cancelled effect cannot unlock a new tool dispatch.
    /// No journal I/O occurs here: Agentd must CAS-persist the returned value.
    pub fn accept_external(
        &self,
        observed: &NativeExternalObservationV1,
        verifier: &dyn NativeLoopObserver,
        now_unix_ms: u64,
    ) -> Result<Self, PortError> {
        let NativeLoopPhaseV1::AwaitingExternal {
            kind,
            action_digest,
            step_observation_digest,
            continuation_digest,
        } = &self.phase
        else {
            return Err(PortError::Invalid("no outstanding external action"));
        };
        if now_unix_ms >= self.deadline_unix_ms {
            return Err(PortError::Cancelled);
        }
        if observed.operation_id != self.binding.operation_id
            || observed.generation != self.binding.generation
            || observed.kind != *kind
            || observed.action_digest != *action_digest
            || observed.step_observation_digest != *step_observation_digest
            || !valid_digest(&observed.observation_digest)
        {
            return Err(PortError::Invalid("external receipt correlation"));
        }
        verifier.verify_external(self, observed)?;
        let mut next = self.clone();
        if observed.status == PortTerminal::Succeeded {
            next.state_digest =
                hash_transition(self, continuation_digest, observed);
            next.next_step = self
                .next_step
                .checked_add(1)
                .ok_or(PortError::Invalid("loop counter overflow"))?;
            next.phase = NativeLoopPhaseV1::Ready;
        } else {
            next.phase = NativeLoopPhaseV1::Quarantined {
                reason_digest: observed.observation_digest.clone(),
            };
        }
        Ok(next)
    }

    /// Completion proposed by an Agent step is not task success until the
    /// independent observer attests the actual outcome.
    pub fn accept_completion(
        &self,
        independent_receipt_digest: &str,
        verifier: &dyn NativeLoopObserver,
        now_unix_ms: u64,
    ) -> Result<Self, PortError> {
        // The task deadline is a completion boundary, not just an admission
        // boundary. A delayed observer must not promote a stale candidate.
        if now_unix_ms >= self.deadline_unix_ms {
            return Err(PortError::Cancelled);
        }
        if !matches!(&self.phase, NativeLoopPhaseV1::CompletionCandidate { .. })
            || !valid_digest(independent_receipt_digest)
        {
            return Err(PortError::Invalid("unverified completion candidate"));
        }
        verifier.verify_completion(self, independent_receipt_digest)?;
        let mut next = self.clone();
        next.phase = NativeLoopPhaseV1::Completed {
            independent_receipt_digest: independent_receipt_digest.to_string(),
        };
        Ok(next)
    }

    /// A cancellation while an external effect is unsettled must quarantine
    /// instead of assuming cancellation proves that no effect happened.
    pub fn request_cancel(&self) -> Self {
        let mut next = self.clone();
        next.phase = match &self.phase {
            NativeLoopPhaseV1::Ready | NativeLoopPhaseV1::CompletionCandidate { .. } => {
                // An unverified completion proposal is still cancellable.
                NativeLoopPhaseV1::Cancelled
            }
            NativeLoopPhaseV1::AwaitingExternal {
                step_observation_digest,
                ..
            } => NativeLoopPhaseV1::Quarantined {
                reason_digest: step_observation_digest.clone(),
            },
            _ => self.phase.clone(),
        };
        next
    }
}

#[cfg(test)]
#[path = "native_loop_tests.rs"]
mod tests;
