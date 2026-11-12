//! One private panel read transaction on the same actual bounded Trainer peer.
//! Intermediate slots authenticate the original immutable Training pin. They
//! are not CURRENT results: only the original first and last peer reads close
//! this call, and no proof, signature or authority is returned to a caller.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_neuron::AnchorWitnessStore;

use super::Error;
use super::OriginalCellEvaluationQualificationConfigV1;
use super::OriginalCellEvaluationQualificationSourcesV1;
use super::binding;
use crate::LearningIterationEvidenceClientV1;

pub(super) enum OriginalPanelTrainingSourceV1 {
    Individual,
    Bound(Arc<OriginalPanelTrainingPinV1>),
}

pub(super) struct OriginalPanelTrainingPinV1 {
    trainer: Arc<LearningIterationEvidenceClientV1>,
    config: OriginalCellEvaluationQualificationConfigV1,
}

/// This scope lives only in one held Host call. Its borrowed proof cannot
/// escape that call, and a canceled read cannot begin another proof in it.
pub(super) struct OriginalPanelTrainingCallV1 {
    source: OriginalPanelTrainingSourceV1,
    identity: Arc<()>,
    slots: usize,
    admitted: AtomicBool,
}

pub(super) enum OriginalPanelTrainingReadV1<'call> {
    Individual,
    Panel(OriginalPanelTrainingProofV1<'call>),
}

pub(super) struct OriginalPanelTrainingProofV1<'call> {
    call: &'call OriginalPanelTrainingCallV1,
    cursor: Cursor,
}

enum Cursor {
    Next(usize),
    Complete,
    Refused,
}

impl OriginalPanelTrainingSourceV1 {
    /// Only the consuming actual Trainer-readback factory installs this pin.
    /// The Arc allocation distinguishes another Source with identical bytes.
    pub(super) fn from_original_training_readback(
        trainer: Arc<LearningIterationEvidenceClientV1>,
        config: &OriginalCellEvaluationQualificationConfigV1,
    ) -> Self {
        Self::Bound(Arc::new(OriginalPanelTrainingPinV1 {
            trainer,
            config: config.clone(),
        }))
    }

    pub(super) fn call(&self, members: usize) -> Result<OriginalPanelTrainingCallV1, Error> {
        if members < 2 {
            return Err(Error::Binding("original nonempty retention panel"));
        }
        let slots = members
            .checked_mul(8)
            .ok_or(Error::Binding("original panel Training read bound"))?;
        let source = match self {
            Self::Individual => Self::Individual,
            Self::Bound(original) => Self::Bound(Arc::clone(original)),
        };
        Ok(OriginalPanelTrainingCallV1 {
            source,
            identity: Arc::new(()),
            slots,
            admitted: AtomicBool::new(false),
        })
    }
}

impl OriginalPanelTrainingCallV1 {
    pub(super) fn begin(&self) -> Result<OriginalPanelTrainingReadV1<'_>, Error> {
        self.admitted
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| Error::CommitUncertain)?;
        match &self.source {
            OriginalPanelTrainingSourceV1::Individual => Ok(OriginalPanelTrainingReadV1::Individual),
            OriginalPanelTrainingSourceV1::Bound(_) => Ok(OriginalPanelTrainingReadV1::Panel(
                OriginalPanelTrainingProofV1 {
                    call: self,
                    cursor: Cursor::Next(0),
                },
            )),
        }
    }
}

impl OriginalPanelTrainingReadV1<'_> {
    pub(super) async fn read(
        &mut self,
        source: &OriginalCellEvaluationQualificationSourcesV1<
            '_,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
            impl AnchorWitnessStore,
        >,
        config: &OriginalCellEvaluationQualificationConfigV1,
    ) -> Result<(), Error> {
        match self {
            Self::Individual => OriginalCellEvaluationQualificationSourcesV1::read_trainer(source, config).await,
            Self::Panel(proof) => {
                let Cursor::Next(slot) = std::mem::replace(&mut proof.cursor, Cursor::Refused) else {
                    return Err(Error::CommitUncertain);
                };
                // A failed or canceled await never leaves a reusable slot.
                let OriginalPanelTrainingSourceV1::Bound(original) = &proof.call.source else {
                    return Err(Error::CommitUncertain);
                };
                original.require_source(source.trainer, config)?;
                if slot == 0 || slot + 1 == proof.call.slots {
                    // These are the existing prepare / finish_readback slots,
                    // never an earlier read moved outside the physical work.
                    OriginalCellEvaluationQualificationSourcesV1::read_trainer(source, config).await?;
                }
                original.authenticate(binding::now()?)?;
                proof.cursor = if slot + 1 == proof.call.slots {
                    Cursor::Complete
                } else {
                    Cursor::Next(slot + 1)
                };
                Ok(())
            }
        }
    }

    pub(super) fn finish(
        self,
        expected: &OriginalPanelTrainingCallV1,
        current: u64,
    ) -> Result<(), Error> {
        match self {
            Self::Individual => match &expected.source {
                OriginalPanelTrainingSourceV1::Individual => Ok(()),
                OriginalPanelTrainingSourceV1::Bound(_) => Err(Error::CommitUncertain),
            },
            Self::Panel(proof) => {
                let (
                    OriginalPanelTrainingSourceV1::Bound(original),
                    OriginalPanelTrainingSourceV1::Bound(expected_source),
                ) = (&proof.call.source, &expected.source)
                else {
                    return Err(Error::CommitUncertain);
                };
                if !Arc::ptr_eq(&proof.call.identity, &expected.identity)
                    || !Arc::ptr_eq(original, expected_source)
                {
                    return Err(Error::Binding("same completed panel Training call and Source"));
                }
                if !matches!(proof.cursor, Cursor::Complete) {
                    return Err(Error::CommitUncertain);
                }
                original.authenticate(current)
            }
        }
    }
}

#[cfg(test)]
impl OriginalPanelTrainingCallV1 {
    pub(super) fn fixture_same_call_new_source(&self) -> Self {
        let OriginalPanelTrainingSourceV1::Bound(original) = &self.source else {
            panic!("actual original Trainer composition is required");
        };
        Self {
            source: OriginalPanelTrainingSourceV1::from_original_training_readback(
                Arc::clone(&original.trainer), &original.config,
            ),
            identity: Arc::clone(&self.identity),
            slots: self.slots,
            admitted: AtomicBool::new(true),
        }
    }
}

impl OriginalPanelTrainingPinV1 {
    fn require_source(
        &self,
        trainer: &LearningIterationEvidenceClientV1,
        config: &OriginalCellEvaluationQualificationConfigV1,
    ) -> Result<(), Error> {
        if !std::ptr::eq(self.trainer.as_ref(), trainer)
            || self.config.training != config.training
            || self.config.scope != config.scope
            || self.config.training_evidence != config.training_evidence
            || self.config.context.generator != config.context.generator
            || self.config.verifier.trust_digest() != config.verifier.trust_digest()
            || self.config.verifier.scope_digest() != config.verifier.scope_digest()
            || self.config.verifier.objective_digest() != config.verifier.objective_digest()
        {
            return Err(Error::Binding("same actual panel Trainer channel and full Training pin"));
        }
        Ok(())
    }

    fn authenticate(&self, current: u64) -> Result<(), Error> {
        let original = self.config.verifier.verify(
            LearningEvidenceRoleV1::Generator,
            &self.config.training_evidence,
            &learning_iteration_receipt_signing_bytes_v1(binding::training_receipt(&self.config)?)?,
            current,
        )?;
        if original.principal() != &self.config.context.generator {
            return Err(Error::Binding("original panel Training Generator custody"));
        }
        Ok(())
    }
}
