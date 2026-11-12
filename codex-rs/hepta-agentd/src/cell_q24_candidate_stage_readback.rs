//! Readonly Candidate handoff from the same original Training continuation.
//! Retained identities are compared after actual I/O; they never replace it.

use std::sync::Arc;

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::Error;
use super::Origin;
use super::OriginalCellQ24CandidateStageOwnersV1;
use super::super::auth;
use crate::OriginalCellQ24CandidateMaterialV1;
use crate::OriginalCellQ24CandidateReadbackClientV1;
use crate::OriginalCellQ24CandidateReadbackErrorV1;
use crate::OriginalCellQ24TrainingCommandConnectionErrorV1;
use crate::OriginalCellQ24TrainingCommandConnectionV1;
use crate::RootResidentLearningEffectGateV3;

/// Dispatch is held only inside the fresh admitted Evaluation future.
/// Readback is an explicit non-effect path, never a fallback after Gate failure.
#[derive(Clone, Copy, Eq, PartialEq)]
pub(super) enum CandidateRead { Dispatch, Readback }

#[derive(Clone, Eq, PartialEq)]
struct CandidateIdentity {
    bundle: CellCompatibilityBundleV1,
    heads: Digest32,
    receipt: LearningIterationReceiptV1,
    attestation: SignedLearningEvidenceV1,
}

pub(super) struct CandidateLane {
    initial: Option<OriginalCellQ24TrainingCommandConnectionV1>,
    client: Option<OriginalCellQ24CandidateReadbackClientV1>,
    retained: Option<CandidateIdentity>,
    failed: bool,
}

impl CandidateLane {
    pub(super) fn new(initial: OriginalCellQ24TrainingCommandConnectionV1) -> Self {
        Self { initial: Some(initial), client: None, retained: None, failed: false }
    }
}

impl OriginalCellQ24CandidateStageOwnersV1 {
    pub(super) async fn read_original_candidate(
        &self, snapshot: &LearningIterationSnapshotV1, mode: CandidateRead,
    ) -> Result<OriginalCellQ24CandidateMaterialV1, Error> {
        let started_at = auth::now()?;
        self.require_live_deadline()?;
        auth::require_snapshot(&self.common.material, snapshot)?;
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        if snapshot.receipts.len() != 3
            || coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation)
            || snapshot.training_no_update_v2().is_some()
        {
            return Err(Error::WrongScope);
        }
        let expected_bundle = coordinator.candidate().ok_or(Error::WrongScope)?;
        if mode == CandidateRead::Dispatch && self.common.origin != Origin::Fresh {
            return Err(Error::WrongScope);
        }
        if mode == CandidateRead::Dispatch {
            let gate = self.common.root.as_ref()
                .ok_or(Error::OwnerUnavailable("fresh resident Candidate continuation"))?;
            RootResidentLearningEffectGateV3::require_current(
                gate, snapshot, &self.common.material.scope,
            ).await?;
        }
        // Always use one lock order and the original same-job owners. These
        // async ownership locks serialize work; no Ledger lock crosses I/O.
        let mut state = self.common.continuation.try_lock().map_err(|_| Error::QueueFull)?;
        let mut lane = self.candidate.try_lock().map_err(|_| Error::QueueFull)?;
        if lane.failed {
            return Err(Error::CommitUncertain);
        }
        // Cancellation or any failure after this point permanently fences this
        // instance. A new readonly recovery must contact the original owners.
        lane.failed = true;
        state.read_prefix(&self.common, snapshot).await?;
        let dataset = state.original_dataset.as_ref().ok_or(Error::CommitUncertain)?.clone();
        let training = state.original_training.as_ref().ok_or(Error::CommitUncertain)?.clone();
        if snapshot.receipts.get(2) != Some(training.receipt()) {
            return Err(Error::WrongScope);
        }
        if lane.client.is_none() {
            let initial = lane.initial.take().ok_or(Error::CommitUncertain)?;
            lane.client = Some(
                OriginalCellQ24TrainingCommandConnectionV1::bind_original_candidate_material(
                    initial, dataset, training.clone(), Arc::clone(&self.baseline),
                ).map_err(connection_failure)?,
            );
        }
        let client = lane.client.as_ref().ok_or(Error::CommitUncertain)?;
        let material = OriginalCellQ24CandidateReadbackClientV1::readback(client)
            .await.map_err(candidate_failure)?;
        if material.receipt() != training.receipt()
            || material.attestation() != training.attestation()
            || material.bundle() != expected_bundle
            || material.model().components() != &expected_bundle.components
            || material.authority() != AuthorityPosture::DENY_ALL
        {
            return Err(Error::WrongScope);
        }
        // Re-read all three original roles after every Candidate page. A saved
        // signature, successful earlier page, or retained model is not CURRENT.
        state.read_prefix(&self.common, snapshot).await?;
        if mode == CandidateRead::Dispatch {
            let gate = self.common.root.as_ref()
                .ok_or(Error::OwnerUnavailable("fresh resident Candidate continuation"))?;
            RootResidentLearningEffectGateV3::require_current(
                gate, snapshot, &self.common.material.scope,
            ).await?;
        }
        // The final original owner/Root I/O precedes all fresh window checks.
        let fresh = auth::require_material(
            &self.common.material, self.common.initial_binding,
        )?;
        auth::require_clock(started_at, fresh)?;
        auth::verify_prefix(&self.common.material, snapshot, &state, fresh)?;
        let current = state.original_training.as_ref().ok_or(Error::CommitUncertain)?;
        if material.receipt() != current.receipt()
            || material.attestation() != current.attestation()
        {
            return Err(Error::WrongScope);
        }
        auth::verify_receipt(
            &self.common.material, material.receipt(), material.attestation(), fresh,
        )?;
        self.require_live_deadline()?;
        let identity = CandidateIdentity {
            bundle: material.bundle().clone(),
            heads: Digest32::of_bytes(material.heads()),
            receipt: material.receipt().clone(),
            attestation: material.attestation().clone(),
        };
        if lane.retained.as_ref().is_some_and(|prior| prior != &identity) {
            return Err(Error::WrongScope);
        }
        lane.retained = Some(identity);
        lane.failed = false;
        Ok(material)
    }
}

fn connection_failure(error: OriginalCellQ24TrainingCommandConnectionErrorV1) -> Error {
    match error {
        OriginalCellQ24TrainingCommandConnectionErrorV1::Binding(_) => Error::WrongScope,
        OriginalCellQ24TrainingCommandConnectionErrorV1::Command(error) => auth::trainer_failure(error),
        OriginalCellQ24TrainingCommandConnectionErrorV1::Material(error) => auth::material_failure(error),
        OriginalCellQ24TrainingCommandConnectionErrorV1::Candidate(error) => candidate_failure(error),
    }
}

fn candidate_failure(error: OriginalCellQ24CandidateReadbackErrorV1) -> Error {
    match error {
        OriginalCellQ24CandidateReadbackErrorV1::Command(error) => auth::trainer_failure(error),
        OriginalCellQ24CandidateReadbackErrorV1::Context(error) => auth::material_failure(error),
        OriginalCellQ24CandidateReadbackErrorV1::Binding(_)
        | OriginalCellQ24CandidateReadbackErrorV1::NoCandidate
        | OriginalCellQ24CandidateReadbackErrorV1::Material(_) => Error::WrongScope,
        OriginalCellQ24CandidateReadbackErrorV1::Unavailable =>
            Error::OwnerUnavailable("original Candidate material"),
    }
}
