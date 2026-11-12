//! Bind a held original channel only after actual D/T/B completion. This
//! retains the first channel deadline and derives cold access by attenuation.

use std::sync::Mutex;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_types::Digest32;

use super::Channel;
use super::Error;
use super::OriginalCircuitEvaluatedSelectionCommandClientV1;
use super::now;
use super::require_clock;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::OriginalCircuitEvaluatedRetentionContextV1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

pub(super) struct Context {
    pub(super) original: OriginalCircuitEvaluatedRetentionContextV1,
}

impl Context {
    pub(super) fn from_original(
        original: OriginalCircuitEvaluatedRetentionContextV1,
    ) -> Result<Self, Error> {
        let value = Self { original };
        value.authenticate(now()?)?;
        Ok(value)
    }

    pub(super) fn authenticate(&self, current: u64) -> Result<(), Error> {
        self.original.original_receipt_predecessors(current)?;
        Ok(())
    }

    pub(super) fn initial(&self) -> Result<LearningIterationSnapshotV1, Error> {
        let snapshot = self.original.snapshot();
        Ok(
            LearningIterationCoordinatorV1::new(snapshot.request.clone(), snapshot.owners.clone())?
                .snapshot()
                .clone(),
        )
    }

    pub(super) fn binding(&self, current: u64) -> Result<Digest32, Error> {
        self.authenticate(current)?;
        Ok(Digest32::of_parts(&[
            b"hepta.agentd.original-circuit-evaluated-selection-command.v1\0",
            &encode_original_owner_snapshot_v1(self.original.snapshot())?,
            self.original.receipt_context_binding().as_array(),
        ]))
    }
}

impl OriginalCircuitEvaluatedSelectionCommandClientV1 {
    pub(crate) fn bind_original_stage_channel(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: &OriginalCellEvaluationCommandReceiptV1,
    ) -> Result<Self, Error> {
        let original = OriginalCircuitEvaluatedRetentionContextV1::from_original_evaluation(
            material.scope.clone(),
            material.verifier.clone(),
            training,
            evaluation,
        )?;
        original.require_new_original_receipt(now()?)?;
        Self::bind_stage_context(
            peer,
            material,
            dataset,
            Context::from_original(original)?,
            false,
        )
    }

    pub(crate) fn recover_original_stage_channel(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        evaluation: &OriginalCellEvaluationCommandReceiptV1,
    ) -> Result<Self, Error> {
        let original = OriginalCircuitEvaluatedRetentionContextV1::recover_original_evaluation(
            material.scope.clone(),
            material.verifier.clone(),
            training,
            evaluation,
        )?;
        Self::bind_stage_context(
            peer,
            material,
            dataset,
            Context::from_original(original)?,
            true,
        )
    }

    fn bind_stage_context(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        context: Context,
        execution_requested: bool,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let binding = context.binding(started_at)?;
        let snapshot = context.original.snapshot();
        let mut actual = LearningIterationCoordinatorV1::from_snapshot(dataset.snapshot().clone())?;
        if context.initial()? != material.initial
            || actual.snapshot().receipts.len() != 2
            || actual.next_stage() != Some(LearningIterationStageV1::Training)
        {
            return Err(Error::Binding(
                "same original Material before evaluated Selection",
            ));
        }
        for receipt in &snapshot.receipts[2..] {
            actual.record(receipt.clone(), receipt.observed_unix_seconds)?;
        }
        if actual.snapshot() != snapshot {
            return Err(Error::Binding(
                "exact original D/T/B evaluated Selection prefix",
            ));
        }
        peer.check_peer_lifetime()?;
        let fresh = OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            dataset, material,
        )
        .map_err(|_| Error::Binding("original Dataset custody before evaluated Selection"))?;
        require_clock(started_at, fresh)?;
        if context.binding(fresh)? != binding {
            return Err(Error::Binding(
                "unchanged original evaluated T/B signatures",
            ));
        }
        if !execution_requested {
            context.original.require_new_original_receipt(fresh)?;
        }
        peer.check_peer_lifetime()?;
        Ok(Self {
            channel: Mutex::new(Some(Channel {
                peer,
                next_request_id: 1,
                execution_requested,
            })),
            context,
            binding,
            retained: Mutex::new(None),
        })
    }
}
