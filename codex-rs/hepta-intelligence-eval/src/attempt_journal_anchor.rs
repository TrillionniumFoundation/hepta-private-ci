//! Independent anchor acknowledgement precedes successful journal acknowledgement.
use std::fs::File;

use super::*;

/// Independently retained, authenticated, linearizable anchor authority.
/// Absence is admissible only at initialization. CAS failure is never permission
/// to reset the journal or lower an anchor. Implementations must sync durable
/// state before success, and report any uncertain write as Indeterminate.
pub trait ProductEvaluationAttemptAnchorStoreV1 {
    fn load(&mut self, binding: Digest32) -> Result<Option<ProductEvaluationAttemptAnchorV1>, ProductEvaluationAttemptJournalErrorV1>;
    fn compare_and_swap(&mut self, binding: Digest32, expected: Option<ProductEvaluationAttemptAnchorV1>, next: ProductEvaluationAttemptAnchorV1) -> Result<(), ProductEvaluationAttemptJournalErrorV1>;
}

pub struct AnchoredProductEvaluationAttemptJournalV1<A> {
    journal: LockedFileProductEvaluationAttemptJournalV1,
    authority: A,
    retained: ProductEvaluationAttemptAnchorV1,
    poisoned: bool,
}

impl<A: ProductEvaluationAttemptAnchorStoreV1> AnchoredProductEvaluationAttemptJournalV1<A> {
    pub fn create(file: File, binding: Digest32, mut authority: A) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        if authority.load(binding)?.is_some() { return Err(ProductEvaluationAttemptJournalErrorV1::AlreadyInitialized); }
        let journal = LockedFileProductEvaluationAttemptJournalV1::create(file, binding)?;
        let retained = journal.anchor()?;
        authority.compare_and_swap(binding, /*expected*/ None, retained)?;
        Ok(Self { journal, authority, retained, poisoned: false })
    }

    pub fn recover(file: File, binding: Digest32, mut authority: A) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        let retained = authority.load(binding)?.ok_or(ProductEvaluationAttemptJournalErrorV1::Binding)?;
        let journal = LockedFileProductEvaluationAttemptJournalV1::recover_with_anchor(file, binding, retained)?;
        let recovered = journal.anchor()?;
        if recovered != retained {
            // A complete post-anchor tail may have committed before its ack was
            // lost. Seal that exact recovered history before exposing it.
            authority.compare_and_swap(binding, Some(retained), recovered)?;
        }
        Ok(Self { journal, authority, retained: recovered, poisoned: false })
    }

    pub fn anchor(&self) -> Result<ProductEvaluationAttemptAnchorV1, ProductEvaluationAttemptJournalErrorV1> {
        if self.poisoned { return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate); }
        if self.journal.anchor()? != self.retained {
            return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate);
        }
        Ok(self.retained)
    }
}

impl<A: ProductEvaluationAttemptAnchorStoreV1> ProductEvaluationAttemptJournalV1 for AnchoredProductEvaluationAttemptJournalV1<A> {
    fn append(&mut self, transition: ProductEvaluationAttemptTransitionV1) -> Result<ProductEvaluationAttemptReceiptV1, ProductEvaluationAttemptJournalErrorV1> {
        self.anchor()?;
        let receipt = self.journal.append(transition)?;
        let next = self.journal.anchor()?;
        if next != self.retained {
            let advanced = self.authority.compare_and_swap(next.binding, Some(self.retained), next);
            if advanced.is_err() {
                self.poisoned = true;
                return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate);
            }
            self.retained = next;
        }
        Ok(receipt)
    }

    fn latest(&mut self, attempt_id: &StableId) -> Result<Option<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1> {
        self.anchor()?;
        self.journal.latest(attempt_id)
    }

    fn history(&mut self, attempt_id: &StableId) -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1> {
        self.anchor()?;
        self.journal.history(attempt_id)
    }

    fn pending(&mut self, after: Option<&StableId>, limit: usize) -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1> {
        self.anchor()?;
        self.journal.pending(after, limit)
    }
}
