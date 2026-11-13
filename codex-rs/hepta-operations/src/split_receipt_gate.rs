//! Fail-closed ordering gate for externally verified Cell Split receipts.
//!
//! This is NOT an executor, signer, artifact store, CNS client or durable ledger.
//! Only the owning service may persist verified receipts and perform effects.
//! Reconstruct this gate from independently verified durable receipts on restart.

use codex_hepta_types::{Digest32, StableId};

/// A strict, non-skippable sequence. In particular cutover follows a
/// generation fence rather than creating the fence after routing changes.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SplitStageV1 {
    ArtifactLoaded,
    ChildStateCommitted,
    ShadowAccepted,
    FinalUseAuthorized,
    GenerationFenced,
    RouteCutover,
}

impl SplitStageV1 {
    const fn index(self) -> usize {
        match self {
            Self::ArtifactLoaded => 0,
            Self::ChildStateCommitted => 1,
            Self::ShadowAccepted => 2,
            Self::FinalUseAuthorized => 3,
            Self::GenerationFenced => 4,
            Self::RouteCutover => 5,
        }
    }
}

/// Receipt metadata is never evidence of a real effect on its own.
/// The caller must verify the issuer signature and query the independent
/// destination owner before allowing this metadata to advance the gate.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SplitStageReceiptV1 {
    pub operation_id: StableId,
    pub parent_generation: u64,
    pub stage: SplitStageV1,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SplitReceiptErrorV1 {
    WrongOperation,
    WrongGeneration,
    InvalidReceipt,
    OutOfOrder,
    ConflictingReplay,
    Complete,
}

/// In-memory safety projection only; not itself a durable source of truth.
pub struct SplitReceiptGateV1 {
    operation_id: StableId,
    parent_generation: u64,
    receipts: [Option<Digest32>; 6],
    next: usize,
}

impl SplitReceiptGateV1 {
    pub fn new(operation_id: StableId, parent_generation: u64) -> Self {
        Self {
            operation_id,
            parent_generation,
            receipts: [None; 6],
            next: 0,
        }
    }

    /// `verify` must reject untrusted, unsigned, stale or merely digest-only
    /// declarations. It must also establish that the external effect committed.
    ///
    /// A duplicate verified receipt is idempotent only if its digest matches.
    pub fn record_verified(
        &mut self,
        receipt: &SplitStageReceiptV1,
        verify: impl FnOnce(&SplitStageReceiptV1) -> bool,
    ) -> Result<(), SplitReceiptErrorV1> {
        if receipt.operation_id != self.operation_id {
            return Err(SplitReceiptErrorV1::WrongOperation);
        }
        if receipt.parent_generation != self.parent_generation {
            return Err(SplitReceiptErrorV1::WrongGeneration);
        }
        if receipt.receipt_digest.is_zero() || !verify(receipt) {
            return Err(SplitReceiptErrorV1::InvalidReceipt);
        }
        let index = receipt.stage.index();
        if index < self.next {
            return if self.receipts[index] == Some(receipt.receipt_digest) {
                Ok(())
            } else {
                Err(SplitReceiptErrorV1::ConflictingReplay)
            };
        }
        if self.next == self.receipts.len() {
            return Err(SplitReceiptErrorV1::Complete);
        }
        if index != self.next {
            return Err(SplitReceiptErrorV1::OutOfOrder);
        }
        self.receipts[index] = Some(receipt.receipt_digest);
        self.next += 1;
        Ok(())
    }

    pub fn next_stage(&self) -> Option<SplitStageV1> {
        match self.next {
            0 => Some(SplitStageV1::ArtifactLoaded),
            1 => Some(SplitStageV1::ChildStateCommitted),
            2 => Some(SplitStageV1::ShadowAccepted),
            3 => Some(SplitStageV1::FinalUseAuthorized),
            4 => Some(SplitStageV1::GenerationFenced),
            5 => Some(SplitStageV1::RouteCutover),
            _ => None,
        }
    }

    pub fn completed(&self) -> bool {
        self.next == self.receipts.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn receipt(stage: SplitStageV1) -> SplitStageReceiptV1 {
        SplitStageReceiptV1 {
            operation_id: StableId::new("split:operation:1").expect("id"),
            parent_generation: 4,
            stage,
            receipt_digest: Digest32::of_bytes(format!("{stage:?}").as_bytes()),
        }
    }

    fn gate() -> SplitReceiptGateV1 {
        SplitReceiptGateV1::new(StableId::new("split:operation:1").expect("id"), 4)
    }

    #[test]
    fn strictly_orders_independently_verified_effects() {
        let mut gate = gate();
        assert_eq!(
            gate.record_verified(&receipt(SplitStageV1::RouteCutover), |_| true),
            Err(SplitReceiptErrorV1::OutOfOrder)
        );
        for stage in [
            SplitStageV1::ArtifactLoaded,
            SplitStageV1::ChildStateCommitted,
            SplitStageV1::ShadowAccepted,
            SplitStageV1::FinalUseAuthorized,
            SplitStageV1::GenerationFenced,
            SplitStageV1::RouteCutover,
        ] {
            gate.record_verified(&receipt(stage), |_| true).expect("verified");
        }
        assert!(gate.completed());
        assert_eq!(gate.next_stage(), None);
    }

    #[test]
    fn rejects_unverified_and_generation_mismatch() {
        let mut gate = gate();
        let first = receipt(SplitStageV1::ArtifactLoaded);
        assert_eq!(
            gate.record_verified(&first, |_| false),
            Err(SplitReceiptErrorV1::InvalidReceipt)
        );
        let mut stale = first.clone();
        stale.parent_generation = 3;
        assert_eq!(
            gate.record_verified(&stale, |_| true),
            Err(SplitReceiptErrorV1::WrongGeneration)
        );
        assert_eq!(gate.next_stage(), Some(SplitStageV1::ArtifactLoaded));
    }

    #[test]
    fn replay_requires_exact_receipt_identity_and_reverification() {
        let mut gate = gate();
        let first = receipt(SplitStageV1::ArtifactLoaded);
        gate.record_verified(&first, |_| true).expect("first");
        gate.record_verified(&first, |_| true).expect("idempotent");
        assert_eq!(
            gate.record_verified(&first, |_| false),
            Err(SplitReceiptErrorV1::InvalidReceipt)
        );
        let mut conflict = first.clone();
        conflict.receipt_digest = Digest32::of_bytes(b"different-issuer-receipt");
        assert_eq!(
            gate.record_verified(&conflict, |_| true),
            Err(SplitReceiptErrorV1::ConflictingReplay)
        );
    }
}
