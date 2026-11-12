//! A separately tagged, preregistered two-run on-policy cohort. These are
//! declarations, not execution grants. The original Training request pins the
//! complete rule through its panel registration before fitting the candidate.

use std::collections::BTreeSet;

use codex_hepta_intelligence_eval::TemporalEvaluationPlan;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::Error;
use super::protocol::OriginalCircuitOnPolicyProtocolV1;
use crate::CircuitTaskSourceInputV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellQ24CandidateMaterialV1;
use crate::OriginalCircuitEvaluationEpisodeV1;

// Preserve the original producer's bounds. A pair consumes two real episodes.
pub(super) const MAX_EPISODES: usize = 64;
pub(super) const MAX_SOURCES: usize = 3 * MAX_EPISODES;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitOnPolicyHistoryV1 {
    pub episode: OriginalCircuitEvaluationEpisodeV1,
    pub input: CircuitTaskSourceInputV1,
}

/// The input names the baseline run. Only run/derived operation identity changes
/// for the candidate. Both runs have distinct ledger-derived original episodes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitOnPolicyPairV1 {
    pub pair_id: StableId,
    pub candidate: OriginalCircuitEvaluationEpisodeV1,
    pub baseline: OriginalCircuitEvaluationEpisodeV1,
    pub input: CircuitTaskSourceInputV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitOnPolicyCohortRuleV1 {
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
    pub protocol: OriginalCircuitOnPolicyProtocolV1,
    pub history: Vec<OriginalCircuitOnPolicyHistoryV1>,
    pub pairs: Vec<OriginalCircuitOnPolicyPairV1>,
}

impl OriginalCircuitOnPolicyCohortRuleV1 {
    pub fn canonical_digest(&self) -> Result<Digest32, Error> {
        self.validate()?;
        let mut bytes = b"hepta.circuit.original-on-policy-cohort-rule.v1\0".to_vec();
        for id in [
            &self.plan_id, &self.snapshot_id,
            &self.history_window_id, &self.holdout_window_id,
        ] {
            push_id(&mut bytes, id);
        }
        for digest in [
            self.task_digest, self.objective_digest,
            self.unit_profile_digest, self.expected_delay_profile_digest,
            self.candidate_plan.canonical_digest()?,
            self.baseline_plan.canonical_digest()?,
            self.protocol.canonical_digest()?,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.push(0); // V1 admits only actual FreshEmpty predecessor state.
        bytes.extend_from_slice(&self.history_start_unix_seconds.to_be_bytes());
        bytes.extend_from_slice(&self.evaluation_end_unix_seconds.to_be_bytes());
        bytes.extend_from_slice(&(self.history.len() as u64).to_be_bytes());
        for row in &self.history {
            push_id(&mut bytes, &row.episode.episode_id);
            push_id(&mut bytes, &row.episode.behavior_run_id);
            push_input(&mut bytes, &row.input)?;
        }
        bytes.extend_from_slice(&(self.pairs.len() as u64).to_be_bytes());
        for row in &self.pairs {
            for id in [
                &row.pair_id,
                &row.candidate.episode_id, &row.candidate.behavior_run_id,
                &row.baseline.episode_id, &row.baseline.behavior_run_id,
            ] {
                push_id(&mut bytes, id);
            }
            push_input(&mut bytes, &row.input)?;
        }
        Ok(Digest32::of_bytes(&bytes))
    }

    fn validate(&self) -> Result<(), Error> {
        let fold = &self.candidate_plan.fold;
        if self.history.is_empty()
            || self.pairs.is_empty()
            || self.history.len() > MAX_EPISODES
            || self.pairs.len() > MAX_EPISODES / 2
            || self.history.len() + 2 * self.pairs.len() > MAX_EPISODES
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
                self.task_digest, self.objective_digest,
                self.unit_profile_digest, self.expected_delay_profile_digest,
                self.candidate_plan.plan_digest, self.baseline_plan.plan_digest,
            ].iter().any(|value| value.is_zero())
        {
            return Err(Error::Binding("complete preregistered paired cohort and time rules"));
        }
        self.protocol.require_objective(self.objective_digest)?;
        let mut episodes = BTreeSet::new();
        let mut runs = BTreeSet::new();
        let mut pairs = BTreeSet::new();
        for row in &self.history {
            if row.input.scope.run_id != row.episode.behavior_run_id
                || !episodes.insert(&row.episode.episode_id)
                || !runs.insert(&row.episode.behavior_run_id)
            {
                return Err(Error::Binding("distinct original historical episodes and inputs"));
            }
            self.require_input(&row.input)?;
        }
        for row in &self.pairs {
            if !pairs.insert(&row.pair_id)
                || row.input.scope.run_id != row.baseline.behavior_run_id
                || !episodes.insert(&row.candidate.episode_id)
                || !episodes.insert(&row.baseline.episode_id)
                || !runs.insert(&row.candidate.behavior_run_id)
                || !runs.insert(&row.baseline.behavior_run_id)
            {
                return Err(Error::Binding("two distinct original episodes for every frozen pair"));
            }
            self.require_input(&row.input)?;
        }
        Ok(())
    }

    fn require_input(&self, input: &CircuitTaskSourceInputV1) -> Result<(), Error> {
        if input.objective_digest != self.objective_digest
            || input.scope.cell_id != self.protocol.binding.cell.cell_id
            || input.candidates.iter().map(|value| &value.candidate_id).collect::<Vec<_>>()
                != self.protocol.binding.cell.candidates.iter()
                    .map(|value| &value.candidate_id).collect::<Vec<_>>()
        {
            return Err(Error::Binding("frozen complete paired input and Cell protocol"));
        }
        let mut bytes = Vec::new();
        push_input(&mut bytes, input)
    }

    pub(super) fn run_ids(&self) -> BTreeSet<StableId> {
        self.history.iter().map(|row| row.episode.behavior_run_id.clone())
            .chain(self.pairs.iter().flat_map(|row| [
                row.candidate.behavior_run_id.clone(), row.baseline.behavior_run_id.clone(),
            ])).collect()
    }

    pub(super) fn source_input(&self, run: &StableId) -> Result<CircuitTaskSourceInputV1, Error> {
        if let Some(row) = self.history.iter().find(|row| &row.episode.behavior_run_id == run) {
            return Ok(row.input.clone());
        }
        let row = self.pairs.iter().find(|row|
            &row.candidate.behavior_run_id == run || &row.baseline.behavior_run_id == run)
            .ok_or(Error::Binding("registered original paired run"))?;
        let mut input = row.input.clone();
        input.scope.run_id = run.clone();
        Ok(input)
    }

    pub(super) fn is_candidate_run(&self, run: &StableId) -> bool {
        self.pairs.iter().any(|row| &row.candidate.behavior_run_id == run)
    }
}

/// The candidate is the opaque value actually returned by the original T lane.
/// Reading it supplies model identity, never permission to execute B. The
/// signed T cut uniquely fills the frozen candidate slot before either B run.
pub struct OriginalCircuitOnPolicyCohortConfigV1 {
    pub registration: OriginalCellEvaluationPanelRegistrationV1,
    pub rule: OriginalCircuitOnPolicyCohortRuleV1,
    pub training: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub training_evidence: SignedLearningEvidenceV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub candidate: OriginalCellQ24CandidateMaterialV1,
    pub freeze_plan: DatasetFreezePlanV2,
    pub freeze_evidence: SignedLearningEvidenceV1,
}

pub(super) fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    push_bytes(bytes, id.as_str().as_bytes());
}

pub(super) fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value);
}

pub(super) fn input_digest(input: &CircuitTaskSourceInputV1) -> Result<Digest32, Error> {
    let mut bytes = b"hepta.circuit.original-on-policy-shared-input.v1\0".to_vec();
    // Run identity is represented separately by both frozen arm bindings.
    push_input_fields(&mut bytes, input)?;
    Ok(Digest32::of_bytes(&bytes))
}

fn push_input(bytes: &mut Vec<u8>, input: &CircuitTaskSourceInputV1) -> Result<(), Error> {
    push_id(bytes, &input.scope.run_id);
    push_input_fields(bytes, input)
}

fn push_input_fields(bytes: &mut Vec<u8>, input: &CircuitTaskSourceInputV1) -> Result<(), Error> {
    if input.scope.principal_digest.is_zero() || input.source_frontier.is_zero()
        || input.objective_digest.is_zero() || input.ndu_snapshot_digest.is_zero()
        || input.monotonic_micros == 0 || input.deadline_micros <= input.monotonic_micros
        || input.observation.is_empty() || input.observation.len() > 32 * 1024
        || !(1..=64).contains(&input.candidates.len())
        || !(1..=3_600_000).contains(&input.lease_duration_ms)
        || input.deadline_micros - input.monotonic_micros > input.lease_duration_ms * 1_000
        || input.candidates.iter().enumerate().any(|(index, value)|
            input.candidates[..index].iter().any(|other| other.candidate_id == value.candidate_id))
    {
        return Err(Error::Binding("bounded complete original input"));
    }
    for id in [&input.scope.agent_id, &input.scope.cell_id] { push_id(bytes, id); }
    for digest in [
        input.scope.principal_digest, input.source_frontier,
        input.objective_digest, input.ndu_snapshot_digest,
    ] { bytes.extend_from_slice(digest.as_array()); }
    for value in [input.monotonic_micros, input.deadline_micros, input.lease_duration_ms] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    push_bytes(bytes, &input.observation);
    bytes.extend_from_slice(&(input.candidates.len() as u64).to_be_bytes());
    for mask in &input.candidates {
        push_id(bytes, &mask.candidate_id);
        bytes.push(u8::from(mask.allowed));
    }
    Ok(())
}
