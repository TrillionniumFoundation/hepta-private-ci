use std::future::Future;
use std::pin::Pin;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::AutomationError;
use crate::AutomationProviderObservation;

pub type EffectFuture<'a, T> =
    Pin<Box<dyn Future<Output = Result<T, AutomationError>> + Send + 'a>>;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct FinalUseAuthorityRequest {
    pub operation_id: String,
    pub authority_epoch: u64,
    pub semantic_digest: Sha256Digest,
    pub payload_digest: Sha256Digest,
    pub grant_payload_digest: Sha256Digest,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FinalUseAuthorityDecision {
    Denied,
    Granted {
        operation_id: String,
        authority_epoch: u64,
        semantic_digest: Sha256Digest,
        payload_digest: Sha256Digest,
        expires_at_ms: u64,
        verifier_receipt_digest: Sha256Digest,
    },
}

pub trait FinalUseAuthorityVerifier: Send + Sync {
    fn verify(
        &self,
        request: FinalUseAuthorityRequest,
    ) -> EffectFuture<'_, FinalUseAuthorityDecision>;
}

/// A sealed result of final-use verification. There is intentionally no public
/// constructor; provider dispatch receives this only through the verifier API.
#[derive(Clone, Debug)]
pub struct VerifiedFinalUseAuthority {
    operation_id: String,
    authority_epoch: u64,
    semantic_digest: Sha256Digest,
    payload_digest: Sha256Digest,
    expires_at_ms: u64,
    verifier_receipt_digest: Sha256Digest,
}

impl VerifiedFinalUseAuthority {
    pub fn operation_id(&self) -> &str {
        &self.operation_id
    }

    pub fn authority_epoch(&self) -> u64 {
        self.authority_epoch
    }

    pub fn semantic_digest(&self) -> &Sha256Digest {
        &self.semantic_digest
    }

    pub fn payload_digest(&self) -> &Sha256Digest {
        &self.payload_digest
    }

    pub fn expires_at_ms(&self) -> u64 {
        self.expires_at_ms
    }

    pub fn verifier_receipt_digest(&self) -> &Sha256Digest {
        &self.verifier_receipt_digest
    }
}

pub async fn verify_final_use_authority<V>(
    verifier: &V,
    request: FinalUseAuthorityRequest,
    now_ms: u64,
) -> Result<VerifiedFinalUseAuthority, AutomationError>
where
    V: FinalUseAuthorityVerifier + ?Sized,
{
    if request.operation_id.is_empty()
        || request.authority_epoch == 0
        || request.deadline_ms < now_ms
        || request.payload_digest != request.grant_payload_digest
    {
        return Err(AutomationError::AccessDenied);
    }
    let expected = request.clone();
    let decision = verifier.verify(request).await?;
    let FinalUseAuthorityDecision::Granted {
        operation_id,
        authority_epoch,
        semantic_digest,
        payload_digest,
        expires_at_ms,
        verifier_receipt_digest,
    } = decision
    else {
        return Err(AutomationError::AccessDenied);
    };
    if operation_id != expected.operation_id
        || authority_epoch != expected.authority_epoch
        || semantic_digest != expected.semantic_digest
        || payload_digest != expected.payload_digest
        || expires_at_ms < now_ms
        || expires_at_ms > expected.deadline_ms
    {
        return Err(AutomationError::AccessDenied);
    }
    Ok(VerifiedFinalUseAuthority {
        operation_id,
        authority_epoch,
        semantic_digest,
        payload_digest,
        expires_at_ms,
        verifier_receipt_digest,
    })
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ProviderDispatchRequest {
    pub occurrence_id: String,
    pub run_id: String,
    pub step_id: String,
    pub attempt: u32,
    pub operation_id: String,
    pub intent_digest: Sha256Digest,
    pub payload_digest: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ProviderDispatchReceipt {
    pub receipt_digest: Sha256Digest,
    pub observation: AutomationProviderObservation,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum ProviderDispatchOutcome {
    Observed(ProviderDispatchReceipt),
    /// The provider may have accepted or completed the effect, but the caller
    /// cannot prove the terminal result. The digest binds the durable evidence
    /// used by later reconciliation; this outcome must never be blindly retried.
    Indeterminate {
        observation_digest: Sha256Digest,
    },
}

pub trait AutomationEffectProvider: Send + Sync {
    /// Error is reserved for failures proven to have happened before the
    /// provider admission seam. Anything that may have crossed that seam must
    /// return an indeterminate outcome.
    fn dispatch(
        &self,
        request: ProviderDispatchRequest,
        authority: &VerifiedFinalUseAuthority,
    ) -> EffectFuture<'_, ProviderDispatchOutcome>;
}
