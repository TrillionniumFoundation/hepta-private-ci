//! Final complete signature checks follow all original I/O. Saved pins compare
//! identities only; neither a receipt nor a context stands in for CURRENT.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;

use super::Error;
use super::Owners;
use super::Predecessors;
use super::ReceiptPin;
use crate::OriginalCircuitEvaluatedNextUseReceiptV1;
use crate::OriginalCircuitEvaluatedRetentionContextV1;
use crate::OriginalCircuitEvaluatedSelectionReceiptV1;

pub(super) fn same_selection(
    first: &OriginalCircuitEvaluatedSelectionReceiptV1,
    second: &OriginalCircuitEvaluatedSelectionReceiptV1,
) -> bool {
    first.snapshot() == second.snapshot()
        && first.receipt() == second.receipt()
        && first.attestation() == second.attestation()
        && first.original_context().receipt_context_binding()
            == second.original_context().receipt_context_binding()
}

pub(super) fn completion_pin(original: &OriginalCircuitEvaluatedNextUseReceiptV1) -> ReceiptPin {
    ReceiptPin {
        snapshot: original.snapshot().clone(),
        receipt: original.receipt().clone(),
        signature: original.attestation().clone(),
        selection_binding: original.original_selection().original_receipt_binding(),
    }
}

impl Owners {
    pub(super) fn verify_evaluated_selection(
        &self,
        supplied: &LearningIterationSnapshotV1,
        predecessors: &Predecessors,
        original: &OriginalCircuitEvaluatedSelectionReceiptV1,
        fresh: u64,
    ) -> Result<(), Error> {
        let expected = OriginalCircuitEvaluatedRetentionContextV1::recover_original_evaluation(
            self.common.material.scope.clone(),
            self.common.material.verifier.clone(),
            &predecessors.training,
            &predecessors.evaluation,
        )
        .map_err(|_| Error::WrongScope)?;
        if original.original_context().receipt_context_binding()
            != expected.receipt_context_binding()
            || original.original_context().snapshot() != predecessors.evaluation.snapshot()
            || original.snapshot().receipts.len() != 5
            || supplied
                .receipts
                .get(4)
                .is_some_and(|receipt| receipt != original.receipt())
        {
            return Err(Error::WrongScope);
        }
        let mut coordinator =
            LearningIterationCoordinatorV1::from_snapshot(expected.snapshot().clone())?;
        coordinator.record(
            original.receipt().clone(),
            original.receipt().observed_unix_seconds,
        )?;
        if coordinator.snapshot() != original.snapshot()
            || coordinator.next_stage() != Some(Stage::NextUse)
        {
            return Err(Error::WrongScope);
        }
        self.common
            .material
            .scope
            .validate_snapshot(original.snapshot())?;
        let verified = self.verify_evaluated_retention_signature(
            original.receipt(),
            original.attestation(),
            fresh,
        )?;
        for predecessor in original
            .original_context()
            .original_receipt_predecessors(fresh)
            .map_err(|_| Error::WrongScope)?
        {
            verify_signed_actor_separation(&predecessor, &verified, fresh)
                .map_err(Error::Evidence)?;
        }
        original
            .original_receipt_predecessors(fresh)
            .map_err(|_| Error::WrongScope)?;
        Ok(())
    }

    pub(super) fn verify_evaluated_next_use(
        &self,
        supplied: &LearningIterationSnapshotV1,
        predecessors: &Predecessors,
        selection: &OriginalCircuitEvaluatedSelectionReceiptV1,
        original: &OriginalCircuitEvaluatedNextUseReceiptV1,
        fresh: u64,
    ) -> Result<(), Error> {
        self.verify_evaluated_selection(supplied, predecessors, selection, fresh)?;
        if !same_selection(selection, original.original_selection())
            || original.snapshot().receipts.len() != 6
            || supplied
                .receipts
                .get(5)
                .is_some_and(|receipt| receipt != original.receipt())
        {
            return Err(Error::WrongScope);
        }
        let mut coordinator =
            LearningIterationCoordinatorV1::from_snapshot(selection.snapshot().clone())?;
        coordinator.record(
            original.receipt().clone(),
            original.receipt().observed_unix_seconds,
        )?;
        if coordinator.snapshot() != original.snapshot() || coordinator.next_stage().is_some() {
            return Err(Error::WrongScope);
        }
        self.common
            .material
            .scope
            .validate_snapshot(original.snapshot())?;
        let verified = self.verify_evaluated_retention_signature(
            original.receipt(),
            original.attestation(),
            fresh,
        )?;
        for predecessor in selection
            .original_receipt_predecessors(fresh)
            .map_err(|_| Error::WrongScope)?
        {
            verify_signed_actor_separation(&predecessor, &verified, fresh)
                .map_err(Error::Evidence)?;
        }
        Ok(())
    }

    fn verify_evaluated_retention_signature(
        &self,
        receipt: &LearningIterationReceiptV1,
        signature: &SignedLearningEvidenceV1,
        fresh: u64,
    ) -> Result<VerifiedLearningEvidenceV1, Error> {
        let role = match receipt.observation.stage() {
            Stage::Selection => LearningEvidenceRoleV1::Selector,
            Stage::NextUse => LearningEvidenceRoleV1::Observer,
            _ => return Err(Error::WrongScope),
        };
        if receipt.operation_id != self.common.material.initial.request.operation_id
            || &receipt.actor_id
                != self
                    .common
                    .material
                    .initial
                    .owners
                    .owner(receipt.observation.stage())
            || receipt.observed_unix_seconds > signature.issued_at
            || signature.issued_at > fresh
        {
            return Err(Error::WrongScope);
        }
        let verified = self
            .common
            .material
            .verifier
            .verify(
                role,
                signature,
                &learning_iteration_receipt_signing_bytes_v1(receipt)?,
                fresh,
            )
            .map_err(Error::Evidence)?;
        if verified.principal().principal_id != receipt.actor_id
            || verified.trust_digest() != self.common.material.initial.owners.evidence_trust_digest
            || verified.objective_digest()
                != self
                    .common
                    .material
                    .initial
                    .request
                    .envelope
                    .objective_digest
        {
            return Err(Error::WrongScope);
        }
        Ok(verified)
    }
}
