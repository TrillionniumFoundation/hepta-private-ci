//! Bounded owner observations for the learning-iteration profile.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CellCompatibilityBundleV1;
use crate::CellStatePartitionV1;
use crate::IterationEnvelopeV1;

/// Explicit learning quotas, separate from foreground reservations.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningIterationBudgetV1 {
    pub maximum_dataset_rows: u32,
    pub maximum_dataset_bytes: u64,
    pub maximum_training_steps: u64,
    pub maximum_training_milliseconds: u64,
    pub maximum_artifact_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningIterationRequestV1 {
    /// Reused unchanged after timeout or uncertain owner commit.
    pub operation_id: StableId,
    pub principal_id: StableId,
    pub agent_id: StableId,
    pub cell_id: StableId,
    pub source_run_id: StableId,
    pub completed_task_receipt: Digest32,
    /// The content pin used by the existing artifact/plasticity owner.
    pub selected_artifact_digest: Digest32,
    pub selected_bundle: CellCompatibilityBundleV1,
    pub envelope: IterationEnvelopeV1,
    pub budget: LearningIterationBudgetV1,
}

/// Host-owned identity and trust pins, never chosen by a model response.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningIterationOwnersV1 {
    pub evidence_trust_digest: Digest32,
    pub experience: StableId,
    pub dataset: StableId,
    pub trainer: StableId,
    pub evaluator: StableId,
    pub proposal: StableId,
    pub selector: StableId,
    pub next_use_observer: StableId,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningIterationStageV1 {
    Experience,
    Dataset,
    Training,
    Evaluation,
    Proposal,
    Selection,
    NextUse,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningEvaluationDispositionV1 {
    Qualified,
    NoUpdate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningProposalDispositionV1 {
    UpdateCandidates,
    NoAdmissibleUpdate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningIterationObservationV1 {
    Experience {
        episode_digest: Digest32,
        completed_task_receipt: Digest32,
    },
    Dataset {
        snapshot_digest: Digest32,
        episode_digest: Digest32,
        withdrawal_frontier: Digest32,
        rows: u32,
        bytes: u64,
    },
    Training {
        candidate: Box<CellCompatibilityBundleV1>,
        steps: u64,
        milliseconds: u64,
        artifact_bytes: u64,
    },
    Evaluation {
        candidate_bundle: Digest32,
        evaluation_profile: Digest32,
        disposition: LearningEvaluationDispositionV1,
    },
    /// Only after acknowledgement from the existing anchored proposal owner.
    Proposal {
        candidate_bundle: Digest32,
        proposal_id: StableId,
        composition_digest: Digest32,
        disposition: LearningProposalDispositionV1,
    },
    /// A read-only observation of an independently authorized selection.
    /// After NoUpdate, candidate_bundle is the unchanged deployed bundle.
    Selection {
        candidate_bundle: Digest32,
        selection_digest: Digest32,
    },
    /// Actual committed use by another task, in the same principal/agent/cell.
    NextUse {
        candidate_bundle: Digest32,
        state_partition: CellStatePartitionV1,
        checkpoint_digest: Digest32,
        selection_digest: Digest32,
        committed_step_receipt: Digest32,
        state_cutover_receipt: Digest32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningIterationReceiptV1 {
    pub operation_id: StableId,
    pub predecessor: Digest32,
    pub actor_id: StableId,
    /// Authenticated owner result, covering the full observation.
    pub evidence_digest: Digest32,
    pub observed_unix_seconds: u64,
    pub observation: LearningIterationObservationV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningIterationSnapshotV1 {
    pub request: LearningIterationRequestV1,
    pub owners: LearningIterationOwnersV1,
    pub receipts: Vec<LearningIterationReceiptV1>,
    pub head_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningIterationDispositionV1 {
    InProgress,
    /// The evaluated decision retains the deployed bundle. Selection and
    /// next-task use remain outstanding until next_stage returns None.
    NoUpdate,
    /// Only a committed NextUse observation completes either decision path.
    UsedByNextTask,
}

impl LearningIterationObservationV1 {
    pub const fn stage(&self) -> LearningIterationStageV1 {
        match self {
            Self::Experience { .. } => LearningIterationStageV1::Experience,
            Self::Dataset { .. } => LearningIterationStageV1::Dataset,
            Self::Training { .. } => LearningIterationStageV1::Training,
            Self::Evaluation { .. } => LearningIterationStageV1::Evaluation,
            Self::Proposal { .. } => LearningIterationStageV1::Proposal,
            Self::Selection { .. } => LearningIterationStageV1::Selection,
            Self::NextUse { .. } => LearningIterationStageV1::NextUse,
        }
    }
}

impl LearningIterationOwnersV1 {
    pub fn owner(&self, stage: LearningIterationStageV1) -> &StableId {
        match stage {
            LearningIterationStageV1::Experience => &self.experience,
            LearningIterationStageV1::Dataset => &self.dataset,
            LearningIterationStageV1::Training => &self.trainer,
            LearningIterationStageV1::Evaluation => &self.evaluator,
            LearningIterationStageV1::Proposal => &self.proposal,
            LearningIterationStageV1::Selection => &self.selector,
            LearningIterationStageV1::NextUse => &self.next_use_observer,
        }
    }
}
