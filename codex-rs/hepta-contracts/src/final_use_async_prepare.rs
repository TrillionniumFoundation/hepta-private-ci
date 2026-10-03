//! Bounded owner preparation under an active final-use fence.

use super::FinalUseAuthority;
use super::FinalUseBinding;
use super::FinalUseError;
use super::FinalUseGrant;
use super::VerifiedUseToken;
use crate::VerifiedUseBoundaryV1;
use crate::VerifiedUseTokenWitnessV1;
use std::future::Future;

/// Source-visible marker for the closed-world privileged caller inventory.
pub const HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_PREPARED_EFFECT: &str =
    "FinalUseAuthority::with_prepared_verified_use_async";

/// Opaque provenance for one successful preparation-entry verification.
/// This is not serializable or constructible by a caller and cannot become a
/// final-use token. Its observations are ordinary non-authorizing audit data.
pub struct VerifiedPreparationEvidence {
    grant: FinalUseGrant,
    observation: VerifiedUseTokenWitnessV1,
}

impl VerifiedPreparationEvidence {
    pub fn grant(&self) -> &FinalUseGrant {
        &self.grant
    }
    pub fn observation(&self) -> &VerifiedUseTokenWitnessV1 {
        &self.observation
    }
}

impl FinalUseAuthority {
    /// Persist bounded owner evidence/admission state before provider entry.
    /// The preparation callback must not contact the provider. Its witness
    /// records only entry into preparation, never a physical send or the
    /// later final live check. The opaque token stays local and is revalidated
    /// against current trusted time after preparation's awaits. The consumer
    /// must check its prepared lease immediately before dispatch and must not
    /// insert another asynchronous preparation gap before that boundary.
    ///
    /// Revocation commits return DispatchInProgress throughout preparation
    /// and the consumer. Error, unwind or future drop releases the fence but
    /// never restores the consumed nonce. Neither presence nor absence of
    /// preparation evidence grants resend authority.
    pub async fn with_prepared_verified_use_async<P, T, E, PF, CF>(
        &self,
        token: VerifiedUseToken,
        expected: &FinalUseBinding,
        prepare: impl FnOnce(VerifiedPreparationEvidence) -> PF,
        consumer: impl FnOnce(P) -> CF,
    ) -> Result<Result<T, E>, FinalUseError>
    where
        PF: Future<Output = Result<P, E>>,
        CF: Future<Output = Result<T, E>>,
    {
        let _boundary = HEPTA_PRIVILEGED_BOUNDARY_FINAL_USE_PREPARED_EFFECT;
        let guard = self.enter_verified_effect(&token, expected)?;
        let observation = self.validate_token_live_witness(
            &token,
            expected,
            VerifiedUseBoundaryV1::PreparationEntry,
        )?;
        let evidence = VerifiedPreparationEvidence {
            grant: token.grant.clone(),
            observation,
        };
        let prepared = match prepare(evidence).await {
            Ok(prepared) => prepared,
            Err(error) => return Ok(Err(error)),
        };
        // Persistence can outwait grant expiry even while revocation is fenced.
        let _entry = self.validate_token_live_witness(
            &token,
            expected,
            VerifiedUseBoundaryV1::DispatchEntry,
        )?;
        let result = consumer(prepared).await;
        drop(guard);
        Ok(result)
    }
}

#[cfg(all(test, unix))]
#[path = "final_use_async_prepare_tests.rs"]
mod tests;
