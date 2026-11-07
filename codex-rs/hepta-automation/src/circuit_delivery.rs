//! Read the original completed transfer without reopening computation admission.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AutomationStore;
use crate::CircuitActivationStatusV2;
use crate::CircuitComputationInputV1;
use crate::CircuitComputationTransferV1;
use crate::CircuitDispatchV2;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::circuit_computation_input;
use crate::circuit_computation_transfer;
use crate::circuit_history::CircuitFenceIdentityV2;
use crate::circuit_journal;
use crate::circuit_journal::CircuitHistoryV2;
use crate::circuit_journal::unavailable;
use crate::circuit_profile::invalid;
use crate::circuit_profile::text;

/// Immutable facts read at one verified owner cut. This is neither an execution
/// grant nor proof that a downstream owner has acknowledged its outbox.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitDeliveryObservationV1 {
    owner_agent_id: AgentId,
    definition_digest: Sha256Digest,
    checkpoint: Sha256Digest,
    revision: u64,
    dispatch: CircuitDispatchV2,
    execution_request_digest: Sha256Digest,
    input: CircuitComputationInputV1,
    transfer: CircuitComputationTransferV1,
}

impl CircuitDeliveryObservationV1 {
    pub fn owner_agent_id(&self) -> &AgentId {
        &self.owner_agent_id
    }
    pub fn definition_digest(&self) -> &Sha256Digest {
        &self.definition_digest
    }
    pub fn checkpoint(&self) -> &Sha256Digest {
        &self.checkpoint
    }
    pub fn revision(&self) -> u64 {
        self.revision
    }
    pub fn dispatch(&self) -> &CircuitDispatchV2 {
        &self.dispatch
    }
    pub fn execution_request_digest(&self) -> &Sha256Digest {
        &self.execution_request_digest
    }
    pub fn input(&self) -> &CircuitComputationInputV1 {
        &self.input
    }
    pub fn transfer(&self) -> &CircuitComputationTransferV1 {
        &self.transfer
    }
}

/// Only the durable Circuit owner can mint this non-cloneable delivery token.
/// It can never admit computation. A consuming bridge must check its complete
/// fence and lease against its trusted clock at the actual downstream boundary.
#[derive(Debug)]
pub struct CircuitDeliveryAdmissionV1 {
    observation: CircuitDeliveryObservationV1,
    fence: TaskFlowFence,
    observed_at_ms: u64,
    lease_expires_at_ms: u64,
}

impl CircuitDeliveryAdmissionV1 {
    pub fn observation(&self) -> &CircuitDeliveryObservationV1 {
        &self.observation
    }
    pub fn fence(&self) -> &TaskFlowFence {
        &self.fence
    }
    pub fn observed_at_ms(&self) -> u64 {
        self.observed_at_ms
    }
    pub fn lease_expires_at_ms(&self) -> u64 {
        self.lease_expires_at_ms
    }
}

impl AutomationStore {
    /// Pure terminal-safe readback of the originally retained input and transfer.
    /// Missing completion remains missing; this never reconstructs a request or
    /// changes the computation reservation, delivery history, or writer lease.
    pub async fn observe_circuit_delivery(
        &self,
        run_id: &str,
        activation_id: u64,
    ) -> Result<Option<CircuitDeliveryObservationV1>, TaskFlowError> {
        text(run_id)?;
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let history = circuit_journal::load(&mut tx, self.owner_agent_id(), run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Conflict("unknown circuit run".into()))?;
        let observation = load(&mut tx, &history, self.owner_agent_id(), activation_id).await?;
        tx.commit().await.map_err(unavailable)?;
        Ok(observation)
    }

    /// Recover delivery under the current live writer fence. Unlike computation
    /// recovery, this may read a completed activation after Circuit termination.
    /// The original first-execution and reconciliation-only APIs are unchanged.
    pub async fn recover_circuit_delivery(
        &self,
        run_id: &str,
        activation_id: u64,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<CircuitDeliveryAdmissionV1, TaskFlowError> {
        text(run_id)?;
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let history = circuit_journal::load(&mut tx, self.owner_agent_id(), run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Conflict("unknown circuit run".into()))?;
        let identity = CircuitFenceIdentityV2::from_fence(fence)?;
        if fence.owner_agent_id != *self.owner_agent_id()
            || !identity.matches(&history.run.writer)
            || now_ms >= history.run.writer.expires_at_ms
            || now_ms < history.run.last_observed_ms
        {
            return Err(TaskFlowError::StaleFence);
        }
        let observation = load(&mut tx, &history, self.owner_agent_id(), activation_id)
            .await?
            .ok_or_else(|| invalid("computation has no retained delivery"))?;
        let admission = CircuitDeliveryAdmissionV1 {
            observation,
            fence: fence.clone(),
            observed_at_ms: now_ms,
            lease_expires_at_ms: history.run.writer.expires_at_ms,
        };
        tx.commit().await.map_err(unavailable)?;
        Ok(admission)
    }
}

pub(crate) async fn load(
    tx: &mut Transaction<'_, Sqlite>,
    history: &CircuitHistoryV2,
    owner: &AgentId,
    activation_id: u64,
) -> Result<Option<CircuitDeliveryObservationV1>, TaskFlowError> {
    let run = &history.run;
    let activation = run
        .activations
        .get(&activation_id)
        .ok_or_else(|| invalid("unknown computation"))?;
    let transfer = circuit_computation_transfer::load(
        tx,
        owner,
        &run.run_id,
        activation_id,
        history.transfer_digests.get(&activation_id),
        activation.output_digest.as_ref(),
    )
    .await?;
    let Some(transfer) = transfer else {
        return Ok(None);
    };
    let input = circuit_computation_input::load(
        tx,
        owner,
        &run.run_id,
        activation_id,
        history.input_digests.get(&activation_id),
    )
    .await?
    .ok_or_else(|| TaskFlowError::Corrupt("delivery lost its original input".into()))?;
    let execution_request_digest = activation
        .execution_request_digest
        .clone()
        .ok_or_else(|| TaskFlowError::Corrupt("delivery lost its original claim".into()))?;
    if activation.status != CircuitActivationStatusV2::Completed
        || activation.receipt_digest.as_ref() != Some(&transfer.digest()?)
    {
        return Err(TaskFlowError::Corrupt(
            "delivery is not the completed transfer".into(),
        ));
    }
    Ok(Some(CircuitDeliveryObservationV1 {
        owner_agent_id: owner.clone(),
        definition_digest: run.definition_digest.clone(),
        checkpoint: history.last_digest.clone(),
        revision: run.revision,
        dispatch: run.dispatch(&history.definition, activation_id)?,
        execution_request_digest,
        input,
        transfer,
    }))
}
