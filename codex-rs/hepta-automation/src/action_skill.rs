//! Goal-checked skills on the existing authorized TaskFlow effect boundary.
//!
//! This module declares a policy identity, not a policy interpreter or another
//! executor. Final-use authorization, durable attempts, writer fencing and
//! recovery admission remain owned by `AutomationStore`.

use std::future::Future;

use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

pub const ACTION_SKILL_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum ActionSkillError {
    #[error("invalid action skill contract")]
    Contract,
    #[error("invalid or mismatched action skill invocation")]
    Invocation,
    #[error("action skill observation unavailable or mismatched")]
    Observation,
    #[error("action skill encoding failed")]
    Encoding,
}

/// Per-call limits only. The durable TaskFlow owner must enforce cumulative
/// work, attempt and recovery budgets; recreating a driver grants none of them.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ActionSkillBudgetV1 {
    pub max_wire_bytes: u32,
    pub provider_timeout_ms: u64,
    pub observer_timeout_ms: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionSkillRecoveryV1 {
    /// Query the original identity. This driver never retries or compensates.
    ReconcileOriginalIdentity,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ActionSkillContractV1 {
    pub schema_version: u32,
    pub skill_id: String,
    pub version: u32,
    pub destination_id: String,
    pub observer_id: String,
    pub initiation_digest: Sha256Digest,
    pub policy_digest: Sha256Digest,
    pub termination_digest: Sha256Digest,
    pub goal_digest: Sha256Digest,
    pub budget: ActionSkillBudgetV1,
    pub recovery: ActionSkillRecoveryV1,
}

impl ActionSkillContractV1 {
    pub fn digest(&self) -> Result<Sha256Digest, ActionSkillError> {
        if self.schema_version != ACTION_SKILL_SCHEMA_VERSION
            || self.version == 0
            || [&self.skill_id, &self.destination_id, &self.observer_id]
                .into_iter()
                .any(|id| id.is_empty() || id.len() > 128 || id.chars().any(char::is_whitespace))
            || !(1..=1_048_576).contains(&self.budget.max_wire_bytes)
            || !(1..=300_000).contains(&self.budget.provider_timeout_ms)
            || !(1..=300_000).contains(&self.budget.observer_timeout_ms)
            || [
                &self.initiation_digest,
                &self.policy_digest,
                &self.termination_digest,
                &self.goal_digest,
            ]
            .into_iter()
            .any(|digest| Sha256Digest::parse(digest.as_str()).is_err())
        {
            return Err(ActionSkillError::Contract);
        }
        evidence_digest(b"hepta.action-skill.contract.v1\0", self)
    }

    /// Freeze these exact bytes into the existing TaskFlow payload/final-use
    /// binding. The provider receives the whole envelope unchanged.
    pub fn encode_invocation(&self, body: Vec<u8>) -> Result<Vec<u8>, ActionSkillError> {
        let contract_digest = self.digest()?;
        if body.len() > self.budget.max_wire_bytes as usize {
            return Err(ActionSkillError::Invocation);
        }
        let invocation = ActionSkillInvocationV1 {
            schema_version: ACTION_SKILL_SCHEMA_VERSION,
            contract_digest,
            destination_id: self.destination_id.clone(),
            body,
        };
        let bytes = serde_json::to_vec(&invocation).map_err(|_| ActionSkillError::Encoding)?;
        if bytes.len() > self.budget.max_wire_bytes as usize {
            return Err(ActionSkillError::Invocation);
        }
        Ok(bytes)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ActionSkillInvocationV1 {
    pub schema_version: u32,
    pub contract_digest: Sha256Digest,
    pub destination_id: String,
    pub body: Vec<u8>,
}

/// The durable effect intent digest includes the attempt, policy generation,
/// operation, subject and scope. It does not confer current writer authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ActionSkillBindingV1 {
    pub provider_intent: ProviderEffectIntent,
    pub effect_intent_digest: Sha256Digest,
    pub contract_digest: Sha256Digest,
    pub destination_id: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionConditionV1 {
    Met,
    Unmet,
    Unknown,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub enum ActionExecutionStateV1 {
    NotStarted,
    Running,
    WaitingForInput,
    Returned { exit_code: Option<i32> },
    Interrupted,
    Unknown,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionGoalStateV1 {
    Satisfied,
    Unsatisfied,
    Partial,
    Unknown,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionCancellationStateV1 {
    NotRequested,
    Requested,
    Confirmed,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ActionInitiationObservationV1 {
    pub binding: ActionSkillBindingV1,
    pub observer_id: String,
    pub evidence_digest: Sha256Digest,
    pub condition: ActionConditionV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ActionSkillObservationV1 {
    pub binding: ActionSkillBindingV1,
    pub provider_receipt_digest: Sha256Digest,
    pub observer_id: String,
    pub evidence_digest: Sha256Digest,
    /// Independent proof of no effect and no possible late commit for this
    /// identity. A missing row, process exit or cancellation ACK is not proof.
    pub absence_proof_digest: Option<Sha256Digest>,
    pub execution: ActionExecutionStateV1,
    pub cancellation: ActionCancellationStateV1,
    pub termination: ActionConditionV1,
    pub goal: ActionGoalStateV1,
}

/// Trusted, independently provisioned, read-only destination observer. The
/// host pins this implementation and its identity; matching a string is not
/// authentication. Implementations evaluate the contract's predicates against
/// authoritative state, never infer them from a tool return or echo a request.
///
/// Before returning, retain the evidence addressed by `evidence_digest`,
/// including partial subeffects, input-reader identity/epoch and cancellation
/// facts, in the destination observation owner. TaskFlow persists a digest, not
/// these details. Lookup must be able to observe them after either owner restarts.
/// Index initiation and subsequent evidence by the entire binding for recovery.
pub trait ActionSkillObserver: Send + Sync {
    fn observer_id(&self) -> &str;

    fn check_initiation(
        &self,
        binding: &ActionSkillBindingV1,
        body: &[u8],
    ) -> impl Future<Output = Result<ActionInitiationObservationV1, ActionSkillError>> + Send;

    fn observe(
        &self,
        binding: &ActionSkillBindingV1,
        provider_receipt_digest: &Sha256Digest,
    ) -> impl Future<Output = Result<ActionSkillObservationV1, ActionSkillError>> + Send;
}

pub(crate) fn evidence_digest<T: Serialize>(
    domain: &[u8],
    value: &T,
) -> Result<Sha256Digest, ActionSkillError> {
    let mut bytes = domain.to_vec();
    bytes.extend(serde_json::to_vec(value).map_err(|_| ActionSkillError::Encoding)?);
    Ok(Sha256Digest::for_bytes(&bytes))
}
