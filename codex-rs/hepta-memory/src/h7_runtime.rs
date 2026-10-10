//! Local qualification runtime for the H7 trajectory → evaluation → artifact
//! reload/rollback seam.
//!
//! The module is compiled in normal builds so the state machine can be wired
//! into an owning Agent's private qualification runtime.  It is intentionally
//! incapable of production promotion: every trajectory event rejects external
//! effects, every artifact/approval carries `production_authority = false`,
//! and the namespace is explicit.  A supervisor, trust signer, model runtime,
//! and durable artifact registry are still required before any production
//! claim can be made.

use std::collections::BTreeMap;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::h7_feedback::H7OfflineEvaluation;
use crate::h7_signed_artifact::H7ArtifactVerifier;
use crate::h7_signed_artifact::H7SignedArtifactEnvelope;
use crate::h7_signed_artifact::H7SignedArtifactTransition;

pub const H7_QUALIFICATION_RUNTIME_SCHEMA_VERSION: u32 = 1;
pub const H7_QUALIFICATION_RUNTIME_NAMESPACE: &str = "local_qualification_only";
pub const H7_QUALIFICATION_RUNTIME_PRODUCTION_AUTHORITY: bool = false;
pub const H7_QUALIFICATION_RUNTIME_EXTERNAL_EFFECTS: bool = false;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7TrajectoryEvent {
    pub trajectory_id: String,
    pub event_seq: u32,
    pub outcome: String,
    pub reward_bps: i32,
    pub safety_ok: bool,
    pub external_effect_executed: bool,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fence_sha256: Sha256Digest,
}

impl H7TrajectoryEvent {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        trajectory_id: impl Into<String>,
        event_seq: u32,
        outcome: impl Into<String>,
        reward_bps: i32,
        safety_ok: bool,
        authority_epoch: u64,
        owner_epoch: u64,
        generation: u64,
        fence_sha256: Sha256Digest,
    ) -> Result<Self, H7RuntimeError> {
        let event = Self {
            trajectory_id: trajectory_id.into(),
            event_seq,
            outcome: outcome.into(),
            reward_bps,
            safety_ok,
            external_effect_executed: false,
            authority_epoch,
            owner_epoch,
            generation,
            fence_sha256,
        };
        event.validate()?;
        Ok(event)
    }

    pub fn validate(&self) -> Result<(), H7RuntimeError> {
        validate_text(&self.trajectory_id, "trajectory id", /*max_bytes*/ 256)?;
        validate_text(&self.outcome, "trajectory outcome", /*max_bytes*/ 512)?;
        if self.event_seq == 0
            || self.authority_epoch == 0
            || self.owner_epoch == 0
            || self.generation == 0
        {
            return Err(H7RuntimeError::Invalid(
                "trajectory sequence and host fence epochs must be non-zero".to_string(),
            ));
        }
        if self.external_effect_executed {
            return Err(H7RuntimeError::ExternalEffect);
        }
        parse_digest(&self.fence_sha256, "trajectory fence")
    }
}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7Trajectory {
    pub trajectory_id: String,
    pub events: Vec<H7TrajectoryEvent>,
    pub trajectory_sha256: Option<Sha256Digest>,
}

impl H7Trajectory {
    pub fn new(trajectory_id: impl Into<String>) -> Result<Self, H7RuntimeError> {
        let trajectory_id = trajectory_id.into();
        validate_text(&trajectory_id, "trajectory id", /*max_bytes*/ 256)?;
        Ok(Self {
            trajectory_id,
            events: Vec::new(),
            trajectory_sha256: None,
        })
    }

    pub fn append(&mut self, event: H7TrajectoryEvent) -> Result<(), H7RuntimeError> {
        event.validate()?;
        let expected = u32::try_from(self.events.len() + 1)
            .map_err(|_| H7RuntimeError::Invalid("trajectory is too long".to_string()))?;
        if event.trajectory_id != self.trajectory_id || event.event_seq != expected {
            return Err(H7RuntimeError::NonContiguousTrajectory {
                expected,
                actual: event.event_seq,
            });
        }
        if let Some(previous) = self.events.last() {
            if (event.authority_epoch, event.owner_epoch, event.generation)
                < (
                    previous.authority_epoch,
                    previous.owner_epoch,
                    previous.generation,
                )
            {
                return Err(H7RuntimeError::FenceRegression);
            }
            if !same_trajectory_fence(&event, previous) {
                return Err(H7RuntimeError::FenceMismatch);
            }
        }
        self.events.push(event);
        self.trajectory_sha256 = Some(self.compute_digest()?);
        Ok(())
    }

    pub fn compute_digest(&self) -> Result<Sha256Digest, H7RuntimeError> {
        if self.events.is_empty() {
            return Err(H7RuntimeError::EmptyTrajectory);
        }
        digest_serialized(&self.events)
    }

    pub fn validate(&self) -> Result<Sha256Digest, H7RuntimeError> {
        if self.events.is_empty() {
            return Err(H7RuntimeError::EmptyTrajectory);
        }
        let mut previous: Option<&H7TrajectoryEvent> = None;
        for (index, event) in self.events.iter().enumerate() {
            event.validate()?;
            let expected = u32::try_from(index + 1)
                .map_err(|_| H7RuntimeError::Invalid("trajectory is too long".to_string()))?;
            if event.trajectory_id != self.trajectory_id || event.event_seq != expected {
                return Err(H7RuntimeError::NonContiguousTrajectory {
                    expected,
                    actual: event.event_seq,
                });
            }
            if let Some(previous) = previous {
                if (event.authority_epoch, event.owner_epoch, event.generation)
                    < (
                        previous.authority_epoch,
                        previous.owner_epoch,
                        previous.generation,
                    )
                {
                    return Err(H7RuntimeError::FenceRegression);
                }
                if !same_trajectory_fence(event, previous) {
                    return Err(H7RuntimeError::FenceMismatch);
                }
            }
            previous = Some(event);
        }
        let digest = self.compute_digest()?;
        if self.trajectory_sha256.as_ref() != Some(&digest) {
            return Err(H7RuntimeError::DigestMismatch("trajectory"));
        }
        Ok(digest)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7Evaluation {
    pub schema_version: u32,
    pub trajectory_sha256: Sha256Digest,
    pub sample_count: u32,
    pub candidate_reward_bps: i32,
    pub safety_floor_met: bool,
    pub replay_only: bool,
    pub production_effects: bool,
    pub evaluation_sha256: Sha256Digest,
}

#[derive(Serialize)]
struct H7EvaluationDigest<'a> {
    schema_version: u32,
    trajectory_sha256: &'a Sha256Digest,
    sample_count: u32,
    candidate_reward_bps: i32,
    safety_floor_met: bool,
    replay_only: bool,
    production_effects: bool,
}

impl H7Evaluation {
    fn for_trajectory(trajectory: &H7Trajectory) -> Result<Self, H7RuntimeError> {
        let trajectory_sha256 = trajectory.validate()?;
        let sample_count = u32::try_from(trajectory.events.len())
            .map_err(|_| H7RuntimeError::Invalid("trajectory is too long".to_string()))?;
        let reward_sum: i64 = trajectory
            .events
            .iter()
            .map(|event| i64::from(event.reward_bps))
            .sum();
        let candidate_reward_bps = i32::try_from(reward_sum / i64::from(sample_count))
            .map_err(|_| H7RuntimeError::Invalid("reward overflow".to_string()))?;
        let mut evaluation = Self {
            schema_version: H7_QUALIFICATION_RUNTIME_SCHEMA_VERSION,
            trajectory_sha256,
            sample_count,
            candidate_reward_bps,
            safety_floor_met: trajectory.events.iter().all(|event| event.safety_ok),
            replay_only: true,
            production_effects: false,
            evaluation_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        evaluation.evaluation_sha256 = digest_serialized(&H7EvaluationDigest {
            schema_version: evaluation.schema_version,
            trajectory_sha256: &evaluation.trajectory_sha256,
            sample_count: evaluation.sample_count,
            candidate_reward_bps: evaluation.candidate_reward_bps,
            safety_floor_met: evaluation.safety_floor_met,
            replay_only: evaluation.replay_only,
            production_effects: evaluation.production_effects,
        })?;
        Ok(evaluation)
    }

    pub fn validate(&self) -> Result<(), H7RuntimeError> {
        if self.schema_version != H7_QUALIFICATION_RUNTIME_SCHEMA_VERSION
            || !self.replay_only
            || self.production_effects
            || self.sample_count == 0
        {
            return Err(H7RuntimeError::Invalid(
                "evaluation crosses the qualification boundary".to_string(),
            ));
        }
        let expected = digest_serialized(&H7EvaluationDigest {
            schema_version: self.schema_version,
            trajectory_sha256: &self.trajectory_sha256,
            sample_count: self.sample_count,
            candidate_reward_bps: self.candidate_reward_bps,
            safety_floor_met: self.safety_floor_met,
            replay_only: self.replay_only,
            production_effects: self.production_effects,
        })?;
        if expected != self.evaluation_sha256 {
            return Err(H7RuntimeError::DigestMismatch("evaluation"));
        }
        parse_digest(&self.trajectory_sha256, "evaluation trajectory")
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7Artifact {
    pub schema_version: u32,
    pub artifact_id: String,
    pub trajectory_sha256: Sha256Digest,
    pub evaluation_sha256: Sha256Digest,
    pub generation: u64,
    pub phase: String,
    pub authority: String,
    pub production_authority: bool,
    pub external_effects: bool,
    pub body_sha256: Sha256Digest,
}

#[derive(Serialize)]
struct H7ArtifactDigest<'a> {
    schema_version: u32,
    artifact_id: &'a str,
    trajectory_sha256: &'a Sha256Digest,
    evaluation_sha256: &'a Sha256Digest,
    generation: u64,
    phase: &'a str,
    authority: &'a str,
    production_authority: bool,
    external_effects: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7Approval {
    pub artifact_id: String,
    pub body_sha256: Sha256Digest,
    pub approver_id: String,
    pub qualification_only: bool,
    pub production_authority: bool,
    pub external_effects: bool,
    pub approval_sha256: Sha256Digest,
}

impl H7Approval {
    pub fn qualification(
        artifact: &H7Artifact,
        approver_id: impl Into<String>,
    ) -> Result<Self, H7RuntimeError> {
        let approver_id = approver_id.into();
        validate_text(&approver_id, "approver id", /*max_bytes*/ 256)?;
        let mut approval = Self {
            artifact_id: artifact.artifact_id.clone(),
            body_sha256: artifact.body_sha256.clone(),
            approver_id,
            qualification_only: true,
            production_authority: false,
            external_effects: false,
            approval_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        approval.approval_sha256 = digest_serialized(&(
            &approval.artifact_id,
            &approval.body_sha256,
            &approval.approver_id,
            approval.qualification_only,
            approval.production_authority,
            approval.external_effects,
        ))?;
        Ok(approval)
    }

    fn validate_for(&self, artifact: &H7Artifact) -> Result<(), H7RuntimeError> {
        if self.artifact_id != artifact.artifact_id
            || self.body_sha256 != artifact.body_sha256
            || !self.qualification_only
            || self.production_authority
            || self.external_effects
        {
            return Err(H7RuntimeError::ApprovalMismatch);
        }
        validate_text(&self.approver_id, "approver id", /*max_bytes*/ 256)?;
        let expected = digest_serialized(&(
            &self.artifact_id,
            &self.body_sha256,
            &self.approver_id,
            self.qualification_only,
            self.production_authority,
            self.external_effects,
        ))?;
        if expected != self.approval_sha256 {
            return Err(H7RuntimeError::DigestMismatch("approval"));
        }
        Ok(())
    }
}

impl H7Artifact {
    fn new(
        artifact_id: impl Into<String>,
        trajectory: &H7Trajectory,
        evaluation: &H7Evaluation,
        generation: u64,
    ) -> Result<Self, H7RuntimeError> {
        let artifact_id = artifact_id.into();
        validate_text(&artifact_id, "artifact id", /*max_bytes*/ 256)?;
        if generation == 0 {
            return Err(H7RuntimeError::Invalid(
                "artifact generation must be non-zero".to_string(),
            ));
        }
        trajectory.validate()?;
        evaluation.validate()?;
        let trajectory_sha256 = trajectory
            .trajectory_sha256
            .as_ref()
            .ok_or(H7RuntimeError::EmptyTrajectory)?;
        if evaluation.trajectory_sha256 != *trajectory_sha256 {
            return Err(H7RuntimeError::DigestMismatch("artifact trajectory"));
        }
        let mut artifact = Self {
            schema_version: H7_QUALIFICATION_RUNTIME_SCHEMA_VERSION,
            artifact_id,
            trajectory_sha256: evaluation.trajectory_sha256.clone(),
            evaluation_sha256: evaluation.evaluation_sha256.clone(),
            generation,
            phase: "shadow".to_string(),
            authority: H7_QUALIFICATION_RUNTIME_NAMESPACE.to_string(),
            production_authority: false,
            external_effects: false,
            body_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        artifact.body_sha256 = digest_serialized(&H7ArtifactDigest {
            schema_version: artifact.schema_version,
            artifact_id: &artifact.artifact_id,
            trajectory_sha256: &artifact.trajectory_sha256,
            evaluation_sha256: &artifact.evaluation_sha256,
            generation: artifact.generation,
            phase: &artifact.phase,
            authority: &artifact.authority,
            production_authority: artifact.production_authority,
            external_effects: artifact.external_effects,
        })?;
        Ok(artifact)
    }

    pub fn validate(&self) -> Result<(), H7RuntimeError> {
        if self.schema_version != H7_QUALIFICATION_RUNTIME_SCHEMA_VERSION
            || self.authority != H7_QUALIFICATION_RUNTIME_NAMESPACE
            || self.phase != "shadow"
            || self.generation == 0
            || self.production_authority
            || self.external_effects
        {
            return Err(H7RuntimeError::Invalid(
                "artifact crosses the qualification boundary".to_string(),
            ));
        }
        let expected = digest_serialized(&H7ArtifactDigest {
            schema_version: self.schema_version,
            artifact_id: &self.artifact_id,
            trajectory_sha256: &self.trajectory_sha256,
            evaluation_sha256: &self.evaluation_sha256,
            generation: self.generation,
            phase: &self.phase,
            authority: &self.authority,
            production_authority: self.production_authority,
            external_effects: self.external_effects,
        })?;
        if expected != self.body_sha256 {
            return Err(H7RuntimeError::DigestMismatch("artifact"));
        }
        parse_digest(&self.trajectory_sha256, "artifact trajectory")?;
        parse_digest(&self.evaluation_sha256, "artifact evaluation")
    }
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum H7Transition {
    #[default]
    Cold,
    Reload,
    Rollback,
}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7RuntimeState {
    pub runtime_generation: u64,
    pub active_artifact_id: Option<String>,
    pub active_artifact_sha256: Option<Sha256Digest>,
    pub active_artifact_generation: u64,
    pub previous_artifact_sha256: Option<Sha256Digest>,
    pub last_transition: H7Transition,
    pub rollback_from_generation: Option<u64>,
}

/// In-memory qualification registry. Embeddings may serialize this value into
/// a private Agent-local durable store and call [`Self::rehydrate`] after a
/// restart; the digest and generation checks are repeated on every reload.
#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct H7QualificationRuntime {
    pub trajectories: BTreeMap<String, H7Trajectory>,
    pub evaluations: BTreeMap<String, H7Evaluation>,
    pub artifacts: BTreeMap<String, H7Artifact>,
    pub approvals: BTreeMap<String, H7Approval>,
    pub state: H7RuntimeState,
}

impl H7QualificationRuntime {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn append_trajectory_event(
        &mut self,
        event: H7TrajectoryEvent,
    ) -> Result<Sha256Digest, H7RuntimeError> {
        let trajectory = self
            .trajectories
            .entry(event.trajectory_id.clone())
            .or_insert(H7Trajectory::new(event.trajectory_id.clone())?);
        trajectory.append(event)?;
        trajectory
            .trajectory_sha256
            .clone()
            .ok_or(H7RuntimeError::EmptyTrajectory)
    }

    pub fn evaluate_trajectory(
        &mut self,
        trajectory_id: &str,
    ) -> Result<H7Evaluation, H7RuntimeError> {
        let trajectory = self
            .trajectories
            .get(trajectory_id)
            .ok_or(H7RuntimeError::MissingTrajectory)?;
        let evaluation = H7Evaluation::for_trajectory(trajectory)?;
        self.evaluations
            .insert(trajectory_id.to_string(), evaluation.clone());
        Ok(evaluation)
    }

    pub fn propose_artifact(
        &mut self,
        artifact_id: impl Into<String>,
        trajectory_id: &str,
        generation: u64,
    ) -> Result<H7Artifact, H7RuntimeError> {
        let trajectory = self
            .trajectories
            .get(trajectory_id)
            .ok_or(H7RuntimeError::MissingTrajectory)?;
        let evaluation = self
            .evaluations
            .get(trajectory_id)
            .ok_or(H7RuntimeError::MissingEvaluation)?;
        let artifact = H7Artifact::new(artifact_id, trajectory, evaluation, generation)?;
        self.artifacts
            .insert(artifact.artifact_id.clone(), artifact.clone());
        Ok(artifact)
    }

    pub fn approve_artifact(
        &mut self,
        artifact_id: &str,
        approver_id: impl Into<String>,
    ) -> Result<H7Approval, H7RuntimeError> {
        let artifact = self
            .artifacts
            .get(artifact_id)
            .ok_or(H7RuntimeError::MissingArtifact)?;
        artifact.validate()?;
        let approval = H7Approval::qualification(artifact, approver_id)?;
        self.approvals
            .insert(artifact_id.to_string(), approval.clone());
        Ok(approval)
    }

    pub fn reload(
        &mut self,
        artifact_id: &str,
        expected_runtime_generation: u64,
    ) -> Result<H7RuntimeState, H7RuntimeError> {
        self.transition(
            artifact_id,
            expected_runtime_generation,
            H7Transition::Reload,
        )
    }

    pub fn rollback(
        &mut self,
        artifact_id: &str,
        expected_runtime_generation: u64,
    ) -> Result<H7RuntimeState, H7RuntimeError> {
        self.transition(
            artifact_id,
            expected_runtime_generation,
            H7Transition::Rollback,
        )
    }

    /// Applies a signed qualification artifact using an exact runtime/CAS
    /// fence.  This path is intentionally separate from the legacy in-memory
    /// transition helper: callers must present an independently verified
    /// signature and the active artifact digest must match the envelope's
    /// predecessor before any state is changed.
    pub fn apply_signed(
        &mut self,
        envelope: &H7SignedArtifactEnvelope,
        verifier: &H7ArtifactVerifier,
        ope: Option<&H7OfflineEvaluation>,
        now_unix_seconds: u64,
    ) -> Result<H7RuntimeState, H7RuntimeError> {
        self.validate()?;
        let artifact = self
            .artifacts
            .get(&envelope.artifact_id)
            .ok_or(H7RuntimeError::MissingArtifact)?
            .clone();
        let expected_predecessor = self.state.active_artifact_sha256.clone();
        verifier
            .verify(
                envelope,
                &artifact,
                ope,
                now_unix_seconds,
                self.state.runtime_generation,
                expected_predecessor.as_ref(),
            )
            .map_err(|error| H7RuntimeError::SignedArtifact(error.to_string()))?;
        let transition = match envelope.transition {
            H7SignedArtifactTransition::Reload => H7Transition::Reload,
            H7SignedArtifactTransition::Rollback => H7Transition::Rollback,
        };
        self.transition_checked(
            &artifact,
            envelope.expected_runtime_generation,
            transition,
            expected_predecessor.as_ref(),
        )
    }

    pub fn snapshot(&self) -> Result<Vec<u8>, H7RuntimeError> {
        serde_json::to_vec(self).map_err(|error| H7RuntimeError::Serialization(error.to_string()))
    }

    pub fn rehydrate(snapshot: &[u8]) -> Result<Self, H7RuntimeError> {
        let runtime: Self = serde_json::from_slice(snapshot)
            .map_err(|error| H7RuntimeError::Serialization(error.to_string()))?;
        runtime.validate()?;
        Ok(runtime)
    }

    pub fn validate(&self) -> Result<(), H7RuntimeError> {
        for trajectory in self.trajectories.values() {
            trajectory.validate()?;
        }
        for (trajectory_id, evaluation) in &self.evaluations {
            evaluation.validate()?;
            let trajectory = self
                .trajectories
                .get(trajectory_id)
                .ok_or(H7RuntimeError::MissingTrajectory)?;
            if trajectory.trajectory_sha256.as_ref() != Some(&evaluation.trajectory_sha256) {
                return Err(H7RuntimeError::DigestMismatch("evaluation trajectory"));
            }
        }
        for artifact in self.artifacts.values() {
            artifact.validate()?;
            let Some(evaluation) = self
                .evaluations
                .values()
                .find(|evaluation| evaluation.evaluation_sha256 == artifact.evaluation_sha256)
            else {
                return Err(H7RuntimeError::MissingEvaluation);
            };
            if evaluation.trajectory_sha256 != artifact.trajectory_sha256 {
                return Err(H7RuntimeError::DigestMismatch(
                    "artifact trajectory/evaluation",
                ));
            }
        }
        for (artifact_id, approval) in &self.approvals {
            let artifact = self
                .artifacts
                .get(artifact_id)
                .ok_or(H7RuntimeError::MissingArtifact)?;
            approval.validate_for(artifact)?;
        }
        // The active artifact identity is a pair.  Accepting only one half
        // would let a tampered snapshot seed `apply_signed` with a digest
        // that has no corresponding artifact (or vice versa), weakening the
        // predecessor CAS fence on the next transition.
        match (
            &self.state.active_artifact_id,
            &self.state.active_artifact_sha256,
        ) {
            (Some(_), None) => {
                return Err(H7RuntimeError::Invalid(
                    "runtime has an active artifact without a digest".to_string(),
                ));
            }
            (None, Some(_)) => {
                return Err(H7RuntimeError::Invalid(
                    "runtime has an artifact digest without an active artifact".to_string(),
                ));
            }
            _ => {}
        }

        if let Some(active_id) = &self.state.active_artifact_id {
            if self.state.runtime_generation == 0 {
                return Err(H7RuntimeError::Invalid(
                    "runtime has an active artifact before its first generation".to_string(),
                ));
            }
            let artifact = self
                .artifacts
                .get(active_id)
                .ok_or(H7RuntimeError::MissingArtifact)?;
            artifact.validate()?;
            if self.state.active_artifact_sha256.as_ref() != Some(&artifact.body_sha256)
                || self.state.active_artifact_generation != artifact.generation
            {
                return Err(H7RuntimeError::DigestMismatch("runtime active artifact"));
            }
            if let Some(previous) = &self.state.previous_artifact_sha256 {
                parse_digest(previous, "runtime previous artifact")?;
            }
            match self.state.last_transition {
                H7Transition::Cold => {
                    return Err(H7RuntimeError::Invalid(
                        "runtime has an active artifact with a cold transition".to_string(),
                    ));
                }
                H7Transition::Reload if self.state.rollback_from_generation.is_some() => {
                    return Err(H7RuntimeError::Invalid(
                        "reload state cannot carry rollback provenance".to_string(),
                    ));
                }
                H7Transition::Rollback => {
                    let Some(from_generation) = self.state.rollback_from_generation else {
                        return Err(H7RuntimeError::Invalid(
                            "rollback state is missing source generation".to_string(),
                        ));
                    };
                    if from_generation <= self.state.active_artifact_generation {
                        return Err(H7RuntimeError::Invalid(
                            "rollback source generation must exceed active generation".to_string(),
                        ));
                    }
                }
                H7Transition::Reload => {}
            }
        } else if self.state.runtime_generation != 0
            || self.state.active_artifact_generation != 0
            || self.state.previous_artifact_sha256.is_some()
            || self.state.rollback_from_generation.is_some()
            || self.state.last_transition != H7Transition::Cold
        {
            return Err(H7RuntimeError::Invalid(
                "runtime cold state has artifact or transition provenance".to_string(),
            ));
        }
        Ok(())
    }

    fn transition(
        &mut self,
        artifact_id: &str,
        expected_runtime_generation: u64,
        transition: H7Transition,
    ) -> Result<H7RuntimeState, H7RuntimeError> {
        if self.state.runtime_generation != expected_runtime_generation {
            return Err(H7RuntimeError::GenerationFence {
                expected: expected_runtime_generation,
                actual: self.state.runtime_generation,
            });
        }
        let artifact = self
            .artifacts
            .get(artifact_id)
            .ok_or(H7RuntimeError::MissingArtifact)?
            .clone();
        artifact.validate()?;
        let approval = self
            .approvals
            .get(artifact_id)
            .ok_or(H7RuntimeError::UnapprovedArtifact)?;
        approval.validate_for(&artifact)?;
        let expected_predecessor = self.state.active_artifact_sha256.clone();
        self.transition_checked(
            &artifact,
            expected_runtime_generation,
            transition,
            expected_predecessor.as_ref(),
        )
    }

    fn transition_checked(
        &mut self,
        artifact: &H7Artifact,
        expected_runtime_generation: u64,
        transition: H7Transition,
        expected_predecessor: Option<&Sha256Digest>,
    ) -> Result<H7RuntimeState, H7RuntimeError> {
        if self.state.runtime_generation != expected_runtime_generation {
            return Err(H7RuntimeError::GenerationFence {
                expected: expected_runtime_generation,
                actual: self.state.runtime_generation,
            });
        }
        artifact.validate()?;
        if transition == H7Transition::Rollback
            && self.state.active_artifact_sha256.as_ref() != expected_predecessor
        {
            return Err(H7RuntimeError::PredecessorMismatch);
        }
        match transition {
            H7Transition::Reload
                if artifact.generation <= self.state.active_artifact_generation =>
            {
                return Err(H7RuntimeError::NonMonotonicReload {
                    artifact: artifact.generation,
                    active: self.state.active_artifact_generation,
                });
            }
            H7Transition::Rollback
                if artifact.generation >= self.state.active_artifact_generation
                    || self.state.active_artifact_id.is_none() =>
            {
                return Err(H7RuntimeError::InvalidRollback {
                    target: artifact.generation,
                    active: self.state.active_artifact_generation,
                });
            }
            H7Transition::Cold => {
                return Err(H7RuntimeError::Invalid(
                    "cold is not a mutable transition".to_string(),
                ));
            }
            H7Transition::Reload | H7Transition::Rollback => {}
        }
        let previous = self.state.active_artifact_sha256.clone();
        let rollback_from_generation =
            (transition == H7Transition::Rollback).then_some(self.state.active_artifact_generation);
        self.state.runtime_generation = self
            .state
            .runtime_generation
            .checked_add(1)
            .ok_or_else(|| H7RuntimeError::Invalid("runtime generation overflow".to_string()))?;
        self.state.active_artifact_id = Some(artifact.artifact_id.clone());
        self.state.active_artifact_sha256 = Some(artifact.body_sha256.clone());
        self.state.active_artifact_generation = artifact.generation;
        self.state.previous_artifact_sha256 = previous;
        self.state.last_transition = transition;
        self.state.rollback_from_generation = rollback_from_generation;
        Ok(self.state.clone())
    }
}

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum H7RuntimeError {
    #[error("invalid H7 qualification value: {0}")]
    Invalid(String),
    #[error("trajectory contains an external effect")]
    ExternalEffect,
    #[error("trajectory is not contiguous (expected {expected}, got {actual})")]
    NonContiguousTrajectory { expected: u32, actual: u32 },
    #[error("trajectory host fence regressed")]
    FenceRegression,
    #[error("trajectory host fence changed within one immutable trajectory")]
    FenceMismatch,
    #[error("trajectory is empty")]
    EmptyTrajectory,
    #[error("trajectory is missing")]
    MissingTrajectory,
    #[error("evaluation is missing")]
    MissingEvaluation,
    #[error("artifact is missing")]
    MissingArtifact,
    #[error("artifact has no qualification approval")]
    UnapprovedArtifact,
    #[error("approval does not match artifact")]
    ApprovalMismatch,
    #[error("digest mismatch for {0}")]
    DigestMismatch(&'static str),
    #[error("runtime generation fence mismatch: expected {expected}, actual {actual}")]
    GenerationFence { expected: u64, actual: u64 },
    #[error("artifact generation {artifact} is not newer than active generation {active}")]
    NonMonotonicReload { artifact: u64, active: u64 },
    #[error("artifact generation {target} is not older than active generation {active}")]
    InvalidRollback { target: u64, active: u64 },
    #[error("signed H7 artifact verification failed: {0}")]
    SignedArtifact(String),
    #[error("signed H7 artifact predecessor CAS head mismatch")]
    PredecessorMismatch,
    #[error("H7 snapshot serialization failed: {0}")]
    Serialization(String),
}

fn validate_text(value: &str, label: &str, max_bytes: usize) -> Result<(), H7RuntimeError> {
    if value.trim().is_empty() || value.len() > max_bytes || value.as_bytes().contains(&0) {
        return Err(H7RuntimeError::Invalid(format!(
            "{label} must contain 1..={max_bytes} non-NUL bytes"
        )));
    }
    Ok(())
}

fn parse_digest(digest: &Sha256Digest, label: &'static str) -> Result<(), H7RuntimeError> {
    Sha256Digest::parse(digest.as_str().to_string())
        .map(|_| ())
        .map_err(|_| H7RuntimeError::DigestMismatch(label))
}

fn same_trajectory_fence(left: &H7TrajectoryEvent, right: &H7TrajectoryEvent) -> bool {
    left.authority_epoch == right.authority_epoch
        && left.owner_epoch == right.owner_epoch
        && left.generation == right.generation
        && left.fence_sha256 == right.fence_sha256
}

fn digest_serialized<T: Serialize>(value: &T) -> Result<Sha256Digest, H7RuntimeError> {
    let encoded = serde_json::to_vec(value)
        .map_err(|error| H7RuntimeError::Serialization(error.to_string()))?;
    Ok(Sha256Digest::for_bytes(&encoded))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fence(seed: u8) -> Sha256Digest {
        Sha256Digest::for_bytes(&[seed; 8])
    }

    fn event(seq: u32, generation: u64) -> H7TrajectoryEvent {
        H7TrajectoryEvent::new(
            "trajectory:h7:runtime",
            seq,
            if seq == 1 { "abstain" } else { "proposal" },
            if seq == 1 { 4_000 } else { 8_000 },
            true,
            7,
            11,
            generation,
            fence(7),
        )
        .expect("event")
    }

    #[test]
    fn h7_runtime_closes_trajectory_eval_approval_reload_rollback_and_rehydrate() {
        let mut runtime = H7QualificationRuntime::new();
        runtime
            .append_trajectory_event(event(1, 1))
            .expect("event one");
        runtime
            .append_trajectory_event(event(2, 1))
            .expect("event two");
        let evaluation = runtime
            .evaluate_trajectory("trajectory:h7:runtime")
            .expect("evaluation");
        assert_eq!(evaluation.sample_count, 2);
        assert_eq!(evaluation.candidate_reward_bps, 6_000);
        assert!(evaluation.replay_only);
        assert!(!evaluation.production_effects);
        let artifact_v1 = runtime
            .propose_artifact("artifact:h7:runtime:1", "trajectory:h7:runtime", 1)
            .expect("artifact v1");
        assert!(!artifact_v1.production_authority);
        runtime
            .approve_artifact(&artifact_v1.artifact_id, "qualification-operator")
            .expect("approval v1");
        let state_v1 = runtime
            .reload(&artifact_v1.artifact_id, 0)
            .expect("reload v1");
        assert_eq!(state_v1.runtime_generation, 1);
        let snapshot = runtime.snapshot().expect("snapshot");
        let mut rehydrated = H7QualificationRuntime::rehydrate(&snapshot).expect("rehydrate");
        assert_eq!(rehydrated.state, state_v1);

        let artifact_v2 = rehydrated
            .propose_artifact("artifact:h7:runtime:2", "trajectory:h7:runtime", 2)
            .expect("artifact v2");
        rehydrated
            .approve_artifact(&artifact_v2.artifact_id, "qualification-operator")
            .expect("approval v2");
        let state_v2 = rehydrated
            .reload(&artifact_v2.artifact_id, 1)
            .expect("reload v2");
        assert_eq!(state_v2.runtime_generation, 2);
        assert_eq!(state_v2.active_artifact_generation, 2);
        let rollback = rehydrated
            .rollback(&artifact_v1.artifact_id, 2)
            .expect("rollback v1");
        assert_eq!(rollback.runtime_generation, 3);
        assert_eq!(rollback.active_artifact_generation, 1);
        assert_eq!(rollback.rollback_from_generation, Some(2));
    }

    #[test]
    fn h7_runtime_rejects_tamper_external_effect_and_stale_fence() {
        let mut runtime = H7QualificationRuntime::new();
        runtime.append_trajectory_event(event(1, 1)).expect("event");
        let mut forged = event(2, 1);
        forged.external_effect_executed = true;
        assert_eq!(
            runtime.append_trajectory_event(forged),
            Err(H7RuntimeError::ExternalEffect)
        );
        runtime
            .append_trajectory_event(event(2, 1))
            .expect("event two");
        runtime
            .evaluate_trajectory("trajectory:h7:runtime")
            .expect("evaluation");
        let artifact = runtime
            .propose_artifact("artifact:h7:runtime:1", "trajectory:h7:runtime", 1)
            .expect("artifact");
        assert_eq!(
            runtime.reload(&artifact.artifact_id, 0),
            Err(H7RuntimeError::UnapprovedArtifact)
        );
        runtime
            .approve_artifact(&artifact.artifact_id, "operator")
            .expect("approval");
        runtime.reload(&artifact.artifact_id, 0).expect("reload");
        assert_eq!(
            runtime.reload(&artifact.artifact_id, 0),
            Err(H7RuntimeError::GenerationFence {
                expected: 0,
                actual: 1,
            })
        );
        let mut snapshot: serde_json::Value =
            serde_json::from_slice(&runtime.snapshot().expect("snapshot")).expect("json");
        snapshot["artifacts"]["artifact:h7:runtime:1"]["phase"] =
            serde_json::Value::String("tampered".to_string());
        let encoded = serde_json::to_vec(&snapshot).expect("encoded tamper");
        assert!(matches!(
            H7QualificationRuntime::rehydrate(&encoded),
            Err(H7RuntimeError::Invalid(_)) | Err(H7RuntimeError::DigestMismatch("artifact"))
        ));
    }

    #[test]
    fn h7_runtime_rejects_orphaned_active_digest_after_rehydrate() {
        let mut runtime = H7QualificationRuntime::new();
        runtime.state.active_artifact_sha256 = Some(Sha256Digest::for_bytes(b"orphan"));
        let encoded = runtime.snapshot().expect("snapshot");
        assert_eq!(
            H7QualificationRuntime::rehydrate(&encoded),
            Err(H7RuntimeError::Invalid(
                "runtime has an artifact digest without an active artifact".to_string()
            ))
        );
    }

    #[test]
    fn h7_runtime_rejects_mixed_generation_or_fence_within_one_trajectory() {
        let mut runtime = H7QualificationRuntime::new();
        runtime
            .append_trajectory_event(event(1, 1))
            .expect("event one");

        let mixed_generation = event(2, 2);
        assert_eq!(
            runtime.append_trajectory_event(mixed_generation),
            Err(H7RuntimeError::FenceMismatch)
        );

        let mut mixed_fence = event(2, 1);
        mixed_fence.fence_sha256 = fence(8);
        assert_eq!(
            runtime.append_trajectory_event(mixed_fence),
            Err(H7RuntimeError::FenceMismatch)
        );

        // Rejection is atomic: the valid same-fence successor still occupies
        // sequence two and the resulting trajectory remains verifiable.
        runtime
            .append_trajectory_event(event(2, 1))
            .expect("same-fence event two");
        runtime
            .trajectories
            .get("trajectory:h7:runtime")
            .expect("trajectory")
            .validate()
            .expect("trajectory validates");

        // Rehydration must apply the same exact-fence rule; recomputing the
        // outer trajectory digest must not make a mixed-generation chain
        // acceptable.
        let mut forged = runtime
            .trajectories
            .get("trajectory:h7:runtime")
            .expect("trajectory")
            .clone();
        forged.events[1].generation = 2;
        forged.trajectory_sha256 = Some(forged.compute_digest().expect("forged digest"));
        assert_eq!(forged.validate(), Err(H7RuntimeError::FenceMismatch));
    }
}
