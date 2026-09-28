//! Independent anchor acknowledgement precedes successful journal acknowledgement.
use std::fs::File;

use super::LockedFileProductEvaluationAttemptJournalV1;
use super::ProductEvaluationAttemptAnchorV1;
use super::ProductEvaluationAttemptJournalErrorV1;
use super::ProductEvaluationAttemptJournalV1;
use super::ProductEvaluationAttemptReceiptV1;
use super::ProductEvaluationAttemptTransitionV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

/// Independently retained, authenticated, linearizable anchor authority.
/// Absence is admissible only at initialization. CAS failure is never permission
/// to reset the journal or lower an anchor. Implementations must sync durable
/// state before success, and report any uncertain write as Indeterminate.
pub trait ProductEvaluationAttemptAnchorStoreV1 {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<ProductEvaluationAttemptAnchorV1>, ProductEvaluationAttemptJournalErrorV1>;

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<ProductEvaluationAttemptAnchorV1>,
        next: ProductEvaluationAttemptAnchorV1,
    ) -> Result<(), ProductEvaluationAttemptJournalErrorV1>;
}

pub struct AnchoredProductEvaluationAttemptJournalV1<A> {
    journal: LockedFileProductEvaluationAttemptJournalV1,
    authority: A,
    retained: ProductEvaluationAttemptAnchorV1,
    poisoned: bool,
}

impl<A: ProductEvaluationAttemptAnchorStoreV1> AnchoredProductEvaluationAttemptJournalV1<A> {
    pub fn create(
        file: File,
        binding: Digest32,
        mut authority: A,
    ) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        if authority.load(binding)?.is_some() {
            return Err(ProductEvaluationAttemptJournalErrorV1::AlreadyInitialized);
        }
        let journal = LockedFileProductEvaluationAttemptJournalV1::create(file, binding)?;
        let retained = journal.anchor()?;
        authority.compare_and_swap(binding, None, retained)?;
        Ok(Self {
            journal,
            authority,
            retained,
            poisoned: false,
        })
    }

    pub fn recover(
        file: File,
        binding: Digest32,
        mut authority: A,
    ) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        let retained = authority
            .load(binding)?
            .ok_or(ProductEvaluationAttemptJournalErrorV1::Binding)?;
        // The file backend must prove the retained anchor occurs in the exact
        // replayed prefix, including when there is a complete post-anchor tail.
        let journal = LockedFileProductEvaluationAttemptJournalV1::recover_with_anchor(
            file, binding, retained,
        )?;
        let recovered = journal.anchor()?;
        if recovered != retained {
            // A complete post-anchor tail may have committed before its ack was
            // lost. Seal that exact recovered history before exposing it.
            authority.compare_and_swap(binding, Some(retained), recovered)?;
        }
        Ok(Self {
            journal,
            authority,
            retained: recovered,
            poisoned: false,
        })
    }

    /// Recover from an independently retained checkpoint and replay only the
    /// later journal tail. The normal journal anchor remains authoritative; the
    /// checkpoint authority is a separate derived namespace in the supplied
    /// store and cannot lower or replace that anchor.
    pub fn recover_with_checkpoint<C: ProductEvaluationAttemptAnchorStoreV1>(
        file: File,
        checkpoint: File,
        binding: Digest32,
        mut authority: A,
        checkpoint_authority: &mut C,
    ) -> Result<Self, ProductEvaluationAttemptJournalErrorV1> {
        let retained = authority
            .load(binding)?
            .ok_or(ProductEvaluationAttemptJournalErrorV1::Binding)?;
        let journal = LockedFileProductEvaluationAttemptJournalV1::recover_with_checkpoint(
            file,
            checkpoint,
            binding,
            retained,
            checkpoint_authority,
        )?;
        let recovered = journal.anchor()?;
        if recovered != retained {
            authority.compare_and_swap(binding, Some(retained), recovered)?;
        }
        Ok(Self {
            journal,
            authority,
            retained: recovered,
            poisoned: false,
        })
    }

    /// Persist a reducer checkpoint without changing the journal frontier. The
    /// checkpoint identity is retained under a derived binding in `authority`.
    pub fn checkpoint_into<C: ProductEvaluationAttemptAnchorStoreV1>(
        &self,
        checkpoint: File,
        authority: &mut C,
    ) -> Result<ProductEvaluationAttemptAnchorV1, ProductEvaluationAttemptJournalErrorV1> {
        self.anchor()?;
        self.journal.checkpoint_into(checkpoint, authority)
    }

    pub fn anchor(
        &self,
    ) -> Result<ProductEvaluationAttemptAnchorV1, ProductEvaluationAttemptJournalErrorV1> {
        if self.poisoned {
            return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate);
        }
        if self.journal.anchor()? != self.retained {
            return Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate);
        }
        Ok(self.retained)
    }
}

impl<A: ProductEvaluationAttemptAnchorStoreV1> ProductEvaluationAttemptJournalV1
    for AnchoredProductEvaluationAttemptJournalV1<A>
{
    fn append(
        &mut self,
        transition: ProductEvaluationAttemptTransitionV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, ProductEvaluationAttemptJournalErrorV1> {
        self.anchor()?;
        // Once a write is attempted, do not expose this wrapper again unless
        // BOTH the journal and its independently retained anchor acknowledge.
        // This also covers an error returned while reading the post-write
        // anchor, not just an error from the anchor authority's CAS.
        self.poisoned = true;
        let receipt = ProductEvaluationAttemptJournalV1::append(&mut self.journal, transition)?;
        let next = self.journal.anchor()?;
        if next != self.retained {
            self.authority
                .compare_and_swap(next.binding, Some(self.retained), next)
                .map_err(|_| ProductEvaluationAttemptJournalErrorV1::Indeterminate)?;
            self.retained = next;
        }
        self.poisoned = false;
        Ok(receipt)
    }

    fn latest(
        &mut self,
        attempt_id: &StableId,
    ) -> Result<Option<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        self.anchor()?;
        ProductEvaluationAttemptJournalV1::latest(&mut self.journal, attempt_id)
    }

    fn history(
        &mut self,
        attempt_id: &StableId,
    ) -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        self.anchor()?;
        ProductEvaluationAttemptJournalV1::history(&mut self.journal, attempt_id)
    }

    fn pending(
        &mut self,
        after: Option<&StableId>,
        limit: usize,
    ) -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        self.anchor()?;
        ProductEvaluationAttemptJournalV1::pending(&mut self.journal, after, limit)
    }
}
