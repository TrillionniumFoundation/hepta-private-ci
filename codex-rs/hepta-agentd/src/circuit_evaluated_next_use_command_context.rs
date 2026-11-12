//! Bind C only to the actual opaque S and actual D on an initially held
//! connection. No stream is recreated and no completed future cut is supplied.

use std::sync::Mutex;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_types::Digest32;

use super::Channel;
use super::Error;
use super::OriginalCircuitEvaluatedNextUseCommandClientV1;
use super::now;
use super::require_clock;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;
use crate::OriginalCircuitNextUseReceiptErrorV1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

pub(super) struct Context {
    pub(super) selection: OriginalCircuitEvaluatedSelectionReceiptV1,
}

impl Context {
    pub(super) fn from_original(
        selection: OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<Self, Error> {
        let value = Self { selection };
        value.authenticate(now()?)?;
        Ok(value)
    }

    pub(super) fn authenticate(&self, current: u64) -> Result<(), Error> {
        self.selection
            .original_receipt_predecessors(current)
            .map_err(OriginalCircuitNextUseReceiptErrorV1::from)?;
        Ok(())
    }

    pub(super) fn initial(&self) -> Result<LearningIterationSnapshotV1, Error> {
        let snapshot = self.selection.snapshot();
        Ok(
            LearningIterationCoordinatorV1::new(snapshot.request.clone(), snapshot.owners.clone())?
                .snapshot()
                .clone(),
        )
    }

    pub(super) fn binding(&self, current: u64) -> Result<Digest32, Error> {
        self.authenticate(current)?;
        Ok(Digest32::of_parts(&[
            b"hepta.agentd.original-circuit-evaluated-next-use-command.v1\0",
            &encode_original_owner_snapshot_v1(self.selection.snapshot())?,
            self.selection.original_receipt_binding().as_array(),
        ]))
    }
}

impl OriginalCircuitEvaluatedNextUseCommandClientV1 {
    pub(crate) fn bind_original_stage_channel(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<Self, Error> {
        selection
            .original_context()
            .require_new_original_receipt(now()?)?;
        Self::bind_stage_context(
            peer,
            material,
            dataset,
            Context::from_original(selection.clone())?,
            false,
        )
    }

    pub(crate) fn recover_original_stage_channel(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
    ) -> Result<Self, Error> {
        Self::bind_stage_context(
            peer,
            material,
            dataset,
            Context::from_original(selection.clone().into_original_receipt_readback())?,
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
        let (scope, verifier, _) = context.selection.original_context().receipt_configuration();
        let mut actual = LearningIterationCoordinatorV1::from_snapshot(dataset.snapshot().clone())?;
        if context.initial()? != material.initial
            || scope != material.scope
            || verifier.trust_digest() != material.verifier.trust_digest()
            || verifier.scope_digest() != material.verifier.scope_digest()
            || verifier.objective_digest() != material.verifier.objective_digest()
            || actual.snapshot().receipts.len() != 2
            || actual.next_stage() != Some(LearningIterationStageV1::Training)
        {
            return Err(Error::Binding("same original Material before evaluated C"));
        }
        for receipt in &context.selection.snapshot().receipts[2..] {
            actual.record(receipt.clone(), receipt.observed_unix_seconds)?;
        }
        if actual.snapshot() != context.selection.snapshot() {
            return Err(Error::Binding("exact original D/T/B/S evaluated C prefix"));
        }
        peer.check_peer_lifetime()?;
        let fresh = OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            dataset, material,
        )
        .map_err(|_| Error::Binding("original Dataset custody before evaluated C"))?;
        require_clock(started_at, fresh)?;
        if context.binding(fresh)? != binding {
            return Err(Error::Binding(
                "unchanged original evaluated T/B/S signatures",
            ));
        }
        if !execution_requested {
            context
                .selection
                .original_context()
                .require_new_original_receipt(fresh)?;
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
