//! Explicit constant-state terminal-value training profile.
//!
//! These records describe a real tabular candidate and its owner-derived
//! provenance. They are not a Cell compatibility bundle or adoption receipt.

use std::error::Error;
use std::fmt;

use codex_hepta_bellman_operator::TerminalCellProfileV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::SharedTerminalCandidateV1;

#[derive(Clone, Copy)]
pub(crate) enum TerminalLearningModeV1 {
    Train,
    Readback,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TerminalLearningBudgetV1 {
    pub maximum_ledger_records: u32,
    pub maximum_dataset_records: u32,
    pub maximum_wall_milliseconds: u64,
    pub maximum_artifact_bytes: u64,
}

#[derive(Clone, Debug)]
pub struct TerminalLearningRequestV1 {
    pub operation_id: StableId,
    pub source_policy_id: Sha256Digest,
    pub expected_source_support_digest: Digest32,
    pub expected_dataset_digest: Digest32,
    pub dataset_plan: DatasetFreezePlanV2,
    /// Issued by the existing evaluator for the exact current ledger cut.
    pub dataset_evidence: SignedLearningEvidenceV1,
    pub profile: TerminalCellProfileV1,
    pub budget: TerminalLearningBudgetV1,
    pub deadline_unix_seconds: u64,
}

/// Exact provenance metadata. Replay permission does not expose Memory prose.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TerminalLearningSourceLineageV1 {
    pub owner_id: AgentId,
    pub policy_id: Sha256Digest,
    pub policy_revision: u64,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TerminalLearningReceiptV1 {
    pub operation_id: StableId,
    pub job_digest: Digest32,
    pub candidate: SharedTerminalCandidateV1,
    pub payload: Vec<u8>,
    pub source: TerminalLearningSourceLineageV1,
    pub source_records: u32,
    pub training_samples: u32,
    /// Measured work from source admission through executor queue and freeze/fit.
    pub elapsed_microseconds: u64,
    pub evidence_trust_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TerminalLearningErrorV1 {
    InvalidRequest,
    WrongScope,
    Conflict,
    Capacity,
    QueueFull,
    Unavailable,
    Busy,
    DeadlineExceeded,
    CommitUncertain,
    Owner(String),
}
impl fmt::Display for TerminalLearningErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result { write!(formatter, "{self:?}") }
}
impl Error for TerminalLearningErrorV1 {}

impl TerminalLearningRequestV1 {
    pub(crate) fn job_digest(&self, agent: &AgentId, producer: &StableId) -> Result<Digest32, TerminalLearningErrorV1> {
        let b = &self.budget;
        if !(1..=4096).contains(&b.maximum_ledger_records)
            || !(1..=b.maximum_ledger_records).contains(&b.maximum_dataset_records)
            || !(1..=60_000).contains(&b.maximum_wall_milliseconds)
            || !(1..=1_048_576).contains(&b.maximum_artifact_bytes)
            || self.deadline_unix_seconds == 0
            || self.expected_dataset_digest.is_zero() || self.expected_source_support_digest.is_zero()
            || self.profile.producer_id != *producer
            || self.profile.objective_digest != self.dataset_plan.objective_digest
            || self.profile.action_ids.is_empty() || self.profile.action_ids.len() > 128
            || self.profile.minimum_samples_per_action == 0
            || self.profile.minimum_samples_per_action > 4096
        { return Err(TerminalLearningErrorV1::InvalidRequest); }
        let mut bytes = b"hepta.agentd.terminal-learning-job.v1\0".to_vec();
        for value in [
            agent.as_str(), self.operation_id.as_str(), self.source_policy_id.as_str(),
            self.dataset_plan.snapshot_id.as_str(), self.profile.artifact_id.as_str(),
            self.profile.producer_id.as_str(), self.profile.sensor_id.as_str(),
        ] { push(&mut bytes, value.as_bytes()); }
        for value in [
            self.expected_source_support_digest, self.expected_dataset_digest,
            self.dataset_plan.objective_digest, self.dataset_plan.inclusion_policy_digest,
            self.profile.objective_digest, self.profile.run_snapshot_digest, self.profile.unit_profile_digest,
        ] { bytes.extend_from_slice(value.as_array()); }
        for value in [
            self.profile.generation.get(), self.profile.minimum_samples_per_action as u64,
            u64::from(b.maximum_ledger_records), u64::from(b.maximum_dataset_records),
            b.maximum_wall_milliseconds, b.maximum_artifact_bytes, self.deadline_unix_seconds,
            self.profile.action_ids.len() as u64,
        ] { bytes.extend_from_slice(&value.to_be_bytes()); }
        for action in &self.profile.action_ids { push(&mut bytes, action.as_str().as_bytes()); }
        push(&mut bytes, &self.dataset_evidence.signing_bytes());
        bytes.extend_from_slice(&self.dataset_evidence.signature);
        Ok(Digest32::of_bytes(&bytes))
    }
}

fn push(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value);
}
