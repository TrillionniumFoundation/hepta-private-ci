//! Original Q24 material proposal owner; no Root profile or adoption authority.
//!
//! This first owner layer deliberately is not an ordinary Proposal payload.
//! A future versioned Root registration must bind this profile and revalidate
//! live Dataset/withdrawal and artifact frontiers before enabling that route.
//! A record here authenticates the supplied original training/evaluation chain,
//! not source-label truth, independent custody or a production publication.

use std::fs::File;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::LockedFileProductEvaluationExecutionErrorV1;
use codex_hepta_intelligence_eval::LockedFileProductEvaluationExecutionStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionClaimV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::WitnessStoreError;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::CellEvaluationQualificationRequestV1;
use crate::CellEvaluationQualificationV1;
use crate::CellEvaluationReceiptV1;
use crate::CellEvaluationRunnerV1;
use crate::CellLearningEvaluationErrorV1;
use crate::CellQ24TrainingOwnerErrorV1;
use crate::CellQ24TrainingOwnerV1;

#[path = "cell_q24_model_proposal_admission.rs"]
mod admission;
use admission::Admission;

#[cfg(target_os = "linux")]
#[path = "cell_q24_model_current_owner.rs"]
mod current;

#[derive(Debug, thiserror::Error)]
pub enum CellQ24ModelProposalErrorV1 {
    #[error("Q24 model proposal binding: {0}")]
    Binding(&'static str),
    #[error("original Q24 model proposal is pending; readback only")]
    Pending,
    #[error("Q24 model proposal acknowledgement is uncertain; reopen original owner")]
    CommitUncertain,
    #[error("training: {0}")]
    Training(#[from] CellQ24TrainingOwnerErrorV1),
    #[error("evaluation: {0}")]
    Evaluation(#[from] CellLearningEvaluationErrorV1),
    #[error("learning iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[cfg(target_os = "linux")]
    #[error("original current Evaluation material: {0}")]
    OriginalEvaluationMaterial(Box<crate::OriginalCellEvaluationCommandErrorV1>),
    #[error("proposal file: {0}")]
    File(#[from] LockedFileProductEvaluationExecutionErrorV1),
    #[error("proposal store: {0}")]
    Store(#[from] ProductEvaluationExecutionStoreErrorV1),
    #[error("proposal witness: {0}")]
    Witness(#[from] WitnessStoreError),
}
type Error = CellQ24ModelProposalErrorV1;

/// Original inputs are revalidated on every commit and readback. A cached
/// qualification or a caller-supplied digest cannot authorize this record.
pub struct CellQ24ModelProposalInputsV1<'a, S> {
    pub training_cut: &'a LearningIterationSnapshotV1,
    pub training_attestation: &'a codex_hepta_learning_ledger::SignedLearningEvidenceV1,
    pub runner: &'a CellEvaluationRunnerV1<S>,
    pub evaluation: &'a CellEvaluationReceiptV1,
    pub qualification: &'a CellEvaluationQualificationV1,
    /// Original qualification inputs. `request.now` is ignored: the owner
    /// samples the host clock for current evidence and any new proposal time.
    pub request: &'a CellEvaluationQualificationRequestV1<'a>,
}

/// Original journal result. There is no public receipt constructor or
/// deserializer, no selector grant, and no production Proposal routing.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellQ24ModelProposalReceiptV1 {
    receipt: LearningIterationReceiptV1,
}
impl CellQ24ModelProposalReceiptV1 {
    pub fn learning_receipt(&self) -> &LearningIterationReceiptV1 {
        &self.receipt
    }
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// One explicit owner over an exclusively transferred regular file and an
/// independently retained witness. No files, witnesses or keys are generated.
/// The host must preserve path/directory durability and the witness rollback
/// domain; jointly restoring both does not establish freshness.
pub struct CellQ24ModelProposalOwnerV1<W: AnchorWitnessStore> {
    journal: LockedFileProductEvaluationExecutionStoreV1,
    witness: W,
    dataset_cut: LearningIterationSnapshotV1,
    scope: Digest32,
    binding: Digest32,
    fenced: bool,
    #[cfg(test)]
    test_clock: Option<Box<dyn Fn() -> Result<u64, Error> + Send + Sync>>,
}

impl<W: AnchorWitnessStore> CellQ24ModelProposalOwnerV1<W> {
    pub fn create<T: AnchorWitnessStore>(
        file: File,
        mut witness: W,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        dataset_cut: LearningIterationSnapshotV1,
    ) -> Result<Self, Error> {
        let (scope, binding) = admission::owner_binding(trainer, &dataset_cut)?;
        if witness.current()?.is_some() {
            return Err(Error::Binding("proposal witness already initialized"));
        }
        Self::create_empty_original(file, witness, dataset_cut, scope, binding)
    }

    fn create_empty_original(
        file: File,
        mut witness: W,
        dataset_cut: LearningIterationSnapshotV1,
        scope: Digest32,
        binding: Digest32,
    ) -> Result<Self, Error> {
        let journal = LockedFileProductEvaluationExecutionStoreV1::create(file, binding)?;
        witness
            .compare_and_swap(None, anchor(journal.anchor())?)
            .map_err(|_| Error::CommitUncertain)?;
        Ok(Self {
            journal,
            witness,
            dataset_cut,
            scope,
            binding,
            fenced: false,
            #[cfg(test)]
            test_clock: None,
        })
    }

    /// Reconcile only an already persisted suffix. A pending claim never
    /// becomes a new proposal; completed bytes keep their original timestamp.
    pub fn recover<T: AnchorWitnessStore>(
        file: File,
        mut witness: W,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        dataset_cut: LearningIterationSnapshotV1,
    ) -> Result<Self, Error> {
        let (scope, binding) = admission::owner_binding(trainer, &dataset_cut)?;
        let minimum = witness
            .current()?
            .ok_or(Error::Binding("original proposal witness"))?;
        Self::recover_existing_original(file, witness, dataset_cut, scope, binding, minimum)
    }

    fn recover_existing_original(
        file: File,
        mut witness: W,
        dataset_cut: LearningIterationSnapshotV1,
        scope: Digest32,
        binding: Digest32,
        minimum: JournalAnchor,
    ) -> Result<Self, Error> {
        let journal = LockedFileProductEvaluationExecutionStoreV1::recover(
            file,
            binding,
            ProductEvaluationExecutionAnchorV1 {
                sequence: minimum
                    .sequence
                    .checked_sub(1)
                    .ok_or(Error::Binding("proposal witness sequence"))?,
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
            dataset_cut,
            scope,
            binding,
            fenced: false,
            #[cfg(test)]
            test_clock: None,
        })
    }

    pub fn commit_or_readback<T: AnchorWitnessStore, S: FinalHoldoutCasStoreV1>(
        &mut self,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        inputs: &CellQ24ModelProposalInputsV1<'_, S>,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        let now = self.now()?;
        let admission = self.admit(trainer, inputs, now)?;
        self.commit_admitted(&admission, now)
    }

    fn commit_admitted(
        &mut self,
        admission: &Admission,
        now: u64,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        let key = admission.key(self.binding);
        match self.journal.readback(&key) {
            Ok(state) => return self.decode_current(admission, state),
            Err(ProductEvaluationExecutionStoreErrorV1::Missing) => {}
            Err(error) => return Err(error.into()),
        }
        let payload = admission.encode(now)?;
        self.require_current()?;
        self.complete_admitted(admission, &key, &payload)
    }

    // One original claim/completion algorithm shared by local and sealed remote
    // admission. Each caller checks CURRENT and its pure authorization first.
    fn complete_admitted(
        &mut self,
        admission: &Admission,
        key: &ProductEvaluationExecutionKeyV1,
        payload: &[u8],
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        let before = anchor(self.journal.anchor())?;
        match self.journal.claim(key) {
            Ok(ProductEvaluationExecutionClaimV1::Claimed) => self.anchor_append(before)?,
            Ok(ProductEvaluationExecutionClaimV1::Existing(state)) => {
                return self.decode_current(admission, state);
            }
            Err(_) => {
                self.fenced = true;
                return Err(Error::CommitUncertain);
            }
        }
        let before = anchor(self.journal.anchor())?;
        if self.journal.complete(key, payload).is_err() {
            self.fenced = true;
            return Err(Error::CommitUncertain);
        }
        self.anchor_append(before)?;
        let state = self.journal.readback(key)?;
        self.decode_current(admission, state)
    }

    /// Read-only: Missing and Pending remain errors, including after expiry.
    /// Current original signatures must still validate; this does not renew them.
    pub fn readback<T: AnchorWitnessStore, S: FinalHoldoutCasStoreV1>(
        &mut self,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        inputs: &CellQ24ModelProposalInputsV1<'_, S>,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        let admission = self.admit(trainer, inputs, self.now()?)?;
        let state = self.journal.readback(&admission.key(self.binding))?;
        self.decode_current(&admission, state)
    }

    fn admit<T: AnchorWitnessStore, S: FinalHoldoutCasStoreV1>(
        &mut self,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        inputs: &CellQ24ModelProposalInputsV1<'_, S>,
        now: u64,
    ) -> Result<Admission, Error> {
        self.require_current()?;
        let admission = admission::validate(
            trainer,
            &self.dataset_cut,
            self.scope,
            self.binding,
            inputs,
            now,
        )?;
        self.require_current()?;
        Ok(admission)
    }

    fn now(&self) -> Result<u64, Error> {
        #[cfg(test)]
        if let Some(clock) = &self.test_clock {
            return clock();
        }
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|time| time.as_secs())
            .map_err(|_| Error::Binding("host clock before Unix epoch"))
    }

    #[cfg(test)]
    pub(crate) fn set_test_clock(
        &mut self,
        clock: impl Fn() -> Result<u64, Error> + Send + Sync + 'static,
    ) {
        self.test_clock = Some(Box::new(clock));
    }

    fn require_current(&mut self) -> Result<(), Error> {
        if self.fenced {
            return Err(Error::CommitUncertain);
        }
        let result = (|| {
            let before = self.witness.current()?;
            let physical = anchor(self.journal.read_current_anchor()?)?;
            let after = self.witness.current()?;
            if before != Some(physical) || after != Some(physical) {
                return Err(Error::CommitUncertain);
            }
            Ok(())
        })();
        if result.is_err() {
            self.fenced = true;
        }
        result
    }
    fn decode_current(
        &mut self,
        admission: &Admission,
        state: ProductEvaluationExecutionStateV1,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        let receipt = admission.decode(state)?;
        self.require_current()?;
        Ok(receipt)
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
            .ok_or(Error::Binding("proposal sequence overflow"))?,
        checkpoint_digest: value.history_digest,
    })
}
