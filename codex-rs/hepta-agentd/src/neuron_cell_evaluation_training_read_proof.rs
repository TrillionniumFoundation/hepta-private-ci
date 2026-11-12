//! Private panel read transactions on the actual original Trainer peers.
//! Intermediate slots authenticate the original immutable Training pin. They
//! are not CURRENT results: only the original first and last peer reads close
//! this call, and no proof, signature or authority is returned to a caller.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;

use super::Error;
use super::OriginalCellEvaluationPanelMemberOwnersV1;
use super::OriginalCellEvaluationQualificationConfigV1;
use super::OriginalCellEvaluationQualificationSourcesV1;
use super::binding;
use crate::LearningIterationEvidenceClientV1;

#[path = "neuron_cell_evaluation_panel_receipt_read.rs"]
pub(super) mod receipt_read;
pub(super) use receipt_read::OriginalPanelReceiptReadV1;

type Member = OriginalCellEvaluationPanelMemberOwnersV1<
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
>;

pub(super) enum OriginalPanelTrainingSourceV1 {
    Individual,
    Bound(Arc<OriginalPanelTrainingPinV1>),
    ReadbackMembers(Arc<Vec<OriginalPanelTrainingPinV1>>),
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
    receipt: ReceiptMode,
    admitted: AtomicBool,
}

pub(super) enum OriginalPanelTrainingReadV1<'call> {
    Individual,
    Panel(OriginalPanelTrainingProofV1<'call>),
}

pub(super) struct OriginalPanelTrainingProofV1<'call> {
    call: &'call OriginalPanelTrainingCallV1,
    cursor: Cursor,
    receipt_completed: bool,
}

enum ReceiptMode {
    Physical,
    BoundReadback,
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

    /// A readonly Host call pins each existing member separately. Even two
    /// members with the same Training bytes retain distinct source slots.
    pub(super) fn readback_call(
        &self,
        primary: &Member,
        retention: &[Member],
    ) -> Result<OriginalPanelTrainingCallV1, Error> {
        match self {
            Self::Bound(_) => {
                let mut call = Self::call(self, retention.len() + 1)?;
                call.receipt = ReceiptMode::BoundReadback;
                return Ok(call);
            }
            Self::Individual => {}
            Self::ReadbackMembers(_) => return Err(Error::CommitUncertain),
        }
        if retention.is_empty() {
            return Err(Error::Binding("original nonempty retention panel"));
        }
        let slots = retention
            .len()
            .checked_add(1)
            .and_then(|members| members.checked_mul(8))
            .ok_or(Error::Binding("original panel Training read bound"))?;
        let members = std::iter::once(primary)
            .chain(retention)
            .map(|member| OriginalPanelTrainingPinV1 {
                trainer: Arc::clone(&member.trainer),
                config: member.qualification.config.clone(),
            })
            .collect();
        Ok(OriginalPanelTrainingCallV1 {
            source: Self::ReadbackMembers(Arc::new(members)),
            identity: Arc::new(()),
            slots,
            receipt: ReceiptMode::Physical,
            admitted: AtomicBool::new(false),
        })
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
            Self::ReadbackMembers(_) => return Err(Error::CommitUncertain),
        };
        Ok(OriginalPanelTrainingCallV1 {
            source,
            identity: Arc::new(()),
            slots,
            receipt: ReceiptMode::Physical,
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
            OriginalPanelTrainingSourceV1::Individual => {
                Ok(OriginalPanelTrainingReadV1::Individual)
            }
            OriginalPanelTrainingSourceV1::Bound(_)
            | OriginalPanelTrainingSourceV1::ReadbackMembers(_) => Ok(
                OriginalPanelTrainingReadV1::Panel(OriginalPanelTrainingProofV1 {
                    call: self,
                    cursor: Cursor::Next(0),
                    receipt_completed: false,
                }),
            ),
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
            Self::Individual => {
                OriginalCellEvaluationQualificationSourcesV1::read_trainer(source, config).await
            }
            Self::Panel(proof) => {
                let Cursor::Next(slot) = std::mem::replace(&mut proof.cursor, Cursor::Refused)
                else {
                    return Err(Error::CommitUncertain);
                };
                if matches!(proof.call.receipt, ReceiptMode::BoundReadback)
                    && slot >= proof.call.slots / 2
                    && !proof.receipt_completed
                {
                    return Err(Error::CommitUncertain);
                }
                // A failed or canceled await never leaves a reusable slot.
                let (original, physical) = match &proof.call.source {
                    OriginalPanelTrainingSourceV1::Individual => {
                        return Err(Error::CommitUncertain);
                    }
                    OriginalPanelTrainingSourceV1::Bound(original) => {
                        original.require_source(source.trainer, config)?;
                        (original.as_ref(), slot == 0 || slot + 1 == proof.call.slots)
                    }
                    OriginalPanelTrainingSourceV1::ReadbackMembers(members) => {
                        // Each panel pass visits every member's prepare and
                        // finish slots. Four passes close this readonly call.
                        let width = members.len() * 2;
                        let original = &members[(slot % width) / 2];
                        let member_slot = (slot / width) * 2 + slot % 2;
                        original.require_member_source(source.trainer, config)?;
                        (original, member_slot == 0 || member_slot == 7)
                    }
                };
                if physical {
                    // These are the existing prepare / finish_readback slots,
                    // never an earlier read moved outside the physical work.
                    OriginalCellEvaluationQualificationSourcesV1::read_trainer(source, config)
                        .await?;
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
                OriginalPanelTrainingSourceV1::Bound(_)
                | OriginalPanelTrainingSourceV1::ReadbackMembers(_) => Err(Error::CommitUncertain),
            },
            Self::Panel(proof) => {
                let same_source = match (&proof.call.source, &expected.source) {
                    (
                        OriginalPanelTrainingSourceV1::Bound(original),
                        OriginalPanelTrainingSourceV1::Bound(expected_source),
                    ) => Arc::ptr_eq(original, expected_source),
                    (
                        OriginalPanelTrainingSourceV1::ReadbackMembers(original),
                        OriginalPanelTrainingSourceV1::ReadbackMembers(expected_source),
                    ) => Arc::ptr_eq(original, expected_source),
                    _ => return Err(Error::CommitUncertain),
                };
                if !Arc::ptr_eq(&proof.call.identity, &expected.identity) || !same_source {
                    return Err(Error::Binding(
                        "same completed panel Training call and Source",
                    ));
                }
                if !matches!(proof.cursor, Cursor::Complete)
                    || matches!(proof.call.receipt, ReceiptMode::BoundReadback)
                        && !proof.receipt_completed
                {
                    return Err(Error::CommitUncertain);
                }
                match &proof.call.source {
                    OriginalPanelTrainingSourceV1::Individual => Err(Error::CommitUncertain),
                    OriginalPanelTrainingSourceV1::Bound(original) => {
                        original.authenticate(current)
                    }
                    OriginalPanelTrainingSourceV1::ReadbackMembers(members) => {
                        for original in members.iter() {
                            original.authenticate(current)?;
                        }
                        Ok(())
                    }
                }
            }
        }
    }
}

#[cfg(test)]
impl OriginalPanelTrainingCallV1 {
    pub(super) fn fixture_same_call_new_source(&self) -> Self {
        let source = match &self.source {
            OriginalPanelTrainingSourceV1::Individual => {
                panic!("actual original Trainer composition is required");
            }
            OriginalPanelTrainingSourceV1::Bound(original) => {
                OriginalPanelTrainingSourceV1::from_original_training_readback(
                    Arc::clone(&original.trainer),
                    &original.config,
                )
            }
            OriginalPanelTrainingSourceV1::ReadbackMembers(members) => {
                OriginalPanelTrainingSourceV1::ReadbackMembers(Arc::new(
                    members
                        .iter()
                        .map(|original| OriginalPanelTrainingPinV1 {
                            trainer: Arc::clone(&original.trainer),
                            config: original.config.clone(),
                        })
                        .collect(),
                ))
            }
        };
        Self {
            source,
            identity: Arc::clone(&self.identity),
            slots: self.slots,
            receipt: match &self.receipt {
                ReceiptMode::Physical => ReceiptMode::Physical,
                ReceiptMode::BoundReadback => ReceiptMode::BoundReadback,
            },
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
            return Err(Error::Binding(
                "same actual panel Trainer channel and full Training pin",
            ));
        }
        Ok(())
    }

    fn require_member_source(
        &self,
        trainer: &LearningIterationEvidenceClientV1,
        config: &OriginalCellEvaluationQualificationConfigV1,
    ) -> Result<(), Error> {
        self.require_source(trainer, config)?;
        if self.config.plan != config.plan
            || self.config.execution_namespace != config.execution_namespace
            || self.config.qualification_namespace != config.qualification_namespace
            || self.config.context.evaluator != config.context.evaluator
            || self.config.context.retention_receipt_digests
                != config.context.retention_receipt_digests
            || self.config.context.unlearning_receipt_digest
                != config.context.unlearning_receipt_digest
            || self.config.product_evidence != config.product_evidence
            || self.config.execution_evidence != config.execution_evidence
        {
            return Err(Error::Binding("same original readonly panel member"));
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
