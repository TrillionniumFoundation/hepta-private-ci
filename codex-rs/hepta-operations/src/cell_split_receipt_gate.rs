//! Fail-closed receipt sequencing for a single Cell Split attempt.
//!
//! This is an admission gate, NOT an executor and NOT a durable store.
//! The caller must verify the external operation receipt with its issuing
//! authority and durably commit the transition before performing the next
//! effect. Neither a digest nor this gate alone authorizes cutover.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SplitStep {
    ArtifactLoaded,
    ChildMigrated,
    ChildBootstrapped,
    FinalUseAuthorized,
    PreviousGenerationFenced,
    RouteCutover,
    Completed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedSplitReceipt {
    /// Stable external operation identity, not merely a content hash.
    pub operation_id: String,
    pub scope: String,
    pub attempt_id: String,
    pub issuing_owner: String,
    pub issuer_receipt_id: String,
    pub generation: u64,
    /// Set only by the adapter that authenticated the issuing owner and
    /// checked its authoritative state, never from the caller's claim.
    pub externally_verified: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SplitGateError {
    InvalidIdentity,
    UnverifiedReceipt,
    IncorrectStep,
    DuplicateReceipt,
    GenerationMismatch,
    Terminal,
}

#[derive(Clone, Debug)]
pub struct CellSplitReceiptGate {
    scope: String,
    attempt_id: String,
    old_generation: u64,
    new_generation: u64,
    accepted: Vec<(SplitStep, String, String)>,
}

impl CellSplitReceiptGate {
    pub fn new(
        scope: String,
        attempt_id: String,
        old_generation: u64,
        new_generation: u64,
    ) -> Result<Self, SplitGateError> {
        if scope.is_empty()
            || attempt_id.is_empty()
            || old_generation == 0
            || new_generation <= old_generation
        {
            return Err(SplitGateError::InvalidIdentity);
        }
        Ok(Self {
            scope,
            attempt_id,
            old_generation,
            new_generation,
            accepted: Vec::new(),
        })
    }

    pub fn next_step(&self) -> Option<SplitStep> {
        const ORDER: [SplitStep; 6] = [
            SplitStep::ArtifactLoaded,
            SplitStep::ChildMigrated,
            SplitStep::ChildBootstrapped,
            SplitStep::FinalUseAuthorized,
            SplitStep::PreviousGenerationFenced,
            SplitStep::RouteCutover,
        ];
        ORDER.get(self.accepted.len()).copied()
    }

    /// This method only validates ordering/bindings. A production caller
    /// MUST authenticate the receipt and durably record it before continuing.
    pub fn record(
        &mut self,
        step: SplitStep,
        receipt: VerifiedSplitReceipt,
    ) -> Result<(), SplitGateError> {
        let expected = self.next_step().ok_or(SplitGateError::Terminal)?;
        if step != expected {
            return Err(SplitGateError::IncorrectStep);
        }
        if !receipt.externally_verified {
            return Err(SplitGateError::UnverifiedReceipt);
        }
        if receipt.scope != self.scope
            || receipt.attempt_id != self.attempt_id
            || receipt.operation_id.is_empty()
            || receipt.issuing_owner.is_empty()
            || receipt.issuer_receipt_id.is_empty()
        {
            return Err(SplitGateError::InvalidIdentity);
        }
        let expected_generation = if step == SplitStep::PreviousGenerationFenced {
            self.old_generation
        } else {
            self.new_generation
        };
        if receipt.generation != expected_generation {
            return Err(SplitGateError::GenerationMismatch);
        }
        if self.accepted.iter().any(|(_, owner, id)| {
            owner == &receipt.issuing_owner && id == &receipt.issuer_receipt_id
        }) {
            return Err(SplitGateError::DuplicateReceipt);
        }
        self.accepted
            .push((step, receipt.issuing_owner, receipt.issuer_receipt_id));
        Ok(())
    }

    pub fn is_complete(&self) -> bool {
        self.next_step().is_none()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn gate() -> CellSplitReceiptGate {
        CellSplitReceiptGate::new("scope:a".into(), "attempt:1".into(), 4, 5).unwrap()
    }

    fn receipt(step: SplitStep, index: usize) -> VerifiedSplitReceipt {
        VerifiedSplitReceipt {
            operation_id: format!("op:{index}"),
            scope: "scope:a".into(),
            attempt_id: "attempt:1".into(),
            issuing_owner: format!("owner:{index}"),
            issuer_receipt_id: format!("receipt:{index}"),
            generation: if step == SplitStep::PreviousGenerationFenced { 4 } else { 5 },
            externally_verified: true,
        }
    }

    #[test]
    fn split_requires_all_six_external_receipts_in_order() {
        let mut gate = gate();
        let steps = [
            SplitStep::ArtifactLoaded,
            SplitStep::ChildMigrated,
            SplitStep::ChildBootstrapped,
            SplitStep::FinalUseAuthorized,
            SplitStep::PreviousGenerationFenced,
            SplitStep::RouteCutover,
        ];
        for (index, step) in steps.into_iter().enumerate() {
            assert_eq!(gate.next_step(), Some(step));
            gate.record(step, receipt(step, index)).unwrap();
        }
        assert!(gate.is_complete());
        assert_eq!(gate.next_step(), None);
        assert_eq!(
            gate.record(SplitStep::RouteCutover, receipt(SplitStep::RouteCutover, 7)),
            Err(SplitGateError::Terminal)
        );
    }

    #[test]
    fn cannot_cutover_without_predecessors_or_trust() {
        let mut gate = gate();
        assert_eq!(
            gate.record(SplitStep::RouteCutover, receipt(SplitStep::RouteCutover, 9)),
            Err(SplitGateError::IncorrectStep)
        );
        let mut claimed = receipt(SplitStep::ArtifactLoaded, 0);
        claimed.externally_verified = false;
        assert_eq!(
            gate.record(SplitStep::ArtifactLoaded, claimed),
            Err(SplitGateError::UnverifiedReceipt)
        );
        assert_eq!(gate.next_step(), Some(SplitStep::ArtifactLoaded));
    }

    #[test]
    fn rejects_wrong_scope_generation_and_reused_external_receipt() {
        let mut gate = gate();
        let mut wrong = receipt(SplitStep::ArtifactLoaded, 0);
        wrong.scope = "scope:other".into();
        assert_eq!(gate.record(SplitStep::ArtifactLoaded, wrong), Err(SplitGateError::InvalidIdentity));
        let mut wrong = receipt(SplitStep::ArtifactLoaded, 0);
        wrong.generation = 4;
        assert_eq!(gate.record(SplitStep::ArtifactLoaded, wrong), Err(SplitGateError::GenerationMismatch));
        gate.record(SplitStep::ArtifactLoaded, receipt(SplitStep::ArtifactLoaded, 0)).unwrap();
        let mut reused = receipt(SplitStep::ChildMigrated, 1);
        reused.issuing_owner = "owner:0".into();
        reused.issuer_receipt_id = "receipt:0".into();
        assert_eq!(gate.record(SplitStep::ChildMigrated, reused), Err(SplitGateError::DuplicateReceipt));
    }
}
