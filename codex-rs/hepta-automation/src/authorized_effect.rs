//! Final-use-authorized TaskFlow effect dispatch.
//!
//! The automation owner never mints authority. A step must already be durably
//! claimed in the TaskFlow outbox. Immediately before the registered effect
//! driver is called, the kernel-owned [`FinalUseAuthority`] verifies an
//! independently signed, short-lived, single-use binding over the exact intent,
//! payload and destination. The driver's terminal/indeterminate observation is
//! then appended to the same durable step chain.

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use thiserror::Error;

use crate::AutomationStore;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowStepObservation;
use crate::TaskFlowStepReceipt;
use crate::TaskFlowStepState;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthorizedEffectOutcome {
    Succeeded,
    Failed,
    Indeterminate,
}

impl AuthorizedEffectOutcome {
    fn observation(self) -> TaskFlowStepObservation {
        match self {
            Self::Succeeded => TaskFlowStepObservation::Succeeded,
            Self::Failed => TaskFlowStepObservation::Failed,
            Self::Indeterminate => TaskFlowStepObservation::Indeterminate,
        }
    }
}

/// Observation produced by the registered downstream effect owner. A driver
/// must return `Indeterminate`, never an error, once external dispatch may have
/// happened. `Err` is reserved for failures proven to occur before provider
/// contact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorizedEffectProviderReceipt {
    pub outcome: AuthorizedEffectOutcome,
    pub receipt_digest: Sha256Digest,
}

pub struct AuthorizedEffectRequest<'a> {
    pub run_id: &'a str,
    pub step_id: &'a str,
    pub attempt: u32,
    pub intent_digest: &'a Sha256Digest,
    pub payload_digest: &'a Sha256Digest,
    pub binding: &'a FinalUseBinding,
}

/// Registered effect-owner adapter. This synchronous boundary is intentional:
/// `FinalUseAuthority::with_verified_use` holds the current revocation fence
/// through the final check and the actual dispatch call. Drivers must impose
/// their own bounded I/O deadline and return `Indeterminate` after ambiguous
/// provider contact.
pub trait AuthorizedEffectDriver {
    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError>;
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum AuthorizedEffectDriverError {
    #[error("effect driver rejected the request before provider contact")]
    BeforeProviderContact,
}

#[derive(Debug, Error)]
pub enum AuthorizedEffectError {
    #[error(transparent)]
    TaskFlow(#[from] TaskFlowError),
    #[error("final-use authority rejected the effect: {0}")]
    FinalUse(FinalUseError),
    #[error("final-use binding does not match the durable TaskFlow intent/payload")]
    BindingMismatch,
    #[error(transparent)]
    Driver(#[from] AuthorizedEffectDriverError),
}

impl AutomationStore {
    /// Dispatch one already-claimed durable TaskFlow step through a final-use
    /// authorized provider seam and append its observation before returning.
    ///
    /// A `Succeeded`/`Failed` receipt is terminal for the step. An
    /// `Indeterminate` receipt blocks dependent work until the owning provider
    /// reconciler appends an explicit reconciliation receipt.
    #[allow(clippy::too_many_arguments)]
    pub async fn execute_authorized_taskflow_effect<D: AuthorizedEffectDriver>(
        &self,
        authority: &FinalUseAuthority,
        driver: &mut D,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        fence: &TaskFlowFence,
        intent_digest: &Sha256Digest,
        payload_digest: &Sha256Digest,
        signed_grant: &SignedFinalUseGrant,
        expected_binding: &FinalUseBinding,
        command_id: &str,
        now_ms: u64,
    ) -> Result<TaskFlowStepReceipt, AuthorizedEffectError> {
        let current = self
            .read_taskflow_step(run_id, step_id, attempt, fence)
            .await?
            .ok_or_else(|| {
                TaskFlowError::Conflict(
                    "authorized effect requires a prepared and claimed durable step".to_string(),
                )
            })?;
        if current.state != TaskFlowStepState::Claimed
            || current.intent_digest != *intent_digest
            || current.payload_digest != *payload_digest
        {
            return Err(TaskFlowError::Conflict(
                "authorized effect does not match the claimed durable step".to_string(),
            )
            .into());
        }
        if expected_binding.request_sha256 != digest_bytes(intent_digest)?
            || expected_binding.payload_sha256 != digest_bytes(payload_digest)?
        {
            return Err(AuthorizedEffectError::BindingMismatch);
        }

        // `claim` durably burns the grant nonce. If the driver returns a
        // pre-contact error, a retry needs a new signed grant. If contact was
        // ambiguous, the driver contract requires an Indeterminate receipt so
        // this method can durably quarantine the step.
        let token = authority
            .claim(signed_grant, expected_binding)
            .map_err(AuthorizedEffectError::FinalUse)?;
        let request = AuthorizedEffectRequest {
            run_id,
            step_id,
            attempt,
            intent_digest,
            payload_digest,
            binding: expected_binding,
        };
        let provider = authority
            .with_verified_use(token, expected_binding, || driver.dispatch(&request))
            .map_err(AuthorizedEffectError::FinalUse)??;
        validate_receipt_digest(&provider.receipt_digest)?;
        let recorded = self
            .record_taskflow_step(
                run_id,
                step_id,
                attempt,
                fence,
                intent_digest,
                payload_digest,
                command_id,
                &provider.receipt_digest,
                provider.outcome.observation(),
                now_ms,
            )
            .await?;
        Ok(recorded.receipt)
    }
}

fn digest_bytes(digest: &Sha256Digest) -> Result<[u8; 32], AuthorizedEffectError> {
    let value = digest.as_str().as_bytes();
    if value.len() != 64 {
        return Err(AuthorizedEffectError::BindingMismatch);
    }
    let mut output = [0_u8; 32];
    for (index, pair) in value.chunks_exact(2).enumerate() {
        output[index] = (hex(pair[0])? << 4) | hex(pair[1])?;
    }
    if output == [0; 32] {
        return Err(AuthorizedEffectError::BindingMismatch);
    }
    Ok(output)
}

fn hex(value: u8) -> Result<u8, AuthorizedEffectError> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => Err(AuthorizedEffectError::BindingMismatch),
    }
}

fn validate_receipt_digest(digest: &Sha256Digest) -> Result<(), AuthorizedEffectError> {
    let value = digest.as_str();
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(TaskFlowError::Invalid("invalid provider receipt digest".to_string()).into());
    }
    Ok(())
}
