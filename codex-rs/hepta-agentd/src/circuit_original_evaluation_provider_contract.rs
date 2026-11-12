//! Preregistered identities and concrete original data custody.
//! Rule fields are declarations only. The original Training signature pins the
//! complete panel profile before B; the original Evaluator signs this rule in
//! the independent B ledger's exact freeze. No declared result is accepted.

use std::collections::BTreeSet;

use codex_hepta_intelligence_eval::TemporalEvaluationPlan;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::Error;
use crate::AgentdIdentity;
use crate::CircuitTaskSourceReadbackV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;

pub(super) const MAX_EPISODES: usize = 64;
pub(super) const MAX_SOURCES: usize = 3 * MAX_EPISODES;

/// The same identity must be present in the original signed Decision and its
/// independently authenticated terminal Outcome. It is fixed before execution.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitEvaluationEpisodeV1 {
    pub episode_id: StableId,
    pub behavior_run_id: StableId,
}

/// Two real original task publications for the same held-out input. Baseline
/// may be the logged behavior run; the candidate is always a distinct run.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitEvaluationTargetV1 {
    pub episode: OriginalCircuitEvaluationEpisodeV1,
    pub candidate_run_id: StableId,
    pub baseline_run_id: StableId,
}

/// Bounded, complete membership, unit and time rules, registered before T.
/// Unix seconds come from the original RunStart admission and independent
/// Outcome; the Cell's unrelated monotonic clock is never converted to UTC.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitEvaluationCohortRuleV1 {
    pub plan_id: StableId,
    pub task_digest: Digest32,
    pub objective_digest: Digest32,
    pub snapshot_id: StableId,
    pub unit_profile_digest: Digest32,
    pub expected_delay_profile_digest: Digest32,
    pub history_start_unix_seconds: u64,
    pub evaluation_end_unix_seconds: u64,
    pub history_window_id: StableId,
    pub holdout_window_id: StableId,
    pub candidate_plan: TemporalEvaluationPlan,
    pub baseline_plan: TemporalEvaluationPlan,
    pub history: Vec<OriginalCircuitEvaluationEpisodeV1>,
    pub targets: Vec<OriginalCircuitEvaluationTargetV1>,
}

impl OriginalCircuitEvaluationCohortRuleV1 {
    pub fn canonical_digest(&self) -> Result<Digest32, Error> {
        self.validate()?;
        let mut bytes = b"hepta.circuit.original-evaluation-cohort-rule.v1\0".to_vec();
        for id in [
            &self.plan_id,
            &self.snapshot_id,
            &self.history_window_id,
            &self.holdout_window_id,
        ] {
            push_id(&mut bytes, id);
        }
        for digest in [
            self.task_digest,
            self.objective_digest,
            self.unit_profile_digest,
            self.expected_delay_profile_digest,
            self.candidate_plan.canonical_digest()?,
            self.baseline_plan.canonical_digest()?,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for value in [
            self.history_start_unix_seconds,
            self.evaluation_end_unix_seconds,
            self.history.len() as u64,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        // The registered order is semantic and must not change after training.
        for row in &self.history {
            push_id(&mut bytes, &row.episode_id);
            push_id(&mut bytes, &row.behavior_run_id);
        }
        bytes.extend_from_slice(&(self.targets.len() as u64).to_be_bytes());
        for row in &self.targets {
            for id in [
                &row.episode.episode_id,
                &row.episode.behavior_run_id,
                &row.candidate_run_id,
                &row.baseline_run_id,
            ] {
                push_id(&mut bytes, id);
            }
        }
        Ok(Digest32::of_bytes(&bytes))
    }

    fn validate(&self) -> Result<(), Error> {
        let fold = &self.candidate_plan.fold;
        if self.history.is_empty()
            || self.targets.is_empty()
            || self.history.len() + self.targets.len() > MAX_EPISODES
            || self.history_start_unix_seconds == 0
            || self.history_start_unix_seconds > fold.training_watermark
            || fold.training_watermark >= fold.evaluation_start
            || fold.evaluation_start > self.evaluation_end_unix_seconds
            || self.history_window_id == self.holdout_window_id
            || self.candidate_plan.fold != self.baseline_plan.fold
            || self.candidate_plan.objective_digest != self.objective_digest
            || self.baseline_plan.objective_digest != self.objective_digest
            || self.candidate_plan.plan_digest != self.candidate_plan.canonical_digest()?
            || self.baseline_plan.plan_digest != self.baseline_plan.canonical_digest()?
            || self.candidate_plan.ope.outcome_watermark != self.evaluation_end_unix_seconds
            || self.baseline_plan.ope.outcome_watermark != self.evaluation_end_unix_seconds
            || fold.minimum_per_action == 0
            || [
                self.task_digest,
                self.objective_digest,
                self.unit_profile_digest,
                self.expected_delay_profile_digest,
                self.candidate_plan.plan_digest,
                self.baseline_plan.plan_digest,
            ]
            .iter()
            .any(|digest| digest.is_zero())
        {
            return Err(Error::Binding("complete preregistered cohort and time rules"));
        }
        let mut episodes = BTreeSet::new();
        let mut runs = BTreeSet::new();
        for row in &self.history {
            if !episodes.insert(&row.episode_id) || !runs.insert(&row.behavior_run_id) {
                return Err(Error::Binding("distinct original historical episodes"));
            }
        }
        for row in &self.targets {
            if !episodes.insert(&row.episode.episode_id)
                || !runs.insert(&row.episode.behavior_run_id)
                || row.candidate_run_id == row.episode.behavior_run_id
                || !runs.insert(&row.candidate_run_id)
                || (row.baseline_run_id != row.episode.behavior_run_id
                    && !runs.insert(&row.baseline_run_id))
            {
                return Err(Error::Binding("distinct actual evaluation arms and episodes"));
            }
        }
        Ok(())
    }

    pub(super) fn run_ids(&self) -> BTreeSet<StableId> {
        self.history
            .iter()
            .map(|row| row.behavior_run_id.clone())
            .chain(self.targets.iter().flat_map(|row| {
                [
                    row.episode.behavior_run_id.clone(),
                    row.candidate_run_id.clone(),
                    row.baseline_run_id.clone(),
                ]
            }))
            .collect()
    }
}

pub(super) fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}

/// A concrete original source read capability, never an uploaded publication.
pub struct OriginalCircuitEvaluationSourceV1 {
    pub source: CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>,
    pub identity: AgentdIdentity,
    pub run_id: StableId,
}

/// Consume the original independent B ledger. No writable owner extraction or
/// reopening factory is provided by this adapter.
pub struct OriginalCircuitEvaluationSourceOwnersV1 {
    pub ledger: LedgerWriter,
    pub sources: Vec<OriginalCircuitEvaluationSourceV1>,
}

pub struct OriginalCircuitEvaluationCohortConfigV1 {
    pub registration: OriginalCellEvaluationPanelRegistrationV1,
    pub rule: OriginalCircuitEvaluationCohortRuleV1,
    pub training: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub training_evidence: SignedLearningEvidenceV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub freeze_plan: DatasetFreezePlanV2,
    pub freeze_evidence: SignedLearningEvidenceV1,
}
