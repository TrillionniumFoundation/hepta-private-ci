//! Admission against the writer's complete root-authenticated trust lifetime.

use super::LedgerWriter;
use super::ProductionLedgerError;
use crate::LearningEvidenceRoleV1;
use crate::SignedLearningEvidenceV1;
use crate::VerifiedLearningEvidenceV1;

impl LedgerWriter {
    /// Require current root and distribution authority at the supplied trusted
    /// time. Consumers must call this before invoking external work; the signed
    /// ingress methods also enforce it before admitting evidence.
    pub fn ensure_current_trust(&self, now: u64) -> Result<(), ProductionLedgerError> {
        if !self.trust.is_current_at(now) {
            return Err(ProductionLedgerError::Binding(
                "learning trust is not current",
            ));
        }
        Ok(())
    }

    pub(super) fn verify_current_evidence(
        &self,
        role: LearningEvidenceRoleV1,
        evidence: &SignedLearningEvidenceV1,
        payload: &[u8],
        now: u64,
    ) -> Result<VerifiedLearningEvidenceV1, ProductionLedgerError> {
        self.ensure_current_trust(now)?;
        self.trust
            .verifier()
            .verify(role, evidence, payload, now)
            .map_err(Into::into)
    }
}
