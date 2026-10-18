//! Bind archived task identity to actual, independently authenticated executions.
//!
//! Timestamps refer to execution/observation, never archive publication time.
//! This pure input adapter cannot authenticate a native receipt by itself; the
//! existing dataset/observer owner must verify the supplied original bytes.
//! It constructs no longitudinal time evidence, signer, holdout owner or gate.

use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::ClusterAssignment;
use crate::FrozenTaskSourceLineageV1;
use crate::HeldOutTarget;
use crate::OutcomeTrainingSample;
use crate::TaskLineageError;
use crate::push_id;
use crate::task_lineage::digest_id;
use crate::task_lineage::require_digest;

/// The owner retains this registration before accessing held-out outcomes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TaskExecutionRegistrationV1 {
    pub run_id: StableId,
    pub preregistration_digest: Digest32,
    pub registered_at_unix_micros: u64,
}

/// One actually completed native execution batch. Millisecond host events must
/// be checked-multiplied by 1,000 at ingress, not silently relabeled.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TaskExecutionWindowV1 {
    pub registration: TaskExecutionRegistrationV1,
    pub started_at_unix_micros: u64,
    pub finished_at_unix_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TaskPredictionEventV1 {
    pub decision_id: StableId,
    pub run_id: StableId,
    pub source_graph_digest: Digest32,
    pub source_record_digest: Digest32,
    pub native_prediction_receipt_digest: Digest32,
    pub executed_at_unix_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TaskObservedOutcomeV1 {
    pub action_id: StableId,
    pub outcome: FixedQ32,
    pub observed_at_unix_micros: u64,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TaskPredictionLineageV1 {
    decision_id: StableId,
    principal: StableId,
    episode: StableId,
    window: StableId,
    cluster: StableId,
    decision_at: u64,
    evidence_digest: Digest32,
}

impl TaskExecutionRegistrationV1 {
    /// Available before execution, from the persisted run registration. It is
    /// an execution-window identity and is not evidence of future efficacy.
    pub fn window_id(
        &self,
        source: &FrozenTaskSourceLineageV1,
    ) -> Result<StableId, TaskLineageError> {
        require_digest(self.preregistration_digest)?;
        if self.registered_at_unix_micros == 0 {
            return Err(TaskLineageError::InvalidWindow);
        }
        let mut bytes = b"hepta.eval.archived-task.execution-window.v1".to_vec();
        bytes.extend_from_slice(source.scope_digest().as_array());
        bytes.extend_from_slice(source.source_graph_digest().as_array());
        bytes.extend_from_slice(self.preregistration_digest.as_array());
        push_id(&mut bytes, &self.run_id);
        digest_id("task-window", Digest32::of_bytes(&bytes))
    }
}

impl FrozenTaskSourceLineageV1 {
    pub fn bind_prediction(
        &self,
        window: &TaskExecutionWindowV1,
        event: &TaskPredictionEventV1,
        now_unix_micros: u64,
    ) -> Result<TaskPredictionLineageV1, TaskLineageError> {
        require_digest(event.native_prediction_receipt_digest)?;
        if window.registration.registered_at_unix_micros == 0
            || window.registration.registered_at_unix_micros >= window.started_at_unix_micros
            || window.started_at_unix_micros > window.finished_at_unix_micros
            || window.finished_at_unix_micros > now_unix_micros
        {
            return Err(TaskLineageError::InvalidWindow);
        }
        if event.run_id != window.registration.run_id
            || event.source_graph_digest != self.source_graph_digest()
            || event.executed_at_unix_micros < window.started_at_unix_micros
            || event.executed_at_unix_micros > window.finished_at_unix_micros
        {
            return Err(TaskLineageError::InvalidEvent);
        }
        let lineage = self.record(event.source_record_digest)?;
        let window_id = window.registration.window_id(self)?;
        let mut bytes = b"hepta.eval.archived-task.prediction-lineage.v1".to_vec();
        for digest in [
            self.source_graph_digest(),
            event.source_record_digest,
            event.native_prediction_receipt_digest,
            window.registration.preregistration_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for id in [&event.decision_id, &event.run_id, &window_id] {
            push_id(&mut bytes, id);
        }
        for time in [
            window.registration.registered_at_unix_micros,
            window.started_at_unix_micros,
            window.finished_at_unix_micros,
            event.executed_at_unix_micros,
        ] {
            bytes.extend_from_slice(&time.to_be_bytes());
        }
        Ok(TaskPredictionLineageV1 {
            decision_id: event.decision_id.clone(),
            principal: lineage.principal.clone(),
            episode: lineage.episode.clone(),
            window: window_id,
            cluster: lineage.cluster.clone(),
            decision_at: event.executed_at_unix_micros,
            evidence_digest: Digest32::of_bytes(&bytes),
        })
    }
}

impl TaskPredictionLineageV1 {
    #[must_use]
    pub fn evidence_digest(&self) -> Digest32 {
        self.evidence_digest
    }

    pub fn held_out_target(
        &self,
        mut actions: Vec<StableId>,
    ) -> Result<HeldOutTarget, TaskLineageError> {
        if actions.is_empty() || actions.len() > 128 {
            return Err(TaskLineageError::InvalidActions);
        }
        let unique: BTreeSet<_> = actions.iter().collect();
        if unique.len() != actions.len() {
            return Err(TaskLineageError::InvalidActions);
        }
        actions.sort();
        Ok(HeldOutTarget {
            decision_id: self.decision_id.clone(),
            principal_lineage: self.principal.clone(),
            episode_lineage: self.episode.clone(),
            window_id: self.window.clone(),
            decision_at: self.decision_at,
            actions,
        })
    }

    #[must_use]
    pub fn cluster_assignment(&self) -> ClusterAssignment {
        ClusterAssignment {
            decision_id: self.decision_id.clone(),
            cluster_id: self.cluster.clone(),
        }
    }

    pub fn training_sample(
        &self,
        outcome: &TaskObservedOutcomeV1,
        now_unix_micros: u64,
    ) -> Result<OutcomeTrainingSample, TaskLineageError> {
        require_digest(outcome.evidence_digest)?;
        if !(FixedQ32::ZERO..=FixedQ32::ONE).contains(&outcome.outcome)
            || outcome.observed_at_unix_micros < self.decision_at
            || outcome.observed_at_unix_micros > now_unix_micros
        {
            return Err(TaskLineageError::InvalidOutcome);
        }
        let mut bytes = b"hepta.eval.archived-task.training-lineage.v1".to_vec();
        bytes.extend_from_slice(self.evidence_digest.as_array());
        bytes.extend_from_slice(outcome.evidence_digest.as_array());
        push_id(&mut bytes, &outcome.action_id);
        bytes.extend_from_slice(&outcome.outcome.raw().to_be_bytes());
        bytes.extend_from_slice(&outcome.observed_at_unix_micros.to_be_bytes());
        Ok(OutcomeTrainingSample {
            decision_id: self.decision_id.clone(),
            principal_lineage: self.principal.clone(),
            episode_lineage: self.episode.clone(),
            window_id: self.window.clone(),
            action_id: outcome.action_id.clone(),
            outcome: outcome.outcome,
            observed_at: outcome.observed_at_unix_micros,
            evidence_digest: Digest32::of_bytes(&bytes),
        })
    }
}

#[cfg(test)]
#[path = "task_execution_lineage_tests.rs"]
mod tests;
