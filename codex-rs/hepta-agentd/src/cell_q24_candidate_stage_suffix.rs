//! Independently signed S/C extend the fixed original five-cut Model proof.
//! These checks run again when Root consumes the same opaque continuation,
//! after its last actual read. No suffix is folded into Model's four signatures.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;

use super::Error;
use super::OriginalCandidateOperationEvidence;
use super::OriginalCellQ24ModelCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;

impl OriginalCandidateOperationEvidence<'_> {
    pub(super) fn authenticate_original_suffix(
        &self,
        model: &OriginalCellQ24ModelCommandReceiptV1,
        signatures: &mut Vec<SignedLearningEvidenceV1>,
        now: u64,
    ) -> Result<(), Error> {
        if signatures.len() != 4 {
            return Err(Error::WrongScope);
        }
        let Some(selection) = &self.selection else {
            if self.next_use.is_some() || self.publication.is_some() || self.completion_read.is_some()
                || &self.snapshot != model.snapshot() {
                return Err(Error::WrongScope);
            }
            return Ok(());
        };
        let operation = &self.operation.0;
        let material = &operation.owners.common.material;
        let context = selection.original_publication_context();
        let publication = self.publication.as_ref().ok_or(Error::WrongScope)?;
        let mut selected = LearningIterationCoordinatorV1::from_snapshot(model.snapshot().clone())?;
        selected.record(selection.receipt().clone(), selection.receipt().observed_unix_seconds)?;
        if selection.model() != model
            || context.model() != model
            || context.decision() != model.snapshot()
            || context.original_predecessors().as_slice() != signatures.as_slice()
            || context.scope() != &material.scope
            || context.verifier().trust_digest() != material.verifier.trust_digest()
            || context.verifier().scope_digest() != material.verifier.scope_digest()
            || context.verifier().objective_digest() != material.verifier.objective_digest()
            || selection.snapshot() != selected.snapshot()
            || selection.snapshot().receipts.len() != 6
            || selected.next_stage() != Some(Stage::NextUse)
            || publication.authority() != AuthorityPosture::DENY_ALL
            || !matches!(&selection.receipt().observation,
                LearningIterationObservationV1::Selection { candidate_bundle, selection_digest }
                if *candidate_bundle == publication.bundle_digest()
                    && *selection_digest == publication.selection_digest())
            || publication.run_id() == &self.snapshot.request.source_run_id
            || selection.receipt().observation.stage() != Stage::Selection
            || self.snapshot.receipts.get(..6) != Some(selection.snapshot().receipts.as_slice())
            || operation.supplied.receipts.get(5).is_some_and(|saved| saved != selection.receipt())
        {
            return Err(Error::WrongScope);
        }
        material.scope.validate_snapshot(selection.snapshot())?;
        let predecessors = context.authenticate(now).map_err(|_| Error::WrongScope)?;
        if predecessors.len() != 2 { return Err(Error::WrongScope); }
        let generator = predecessors.first().ok_or(Error::WrongScope)?;
        let evaluator = predecessors.get(1).ok_or(Error::WrongScope)?;
        let selector = verify_original_role(
            material, selection.receipt(), selection.attestation(),
            LearningEvidenceRoleV1::Selector, now,
        )?;
        verify_signed_actor_separation(generator, &selector, now).map_err(Error::Evidence)?;
        verify_signed_actor_separation(evaluator, &selector, now).map_err(Error::Evidence)?;
        signatures.push(selection.attestation().clone());
        let Some(next_use) = &self.next_use else {
            if self.completion_read.is_some() || &self.snapshot != selection.snapshot() {
                return Err(Error::WrongScope);
            }
            return Ok(());
        };
        let completed = self.completion_read.as_ref().ok_or(Error::WrongScope)?;
        selected.record(next_use.receipt().clone(), next_use.receipt().observed_unix_seconds)?;
        if next_use.model() != model
            || next_use.training_attestation() != operation.training.attestation()
            || next_use.selection_attestation() != selection.attestation()
            || next_use.snapshot() != selected.snapshot()
            || next_use.snapshot() != &self.snapshot
            || next_use.snapshot().receipts.len() != 7
            || selected.next_stage().is_some()
            || completed.observation() != &next_use.receipt().observation
            || completed.publication_digest() != publication.publication_digest()
            || completed.source_input_digest() != publication.task_digest()
            || completed.source_publication_digest().is_none()
            || !matches!(&next_use.receipt().observation,
                LearningIterationObservationV1::NextUse {
                    candidate_bundle, state_partition, selection_digest, ..
                } if *candidate_bundle == publication.bundle_digest()
                    && *selection_digest == publication.selection_digest()
                    && &state_partition.run_id == publication.run_id())
            || next_use.receipt().observation.stage() != Stage::NextUse
            || operation.supplied.receipts.get(6).is_some_and(|saved| saved != next_use.receipt())
        {
            return Err(Error::WrongScope);
        }
        material.scope.validate_snapshot(next_use.snapshot())?;
        let observer = verify_original_role(
            material, next_use.receipt(), next_use.attestation(),
            LearningEvidenceRoleV1::Observer, now,
        )?;
        verify_signed_actor_separation(generator, &observer, now).map_err(Error::Evidence)?;
        verify_signed_actor_separation(evaluator, &observer, now).map_err(Error::Evidence)?;
        verify_signed_actor_separation(&selector, &observer, now).map_err(Error::Evidence)?;
        signatures.push(next_use.attestation().clone());
        Ok(())
    }
}

fn verify_original_role(
    material: &OriginalCellQ24MaterialReceiptConfigV1,
    receipt: &LearningIterationReceiptV1,
    signature: &SignedLearningEvidenceV1,
    role: LearningEvidenceRoleV1,
    now: u64,
) -> Result<VerifiedLearningEvidenceV1, Error> {
    if &receipt.actor_id != material.initial.owners.owner(receipt.observation.stage())
        || receipt.operation_id != material.initial.request.operation_id
        || receipt.observed_unix_seconds > signature.issued_at
        || signature.issued_at > now
    {
        return Err(Error::WrongScope);
    }
    let evidence = material.verifier.verify(
        role, signature, &learning_iteration_receipt_signing_bytes_v1(receipt)?, now,
    ).map_err(Error::Evidence)?;
    if evidence.principal().principal_id != receipt.actor_id
        || evidence.trust_digest() != material.initial.owners.evidence_trust_digest
        || evidence.objective_digest() != material.initial.request.envelope.objective_digest
    {
        return Err(Error::WrongScope);
    }
    Ok(evidence)
}
