//! Retain the independent current distribution floor in cloned/opaque evidence.
use super::*;
use crate::LearningTrustFrontier;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use std::sync::Arc;

#[derive(Clone)]
pub(super) struct EvidenceTrustFrontier {
    binding: Digest32,
    expected: LearningTrustFrontier,
    store: Arc<dyn AuthorityFrontierStore<LearningTrustFrontier>>,
    microsecond_clock: Option<Arc<dyn AuthorityClock>>,
}
impl fmt::Debug for EvidenceTrustFrontier {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("EvidenceTrustFrontier")
            .field("binding", &self.binding)
            .field("expected", &self.expected)
            .finish_non_exhaustive()
    }
}
impl PartialEq for EvidenceTrustFrontier {
    fn eq(&self, other: &Self) -> bool {
        self.binding == other.binding
            && self.expected == other.expected
            && Arc::ptr_eq(&self.store, &other.store)
            && match (&self.microsecond_clock, &other.microsecond_clock) {
                (Some(left), Some(right)) => Arc::ptr_eq(left, right),
                (None, None) => true,
                (Some(_), None) | (None, Some(_)) => false,
            }
    }
}
impl Eq for EvidenceTrustFrontier {}
impl EvidenceTrustFrontier {
    pub(super) fn verify_at(&self, supplied_now: u64) -> Result<u64, SignedEvidenceError> {
        crate::production::verify_expected_frontier(
            self.binding,
            &self.expected,
            self.store.as_ref(),
        )
        .map_err(SignedEvidenceError::TrustFrontier)?;
        match &self.microsecond_clock {
            Some(clock) => {
                let trusted = clock
                    .now_unix_ms()
                    .map_err(SignedEvidenceError::TrustFrontier)?
                    .checked_mul(1_000)
                    .ok_or(SignedEvidenceError::ValidityWindow)?;
                Ok(trusted)
            }
            None => Ok(supplied_now),
        }
    }
}
impl LearningEvidenceVerifierV1 {
    /// Installation evidence uses Unix microseconds. The protected clock is
    /// retained through cloned verifiers and opaque roles. This clock supplies
    /// the authorization time; caller wall time cannot activate future evidence
    /// early or postpone signed expiry.
    pub fn with_microsecond_authority_clock(
        mut self,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<Self, AuthorityTrustError> {
        let frontier = self
            .activation_frontier
            .as_mut()
            .ok_or(AuthorityTrustError::Invalid)?;
        frontier.microsecond_clock = Some(clock);
        Ok(self)
    }

    pub(crate) fn bind_activation_frontier(
        &mut self,
        binding: Digest32,
        expected: LearningTrustFrontier,
        store: Arc<dyn AuthorityFrontierStore<LearningTrustFrontier>>,
    ) -> Result<(), AuthorityTrustError> {
        crate::production::verify_expected_frontier(binding, &expected, store.as_ref())?;
        self.activation_frontier = Some(EvidenceTrustFrontier {
            binding,
            expected,
            store,
            microsecond_clock: None,
        });
        Ok(())
    }
}
