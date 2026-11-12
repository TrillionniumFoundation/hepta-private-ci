//! Concrete ordinary Candidate branch on the same original E/D/T owners.
//!
//! Evaluation uses its initially delivered original host connection. That host
//! must retain the actual independent B/retention owners and original Evaluator
//! receipt capability. Candidate bytes remain readonly material; neither this
//! route nor an Evaluation receipt supplies adoption or FinalUse rights. The
//! separately delivered original Model connection is the only Proposal path.

use std::sync::Arc;
use std::time::Instant;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

use super::Error;
use super::Origin;
use super::OriginalCellQ24NoUpdatePeerStreamV1;
use super::OriginalCellQ24NoUpdateStageOwnersV1;
use super::OriginalCellQ24NoUpdateStageStreamsV1;
use super::lane::ResidentLane;
use crate::LearningIterationOwnerFutureV1;
use crate::LearningIterationStageOwnerPortsV1;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::PreparedLearningIterationProposalV1;
use crate::RootResidentLearningEffectGateV3;

#[path = "cell_q24_candidate_stage_inputs.rs"]
mod inputs;
#[path = "cell_q24_candidate_stage_readback.rs"]
mod readback;
use readback::CandidateLane;
use readback::CandidateRead;
#[path = "cell_q24_candidate_stage_evaluation.rs"]
mod evaluation;
use evaluation::EvaluationLane;
#[path = "cell_q24_candidate_stage_model.rs"]
mod model;
use model::ModelLane;
#[path = "cell_q24_candidate_stage_retention.rs"]
pub(super) mod retention;
use retention::EvaluatedLane;

/// All endpoints are original connected streams delivered at the same initial
/// handoff. There is no future Training receipt, B result, panel or model DTO.
pub struct OriginalCellQ24CandidateStageStreamsV1 {
    pub common: OriginalCellQ24NoUpdateStageStreamsV1,
    pub candidate_material: OriginalCellQ24NoUpdatePeerStreamV1,
    pub evaluator: OriginalCellQ24NoUpdatePeerStreamV1,
    pub model: OriginalCellQ24NoUpdatePeerStreamV1,
}

/// Root consumes this value. No Clone, owner getter, callback, key or mutable
/// future-result slot escapes the same private common continuation.
pub struct OriginalCellQ24CandidateStageOwnersV1 {
    common: OriginalCellQ24NoUpdateStageOwnersV1,
    protocol: OriginalCellEvaluationPanelRegistrationV1,
    baseline: Arc<LoadedCellQ24ModelV1>,
    candidate: ResidentLane<CandidateLane>,
    evaluation: ResidentLane<EvaluationLane>,
    model: ResidentLane<ModelLane>,
    retention: ResidentLane<EvaluatedLane>,
    end: Instant,
}

impl OriginalCellQ24CandidateStageOwnersV1 {
    pub fn from_original_streams(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        streams: OriginalCellQ24CandidateStageStreamsV1,
        protocol: OriginalCellEvaluationPanelRegistrationV1,
        baseline: Arc<LoadedCellQ24ModelV1>,
    ) -> Result<Self, Error> {
        inputs::bind(material, streams, protocol, baseline, Origin::Fresh)
    }

    pub fn recover_original_streams(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        streams: OriginalCellQ24CandidateStageStreamsV1,
        protocol: OriginalCellEvaluationPanelRegistrationV1,
        baseline: Arc<LoadedCellQ24ModelV1>,
    ) -> Result<Self, Error> {
        inputs::bind(material, streams, protocol, baseline, Origin::Recovered)
    }

    pub(crate) fn require_initial(
        &self,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        verifier: &LearningEvidenceVerifierV1,
    ) -> Result<(), Error> {
        OriginalCellQ24NoUpdateStageOwnersV1::require_initial(
            &self.common,
            initial,
            scope,
            verifier,
        )?;
        if initial.request.evaluation_profile != self.protocol.evaluation_profile()
            || self.baseline.components() != &initial.request.selected_bundle.components
            || Instant::now() >= self.end
        {
            return Err(Error::WrongScope);
        }
        Ok(())
    }

    fn require_live_deadline(&self) -> Result<(), Error> {
        if Instant::now() >= self.end {
            return Err(Error::DeadlineExceeded);
        }
        Ok(())
    }

    pub(crate) fn install_fresh_resident_gate(
        &mut self,
        gate: Arc<RootResidentLearningEffectGateV3>,
    ) -> Result<(), Error> {
        OriginalCellQ24NoUpdateStageOwnersV1::install_fresh_resident_gate(&mut self.common, gate)
    }
}

impl LearningIterationStageOwnerPortsV1 for OriginalCellQ24CandidateStageOwnersV1 {
    fn validate_recovery<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, ()> {
        Box::pin(async move {
            tokio::time::timeout_at(self.end.into(), async {
                self.require_live_deadline()?;
                let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
                if coordinator.candidate().is_some() && retention::is_evaluated_retention(snapshot) {
                    self.read_original_evaluated_retention(snapshot).await
                } else if coordinator.candidate().is_some() && snapshot.receipts.len() == 5 {
                    OriginalCellQ24CandidateStageOwnersV1::read_original_model(self, snapshot).await?;
                    Ok(())
                } else if coordinator.candidate().is_some() && snapshot.receipts.len() >= 4 {
                    // This is original readback, including while the fresh
                    // Root future still has the three-cut Evaluation intent.
                    // It never asks that gate to accept the future fourth cut.
                    self.read_original_evaluation(snapshot).await?;
                    if snapshot.receipts.len() != 4 {
                        return Err(Error::OwnerUnavailable(
                            "original post-Evaluation Model and adoption readback capabilities are required",
                        ));
                    }
                    Ok(())
                } else if self.common.origin == Origin::Recovered
                    && snapshot.receipts.len() == 3 && coordinator.candidate().is_some()
                {
                    OriginalCellQ24CandidateStageOwnersV1::read_original_candidate(
                        self, snapshot, CandidateRead::Readback,
                    ).await?;
                    Ok(())
                } else {
                    // Fresh T attestation precedes Root's T checkpoint: do not
                    // invent an Evaluation dispatch to validate that third cut.
                    LearningIterationStageOwnerPortsV1::validate_recovery(&self.common, snapshot).await
                }
            }).await.map_err(|_| Error::CommitUncertain)?
        })
    }

    fn execute_stage<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        stage: Stage,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        Box::pin(async move {
            tokio::time::timeout_at(self.end.into(), async {
                self.require_live_deadline()?;
                if stage == Stage::Evaluation {
                    if self.common.origin != Origin::Fresh {
                        return Err(Error::WrongScope);
                    }
                    return self.execute_original_evaluation(snapshot).await;
                }
                if stage == Stage::Proposal {
                    return self.execute_original_model(snapshot).await;
                }
                if matches!(stage, Stage::Selection | Stage::NextUse)
                    && retention::is_evaluated_retention(snapshot)
                {
                    return self.execute_original_evaluated_retention(snapshot, stage).await;
                }
                // Training NoUpdate keeps its original three-cut route. A
                // qualified Candidate still needs Model and adoption custody.
                if matches!(stage, Stage::Selection | Stage::NextUse)
                    && snapshot.training_no_update_v2().is_none()
                {
                    return Err(Error::OwnerUnavailable(
                        "original Candidate Model, Selector, version and FinalUse capabilities are required",
                    ));
                }
                LearningIterationStageOwnerPortsV1::execute_stage(&self.common, snapshot, stage).await
            }).await.map_err(|_| Error::CommitUncertain)?
        })
    }

    fn prepare_proposal<'a>(
        &'a self,
        _snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        Box::pin(async {
            Err(Error::OwnerUnavailable(
                "original evaluated Model and independent adoption capabilities are required",
            ))
        })
    }

    fn receipt_attestation<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        receipt: &'a LearningIterationReceiptV1,
        now_unix_seconds: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        Box::pin(async move {
            tokio::time::timeout_at(self.end.into(), async {
                self.require_live_deadline()?;
                let coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
                if coordinator.candidate().is_some() && snapshot.receipts.len() >= 3 {
                    let training = self.training_prefix(snapshot)?;
                    if receipt.observation.stage() == Stage::Evaluation {
                        let original = self.read_original_evaluation(snapshot).await?;
                        if original.receipt() != receipt {
                            return Err(Error::WrongScope);
                        }
                        return Ok(original.attestation().clone());
                    }
                    if matches!(receipt.observation.stage(), Stage::Experience | Stage::Dataset | Stage::Training) {
                        return LearningIterationStageOwnerPortsV1::receipt_attestation(
                            &self.common, &training, receipt, now_unix_seconds,
                        ).await;
                    }
                    if retention::is_evaluated_retention(snapshot)
                        && matches!(receipt.observation.stage(), Stage::Selection | Stage::NextUse)
                    {
                        return self.evaluated_retention_attestation(snapshot, receipt).await;
                    }
                    return Err(Error::OwnerUnavailable(
                        "original Candidate Model and adoption attestation capabilities are required",
                    ));
                }
                LearningIterationStageOwnerPortsV1::receipt_attestation(
                    &self.common, snapshot, receipt, now_unix_seconds,
                ).await
            }).await.map_err(|_| Error::CommitUncertain)?
        })
    }
}

#[cfg(test)]
pub(crate) fn fixture_from_original_clients(
    mut common: OriginalCellQ24NoUpdateStageOwnersV1,
    protocol: OriginalCellEvaluationPanelRegistrationV1,
    baseline: Arc<LoadedCellQ24ModelV1>,
    initial: crate::OriginalCellQ24TrainingCommandConnectionV1,
    end: Instant,
) -> Result<OriginalCellQ24CandidateStageOwnersV1, Error> {
    let end = end.min(common.end);
    common.end = end;
    let owners = OriginalCellQ24CandidateStageOwnersV1 {
        common,
        protocol,
        baseline,
        candidate: ResidentLane::new(CandidateLane::new(initial)),
        evaluation: ResidentLane::new(EvaluationLane::fixture_unavailable()),
        model: ResidentLane::new(ModelLane::fixture_unavailable()),
        retention: ResidentLane::new(EvaluatedLane::new()),
        end,
    };
    owners.require_initial(
        &owners.common.material.initial,
        &owners.common.material.scope,
        &owners.common.material.verifier,
    )?;
    Ok(owners)
}
