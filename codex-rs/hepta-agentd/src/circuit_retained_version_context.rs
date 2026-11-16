//! Full original E/D/T pins. This data carries no publication permission.
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_types::Digest32;

use super::super::OriginalCircuitRetainedPublicationContextV1;
use super::super::context::PublicationAccess;
use super::Error;
use super::RetainedVersionOriginV1;
use super::now;
use super::require_clock;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

pub(super) struct OriginalVersionCut {
    pub(super) material: OriginalCellQ24MaterialReceiptConfigV1,
    pub(super) dataset: OriginalCellQ24MaterialCommandReceiptV1,
    pub(super) training: OriginalCircuitRetainedPublicationContextV1,
    pub(super) binding: Digest32,
    pub(super) initial_binding: Digest32,
}
impl OriginalVersionCut {
    pub(super) fn from_original(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        dataset: OriginalCellQ24MaterialCommandReceiptV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        origin: RetainedVersionOriginV1,
    ) -> Result<Self, Error> {
        let started = now()?;
        OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            &dataset, &material,
        )?;
        let training = match origin {
            RetainedVersionOriginV1::Fresh => {
                OriginalCircuitRetainedPublicationContextV1::from_original_training(
                    dataset.snapshot().clone(),
                    material.scope.clone(),
                    material.verifier.clone(),
                    training,
                )?
            }
            RetainedVersionOriginV1::Recovered => {
                let mut prefix =
                    LearningIterationCoordinatorV1::from_snapshot(dataset.snapshot().clone())?;
                if prefix.snapshot().receipts.len() != 2
                    || prefix.next_stage()
                        != Some(codex_hepta_learning_artifacts::LearningIterationStageV1::Training)
                {
                    return Err(Error::Binding("original Dataset before retained recovery"));
                }
                prefix.record(
                    training.receipt().clone(),
                    training.receipt().observed_unix_seconds,
                )?;
                OriginalCircuitRetainedPublicationContextV1 {
                    training: prefix.snapshot().clone(),
                    scope: material.scope.clone(),
                    verifier: material.verifier.clone(),
                    training_evidence: training.attestation().clone(),
                }
            }
        };
        let (initial_binding, fresh) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)?;
        require_clock(started, fresh)?;
        let mut cut = Self {
            material,
            dataset,
            training,
            binding: Digest32::ZERO,
            initial_binding,
        };
        cut.binding = cut.authenticate(fresh, PublicationAccess::Readback)?;
        Ok(cut)
    }

    pub(super) fn authenticate(
        &self,
        at: u64,
        access: PublicationAccess,
    ) -> Result<Digest32, Error> {
        let prefix = self.training.authenticate(at, access)?;
        let initial = LearningIterationCoordinatorV1::new(
            prefix.snapshot().request.clone(),
            prefix.snapshot().owners.clone(),
        )?;
        if initial.snapshot() != &self.material.initial
            || self.training.scope != self.material.scope
            || self.dataset.snapshot().receipts != prefix.snapshot().receipts[..2]
            || self.dataset.snapshot().head_digest != prefix.snapshot().receipts[2].predecessor
        {
            return Err(Error::Binding(
                "same original retained initial and Dataset cut",
            ));
        }
        let mut signatures = Vec::new();
        for original in self.dataset.attestations() {
            signatures.extend_from_slice(&original.signing_bytes());
            signatures.extend_from_slice(&original.signature);
        }
        signatures.extend_from_slice(&self.training.training_evidence.signing_bytes());
        signatures.extend_from_slice(&self.training.training_evidence.signature);
        Ok(Digest32::of_parts(&[
            b"hepta.agentd.original-retained-version.command.v1\0",
            self.initial_binding.as_array(),
            &encode_original_owner_snapshot_v1(prefix.snapshot())?,
            self.training.scope.binding().as_array(),
            self.training.verifier.trust_digest().as_array(),
            self.training.verifier.scope_digest().as_array(),
            self.training.verifier.objective_digest().as_array(),
            &signatures,
        ]))
    }

    /// Call after the last peer/file read. This verifies the original full
    /// Material and Training windows, never a newly signed or renewed record.
    pub(super) fn require_fresh(
        &self,
        started: u64,
        access: PublicationAccess,
    ) -> Result<(), Error> {
        let (binding, at) =
            OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(
                &self.material,
            )?;
        let fresh = OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            &self.dataset,
            &self.material,
        )?;
        require_clock(started, at)?;
        require_clock(at, fresh)?;
        if binding != self.initial_binding || self.authenticate(fresh, access)? != self.binding {
            return Err(Error::Binding(
                "same original full retained Version context",
            ));
        }
        Ok(())
    }

    // Pure private pin data for final authentication after releasing the
    // original owner's mutex. This is not a live capability or a lease.
    pub(super) fn duplicate_response_pin(&self) -> Self {
        Self {
            material: self.material.clone(),
            dataset: self.dataset.clone(),
            training: self.original_context(),
            binding: self.binding,
            initial_binding: self.initial_binding,
        }
    }

    pub(super) fn original_context(&self) -> OriginalCircuitRetainedPublicationContextV1 {
        OriginalCircuitRetainedPublicationContextV1 {
            training: self.training.training.clone(),
            scope: self.training.scope.clone(),
            verifier: self.training.verifier.clone(),
            training_evidence: self.training.training_evidence.clone(),
        }
    }
}
