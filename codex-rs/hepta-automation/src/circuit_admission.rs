//! Sealed computation admission from the real durable Circuit owner.
//!
//! A canonical dispatch DTO is not proof of admission. This owner journals a
//! computation claim exactly once before returning its non-cloneable token.
//! After acknowledgement loss, recovery is readback-only even if the Cell has
//! not yet received the request. Absence alone is not a no-contact proof.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;

use crate::AutomationStore;
use crate::CircuitActivationStatusV2;
use crate::CircuitCommandStatusV2;
use crate::CircuitDispatchV2;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::circuit_history::CircuitFenceIdentityV2;
use crate::circuit_history::CircuitLedgerEventV2;
use crate::circuit_journal;
use crate::circuit_journal::CircuitHistoryV2;
use crate::circuit_journal::unavailable;
use crate::circuit_profile::digest;
use crate::circuit_profile::hash;
use crate::circuit_profile::invalid;
use crate::circuit_profile::text;

#[derive(Clone, Debug)]
pub struct CircuitComputationClaimV2 {
    pub run_id: String,
    pub activation_id: u64,
    pub command_id: String,
    pub fence: TaskFlowFence,
    pub expected_revision: u64,
    pub now_ms: u64,
    /// Exact downstream semantic request, including its original clock,
    /// source frontier, candidate mask, objective and NDU snapshot.
    pub execution_request_digest: Sha256Digest,
}

#[derive(Debug)]
enum AdmissionMode {
    Execute,
    ReconciliationOnly,
}

/// Only AutomationStore constructs this token. It is neither Clone nor
/// Deserialize, and bridges consume it by value. It admits one computation
/// through the existing facilities; it grants no external-effect authority.
#[derive(Debug)]
pub struct CircuitComputationAdmissionV2 {
    dispatch: CircuitDispatchV2,
    owner_agent_id: AgentId,
    definition_digest: Sha256Digest,
    execution_request_digest: Option<Sha256Digest>,
    observed_revision: u64,
    observed_at_ms: u64,
    lease_expires_at_ms: u64,
    run_deadline_ms: u64,
    mode: AdmissionMode,
}

impl CircuitComputationAdmissionV2 {
    pub fn dispatch(&self) -> &CircuitDispatchV2 { &self.dispatch }
    pub fn owner_agent_id(&self) -> &AgentId { &self.owner_agent_id }
    pub fn definition_digest(&self) -> &Sha256Digest { &self.definition_digest }
    pub fn execution_request_digest(&self) -> Option<&Sha256Digest> { self.execution_request_digest.as_ref() }
    pub fn observed_revision(&self) -> u64 { self.observed_revision }
    pub fn observed_at_ms(&self) -> u64 { self.observed_at_ms }
    pub fn lease_expires_at_ms(&self) -> u64 { self.lease_expires_at_ms }
    pub fn run_deadline_ms(&self) -> u64 { self.run_deadline_ms }
    pub fn reconciliation_only(&self) -> bool { matches!(self.mode, AdmissionMode::ReconciliationOnly) }
}

impl AutomationStore {
    /// Persist the first claim before handing out an executable admission.
    /// Repeated claims never return execution authority, including after a lost
    /// response between this commit and the downstream Cell's admission.
    pub async fn claim_circuit_computation(
        &self,
        claim: &CircuitComputationClaimV2,
    ) -> Result<CircuitComputationAdmissionV2, TaskFlowError> {
        text(&claim.run_id)?;
        text(&claim.command_id)?;
        digest(&claim.execution_request_digest)?;
        let identity = CircuitFenceIdentityV2::from_fence(&claim.fence)?;
        let event = CircuitLedgerEventV2::ComputationClaimed {
            fence: identity,
            expected_revision: claim.expected_revision,
            now_ms: claim.now_ms,
            activation_id: claim.activation_id,
            execution_request_digest: claim.execution_request_digest.clone(),
        };
        let mut tx = self.taskflow_pool().begin_with("BEGIN IMMEDIATE").await.map_err(unavailable)?;
        let mut history = circuit_journal::load(&mut tx, self.owner_agent_id(), &claim.run_id).await?
            .ok_or_else(|| TaskFlowError::Conflict("unknown circuit run".to_string()))?;
        validate_pending(&history, self.owner_agent_id(), &claim.fence, claim.activation_id, claim.now_ms)?;
        let command_digest = hash("hepta.circuit.command.v2", &event)?;
        if history.commands.get(&claim.command_id).is_some_and(|digest| digest != &command_digest) {
            return Err(TaskFlowError::Conflict("computation command ID has different bytes".to_string()));
        }
        let activation = &history.run.activations[&claim.activation_id];
        if activation.execution_request_digest.as_ref().is_some_and(|digest| digest != &claim.execution_request_digest) {
            return Err(TaskFlowError::Conflict("computation claim changes the downstream request".to_string()));
        }
        let may_claim = activation.status == CircuitActivationStatusV2::InFlight
            && !activation.cancel_requested && activation.execution_request_digest.is_none();
        let mode = if may_claim {
            let receipt = circuit_journal::persist_transition(
                &mut tx, &history, self.owner_agent_id(), &claim.command_id, &event,
            ).await?;
            history.run = receipt.run;
            if receipt.status == CircuitCommandStatusV2::Applied {
                AdmissionMode::Execute
            } else {
                AdmissionMode::ReconciliationOnly
            }
        } else {
            AdmissionMode::ReconciliationOnly
        };
        let admission = admission(&history, self.owner_agent_id(), claim.activation_id, claim.now_ms, mode)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(admission)
    }

    /// Verified readback only. This method never changes a Ready activation into
    /// a dispatch and never reissues an InFlight/Indeterminate computation.
    pub async fn recover_circuit_computation(
        &self,
        run_id: &str,
        activation_id: u64,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<CircuitComputationAdmissionV2, TaskFlowError> {
        text(run_id)?;
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let history = circuit_journal::load(&mut tx, self.owner_agent_id(), run_id).await?
            .ok_or_else(|| TaskFlowError::Conflict("unknown circuit run".to_string()))?;
        validate_pending(&history, self.owner_agent_id(), fence, activation_id, now_ms)?;
        let admission = admission(&history, self.owner_agent_id(), activation_id, now_ms, AdmissionMode::ReconciliationOnly)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(admission)
    }
}

fn validate_pending(
    history: &CircuitHistoryV2,
    owner: &AgentId,
    fence: &TaskFlowFence,
    activation_id: u64,
    now_ms: u64,
) -> Result<(), TaskFlowError> {
    let identity = CircuitFenceIdentityV2::from_fence(fence)?;
    if fence.owner_agent_id != *owner || !identity.matches(&history.run.writer)
        || now_ms >= history.run.writer.expires_at_ms || now_ms < history.run.last_observed_ms
    {
        return Err(TaskFlowError::StaleFence);
    }
    let activation = history.run.activations.get(&activation_id).ok_or_else(|| invalid("unknown computation"))?;
    if !matches!(activation.status, CircuitActivationStatusV2::InFlight | CircuitActivationStatusV2::Indeterminate)
        || history.run.outcome().is_some()
    {
        return Err(invalid("activation has no pending computation to admit or reconcile"));
    }
    history.run.dispatch(&history.definition, activation_id)?;
    Ok(())
}

fn admission(
    history: &CircuitHistoryV2,
    owner: &AgentId,
    activation_id: u64,
    observed_at_ms: u64,
    mode: AdmissionMode,
) -> Result<CircuitComputationAdmissionV2, TaskFlowError> {
    Ok(CircuitComputationAdmissionV2 {
        dispatch: history.run.dispatch(&history.definition, activation_id)?,
        owner_agent_id: owner.clone(),
        definition_digest: history.run.definition_digest.clone(),
        execution_request_digest: history.run.activations[&activation_id].execution_request_digest.clone(),
        observed_revision: history.run.revision,
        observed_at_ms,
        lease_expires_at_ms: history.run.writer.expires_at_ms,
        run_deadline_ms: history.run.created_at_ms.checked_add(history.definition.limits.max_elapsed_ms)
            .ok_or_else(|| invalid("circuit deadline overflow"))?,
        mode,
    })
}

#[cfg(test)]
#[path = "circuit_admission_tests.rs"]
mod tests;
