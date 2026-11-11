//! Local checks after original I/O. Complete retained signatures are immutable
//! identity pins; their original issuance/expiry are verified at a fresh clock.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1 as Role;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::Digest32;

use super::Error;
use super::state::Continuation;
use crate::OriginalCellQ24MaterialReceiptConfigV1 as Material;

pub(super) fn now() -> Result<u64, Error> {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|value| value.as_secs())
        .map_err(|_| Error::WrongScope)
}

pub(super) fn require_clock(started_at: u64, current: u64) -> Result<(), Error> {
    if current < started_at { return Err(Error::WrongScope); }
    Ok(())
}

pub(super) fn require_material(material: &Material, binding: Digest32) -> Result<u64, Error> {
    let (actual, current) = Material::require_original_command_initial(material)
        .map_err(|_| Error::WrongScope)?;
    if actual != binding { return Err(Error::WrongScope); }
    Ok(current)
}

pub(super) fn require_snapshot(material: &Material, snapshot: &LearningIterationSnapshotV1)
    -> Result<(), Error>
{
    LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
    material.scope.validate_snapshot(snapshot)?;
    if snapshot.request != material.initial.request || snapshot.owners != material.initial.owners
        || snapshot.receipts.len() > 5
    {
        return Err(Error::WrongScope);
    }
    for (index, receipt) in snapshot.receipts.iter().enumerate() {
        if stage_index(receipt.observation.stage())? != index {
            return Err(Error::WrongScope);
        }
    }
    Ok(())
}

pub(super) fn stage_index(stage: Stage) -> Result<usize, Error> {
    match stage {
        Stage::Experience => Ok(0),
        Stage::Dataset => Ok(1),
        Stage::Training => Ok(2),
        Stage::Selection => Ok(3),
        Stage::NextUse => Ok(4),
        Stage::Evaluation | Stage::Proposal =>
            Err(Error::OwnerUnavailable("NoUpdate assembly has no Candidate authority")),
    }
}

pub(super) fn require_receipt_position(
    snapshot: &LearningIterationSnapshotV1, receipt: &LearningIterationReceiptV1,
) -> Result<(), Error> {
    let index = stage_index(receipt.observation.stage())?;
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
    if let Some(original) = snapshot.receipts.get(index) {
        if original != receipt { return Err(Error::WrongScope); }
    } else {
        if index != snapshot.receipts.len()
            || coordinator.next_stage() != Some(receipt.observation.stage())
        {
            return Err(Error::WrongScope);
        }
        coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
    }
    Ok(())
}

pub(super) fn verify_receipt(
    material: &Material, receipt: &LearningIterationReceiptV1,
    signature: &SignedLearningEvidenceV1, at: u64,
) -> Result<VerifiedLearningEvidenceV1, Error> {
    let stage = receipt.observation.stage();
    let role = match stage {
        Stage::Experience | Stage::Dataset | Stage::NextUse => Role::Observer,
        Stage::Training => Role::Generator,
        Stage::Selection => Role::Selector,
        Stage::Evaluation | Stage::Proposal =>
            return Err(Error::OwnerUnavailable("NoUpdate assembly has no Candidate authority")),
    };
    if &receipt.actor_id != material.initial.owners.owner(stage)
        || receipt.observed_unix_seconds != signature.issued_at
        || receipt.observed_unix_seconds > at
    {
        return Err(Error::WrongScope);
    }
    let actual = material.verifier.verify(
        role, signature, &learning_iteration_receipt_signing_bytes_v1(receipt)?, at,
    ).map_err(Error::Evidence)?;
    if actual.principal().principal_id != receipt.actor_id
        || actual.trust_digest() != material.initial.owners.evidence_trust_digest
        || actual.objective_digest() != material.initial.request.envelope.objective_digest
    {
        return Err(Error::WrongScope);
    }
    Ok(actual)
}

pub(super) fn verify_prefix(
    material: &Material, snapshot: &LearningIterationSnapshotV1,
    state: &Continuation, at: u64,
) -> Result<(), Error> {
    require_snapshot(material, snapshot)?;
    if state.records.len() < snapshot.receipts.len() { return Err(Error::CommitUncertain); }
    let mut verified = Vec::with_capacity(snapshot.receipts.len());
    for (receipt, original) in snapshot.receipts.iter().zip(&state.records) {
        if receipt != &original.0 { return Err(Error::WrongScope); }
        verified.push(verify_receipt(material, receipt, &original.1, at)?);
    }
    if verified.len() >= 4 {
        verify_signed_actor_separation(&verified[2], &verified[3], at).map_err(Error::Evidence)?;
    }
    if verified.len() == 5 {
        verify_signed_actor_separation(&verified[2], &verified[4], at).map_err(Error::Evidence)?;
        verify_signed_actor_separation(&verified[3], &verified[4], at).map_err(Error::Evidence)?;
    }
    Ok(())
}

pub(super) fn material_failure(error: crate::OriginalCellQ24MaterialCommandErrorV1) -> Error {
    use crate::OriginalCellQ24MaterialCommandErrorV1 as Source;
    match error {
        Source::Missing | Source::Pending | Source::ReadbackRequired | Source::CommitUncertain =>
            Error::CommitUncertain,
        Source::DeadlineExceeded => Error::DeadlineExceeded,
        Source::Busy => Error::QueueFull,
        Source::Evidence(error) => Error::Evidence(error),
        Source::Binding(_) | Source::Iteration(_) | Source::Checkpoint(_) | Source::Encoding(_) =>
            Error::WrongScope,
        Source::Unavailable | Source::Transport(_) | Source::Material(_) | Source::Dataset(_) =>
            Error::OwnerUnavailable("original Material stage"),
    }
}

pub(super) fn trainer_failure(error: crate::OriginalCellQ24TrainingCommandErrorV1) -> Error {
    use crate::OriginalCellQ24TrainingCommandErrorV1 as Source;
    match error {
        Source::Missing | Source::Pending | Source::ReadbackRequired | Source::CommitUncertain
        | Source::Cancelled => Error::CommitUncertain,
        Source::DeadlineExceeded => Error::DeadlineExceeded,
        Source::Busy => Error::QueueFull,
        Source::Evidence(error) => Error::Evidence(error),
        Source::Binding(_) | Source::Iteration(_) | Source::Checkpoint(_) | Source::Encoding(_) =>
            Error::WrongScope,
        Source::Unavailable | Source::Transport(_) | Source::Stage(_) =>
            Error::OwnerUnavailable("original Trainer stage"),
    }
}

pub(super) fn selector_failure(error: crate::OriginalCircuitSelectionCommandErrorV1) -> Error {
    use crate::OriginalCircuitSelectionCommandErrorV1 as Source;
    match error {
        Source::Missing | Source::Pending | Source::ReadbackRequired | Source::CommitUncertain =>
            Error::CommitUncertain,
        Source::DeadlineExceeded => Error::DeadlineExceeded,
        Source::Busy => Error::QueueFull,
        Source::Evidence(error) => Error::Evidence(error),
        Source::Binding(_) | Source::Iteration(_) | Source::Checkpoint(_) | Source::Encoding(_) =>
            Error::WrongScope,
        Source::Unavailable | Source::Transport(_) | Source::Owner(_) =>
            Error::OwnerUnavailable("original Selector stage"),
    }
}

pub(super) fn next_use_failure(error: crate::OriginalCircuitNextUseCommandErrorV1) -> Error {
    use crate::OriginalCircuitNextUseCommandErrorV1 as Source;
    match error {
        Source::Missing | Source::Pending | Source::ReadbackRequired | Source::CommitUncertain =>
            Error::CommitUncertain,
        Source::DeadlineExceeded => Error::DeadlineExceeded,
        Source::Busy => Error::QueueFull,
        Source::Evidence(error) => Error::Evidence(error),
        Source::Binding(_) | Source::Iteration(_) | Source::Checkpoint(_) | Source::Encoding(_) =>
            Error::WrongScope,
        Source::Unavailable | Source::Transport(_) | Source::Owner(_) =>
            Error::OwnerUnavailable("original completed-C Observer"),
    }
}
