//! Original bounded owner records with an independently retained recovery head.
//! This is persistence only. A caller still needs its original authorized file,
//! witness, role and exact operation; no path, key or authority is provisioned.

use std::fs::File;

use codex_hepta_intelligence_eval::LockedFileProductEvaluationExecutionErrorV1;
use codex_hepta_intelligence_eval::LockedFileProductEvaluationExecutionStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionClaimV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::WitnessStoreError;
use codex_hepta_types::Digest32;

#[derive(Debug, thiserror::Error)]
pub enum LearningOriginalOwnerErrorV1 {
    #[error("original learning owner binding: {0}")]
    Binding(&'static str),
    #[error("original learning owner has an unresolved operation")]
    Pending,
    #[error("original learning owner commit is uncertain; reopen the same owner")]
    CommitUncertain,
    #[error("original learning owner file: {0}")]
    File(#[from] LockedFileProductEvaluationExecutionErrorV1),
    #[error("original learning owner store: {0}")]
    Store(#[from] ProductEvaluationExecutionStoreErrorV1),
    #[error("original learning owner witness: {0}")]
    Witness(#[from] WitnessStoreError),
    #[error("original learning owner signature: {0}")]
    Evidence(#[from] SignedEvidenceError),
}

type Error = LearningOriginalOwnerErrorV1;

pub(crate) struct LearningOwnerJournalV1<W: AnchorWitnessStore> {
    journal: LockedFileProductEvaluationExecutionStoreV1,
    witness: W,
    fenced: bool,
}

impl<W: AnchorWitnessStore> LearningOwnerJournalV1<W> {
    pub(crate) fn create(file: File, mut witness: W, binding: Digest32) -> Result<Self, Error> {
        if binding.is_zero() || witness.current()?.is_some() {
            return Err(Error::Binding("fresh owner and independent witness"));
        }
        let journal = LockedFileProductEvaluationExecutionStoreV1::create(file, binding)?;
        witness
            .compare_and_swap(None, anchor(journal.anchor())?)
            .map_err(|_| Error::CommitUncertain)?;
        Ok(Self {
            journal,
            witness,
            fenced: false,
        })
    }

    pub(crate) fn recover(file: File, mut witness: W, binding: Digest32) -> Result<Self, Error> {
        let minimum = witness
            .current()?
            .ok_or(Error::Binding("original independent witness"))?;
        let journal = LockedFileProductEvaluationExecutionStoreV1::recover(
            file,
            binding,
            ProductEvaluationExecutionAnchorV1 {
                sequence: minimum
                    .sequence
                    .checked_sub(1)
                    .ok_or(Error::Binding("witness sequence"))?,
                history_digest: minimum.checkpoint_digest,
            },
        )?;
        let current = anchor(journal.anchor())?;
        if current != minimum {
            witness
                .compare_and_swap(Some(minimum), current)
                .map_err(|_| Error::CommitUncertain)?;
        }
        Ok(Self {
            journal,
            witness,
            fenced: false,
        })
    }

    #[cfg(test)]
    pub(crate) fn qualification_file_bytes(
        &mut self,
        maximum_bytes: u64,
    ) -> Result<Vec<u8>, Error> {
        self.require_current()?;
        Ok(self.journal.qualification_file_bytes(maximum_bytes)?)
    }

    /// The closure is invoked only after a new claim and its witness are durable.
    /// An existing Pending operation never invokes it, even after a cold reopen.
    pub(crate) fn commit_once(
        &mut self,
        key: &ProductEvaluationExecutionKeyV1,
        build: impl FnOnce() -> Result<Vec<u8>, Error>,
    ) -> Result<Vec<u8>, Error> {
        self.require_current()?;
        let before = anchor(self.journal.anchor())?;
        match self.journal.claim(key) {
            Ok(ProductEvaluationExecutionClaimV1::Existing(
                ProductEvaluationExecutionStateV1::Completed(bytes),
            )) => {
                self.require_current()?;
                return Ok(bytes);
            }
            Ok(ProductEvaluationExecutionClaimV1::Existing(
                ProductEvaluationExecutionStateV1::Pending,
            )) => {
                return Err(Error::Pending);
            }
            Ok(ProductEvaluationExecutionClaimV1::Claimed) => self.anchor_append(before)?,
            Err(error) => {
                self.fenced = true;
                return Err(error.into());
            }
        }
        let bytes = build()?;
        self.require_current()?;
        let before = anchor(self.journal.anchor())?;
        if self.journal.complete(key, &bytes).is_err() {
            self.fenced = true;
            return Err(Error::CommitUncertain);
        }
        self.anchor_append(before)?;
        let saved = self.read(key)?;
        if saved != bytes {
            self.fenced = true;
            return Err(Error::CommitUncertain);
        }
        Ok(saved)
    }

    pub(crate) fn read(&mut self, key: &ProductEvaluationExecutionKeyV1) -> Result<Vec<u8>, Error> {
        self.require_current()?;
        let state = self.journal.readback(key)?;
        self.require_current()?;
        match state {
            ProductEvaluationExecutionStateV1::Pending => Err(Error::Pending),
            ProductEvaluationExecutionStateV1::Completed(bytes) => Ok(bytes),
        }
    }

    fn require_current(&self) -> Result<(), Error> {
        if self.fenced || self.witness.current()? != Some(anchor(self.journal.anchor())?) {
            return Err(Error::CommitUncertain);
        }
        Ok(())
    }

    fn anchor_append(&mut self, before: JournalAnchor) -> Result<(), Error> {
        if self
            .witness
            .compare_and_swap(Some(before), anchor(self.journal.anchor())?)
            .is_err()
        {
            self.fenced = true;
            return Err(Error::CommitUncertain);
        }
        Ok(())
    }
}

fn anchor(value: ProductEvaluationExecutionAnchorV1) -> Result<JournalAnchor, Error> {
    Ok(JournalAnchor {
        sequence: value
            .sequence
            .checked_add(1)
            .ok_or(Error::Binding("owner sequence overflow"))?,
        checkpoint_digest: value.history_digest,
    })
}
