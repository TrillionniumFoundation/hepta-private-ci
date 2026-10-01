//! Already authenticated evidence retained under the same fit memory ledger.

use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;

use super::FinalUseErrorV1;
use crate::OperatorDatasetBindingError;
use crate::OperatorResourceBudgetV1;
use crate::OperatorWorkErrorV1;
use crate::OperatorWorkMeter;
use crate::checked_add;
use crate::checked_u64;

type EvidencePair = (VerifiedLearningEvidenceV1, VerifiedLearningEvidenceV1);

pub(super) struct IssuedEvidenceV1<'a> {
    owner: &'a LedgerWriter,
    evidence: EvidencePair,
    // The reservation remains live across worker dispatch and fitting. Moving
    // this private value cannot detach it from the shared fit budget ledger.
    meter: OperatorWorkMeter,
}

impl<'a> IssuedEvidenceV1<'a> {
    pub(super) fn new(
        authenticated: (&'a LedgerWriter, EvidencePair),
        budget: OperatorResourceBudgetV1,
    ) -> Result<Self, OperatorWorkErrorV1> {
        let (owner, evidence) = authenticated;
        let mut required = checked_u64(std::mem::size_of::<Self>())?;
        for receipt in [&evidence.0, &evidence.1] {
            for id in [
                receipt.principal().principal_id.as_str(),
                receipt.controller_id().as_str(),
            ] {
                required = checked_add(required, checked_u64(id.len())?)?;
            }
        }
        let mut meter = OperatorWorkMeter::new(budget)?;
        meter.reserve_total_bytes(required)?;
        Ok(Self {
            owner,
            evidence,
            meter,
        })
    }

    pub(super) fn revalidate(&mut self, now: u64) -> Result<(), FinalUseErrorV1> {
        self.meter.consume(2)?;
        self.owner
            .revalidate_trust_at(now)
            .map_err(|error| FinalUseErrorV1::OwnerState(error.to_string()))?;
        let verifier = self.owner.verifier();
        verifier
            .revalidate(&self.evidence.0, now)
            .map_err(OperatorDatasetBindingError::SignedEvidence)?;
        verifier
            .revalidate(&self.evidence.1, now)
            .map_err(OperatorDatasetBindingError::SignedEvidence)?;
        verify_signed_independent_roles_v1(&self.evidence.0, &self.evidence.1, now)
            .map_err(OperatorDatasetBindingError::SignedEvidence)?;
        Ok(())
    }
}
