//! A terminal Circuit may replace its delivery writer without admitting work.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::AutomationStore;
use crate::CircuitActivationStatusV2;
use crate::CircuitCommandReceiptV2;
use crate::CircuitLeaseClaimV2;
use crate::CircuitRunV2;
use crate::TaskFlowError;
use crate::circuit_delivery;
use crate::circuit_history::CircuitFenceIdentityV2;
use crate::circuit_history::CircuitLedgerEventV2;
use crate::circuit_journal;
use crate::circuit_journal::unavailable;
use crate::circuit_profile::digest;
use crate::circuit_profile::invalid;
use crate::circuit_profile::text;
use crate::circuit_state::CircuitWriterV2;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CircuitDeliveryLeaseV1 {
    fence: CircuitFenceIdentityV2,
    expected_revision: u64,
    now_ms: u64,
    lease_duration_ms: u64,
    pub activation_id: u64,
    pub transfer_digest: Sha256Digest,
}

impl CircuitDeliveryLeaseV1 {
    pub(crate) fn replay(
        &self,
        run: &CircuitRunV2,
        owner: &AgentId,
    ) -> Result<CircuitRunV2, TaskFlowError> {
        digest(&self.transfer_digest)?;
        if run.revision != self.expected_revision || run.outcome().is_none() {
            return Err(TaskFlowError::Conflict(
                "delivery claim revision or nonterminal state".into(),
            ));
        }
        let activation = run
            .activations
            .get(&self.activation_id)
            .ok_or_else(|| invalid("unknown delivery"))?;
        if activation.status != CircuitActivationStatusV2::Completed
            || activation.execution_request_digest.is_none()
            || activation.receipt_digest.as_ref() != Some(&self.transfer_digest)
        {
            return Err(invalid("delivery claim differs from completed transfer"));
        }
        if self.now_ms < run.last_observed_ms
            || self.lease_duration_ms == 0
            || self.lease_duration_ms > 3_600_000
        {
            return Err(invalid("invalid delivery claim time or lease duration"));
        }
        let expires = self
            .now_ms
            .checked_add(self.lease_duration_ms)
            .ok_or_else(|| invalid("delivery lease overflow"))?;
        let proposed = self.fence.to_fence(owner)?;
        let expired = self.now_ms >= run.writer.expires_at_ms;
        if (!expired && (!self.fence.matches(&run.writer) || expires < run.writer.expires_at_ms))
            || (expired
                && (proposed.generation <= run.writer.generation
                    || proposed.owner_epoch < run.writer.owner_epoch))
        {
            return Err(TaskFlowError::StaleFence);
        }
        let mut next = run.clone();
        next.writer = CircuitWriterV2::new(&proposed, expires)?;
        next.revision = next
            .revision
            .checked_add(1)
            .ok_or_else(|| invalid("delivery claim revision overflow"))?;
        next.last_observed_ms = self.now_ms;
        Ok(next)
    }
}

impl AutomationStore {
    /// Renew or replace only the delivery owner of a terminal run. The original
    /// computation claim still rejects termination; no reservation, cost,
    /// activation, outcome or computation admission changes here.
    pub async fn claim_circuit_delivery_owner(
        &self,
        claim: &CircuitLeaseClaimV2,
        activation_id: u64,
        transfer_digest: &Sha256Digest,
    ) -> Result<CircuitCommandReceiptV2, TaskFlowError> {
        text(&claim.run_id)?;
        text(&claim.command_id)?;
        if claim.fence.owner_agent_id != *self.owner_agent_id() {
            return Err(TaskFlowError::StaleFence);
        }
        let event = CircuitLedgerEventV2::DeliveryOwnerClaimedV1 {
            claim: CircuitDeliveryLeaseV1 {
                fence: CircuitFenceIdentityV2::from_fence(&claim.fence)?,
                expected_revision: claim.expected_revision,
                now_ms: claim.now_ms,
                lease_duration_ms: claim.lease_duration_ms,
                activation_id,
                transfer_digest: transfer_digest.clone(),
            },
        };
        let mut tx = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let history = circuit_journal::load(&mut tx, self.owner_agent_id(), &claim.run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Conflict("unknown circuit run".into()))?;
        let observation =
            circuit_delivery::load(&mut tx, &history, self.owner_agent_id(), activation_id)
                .await?
                .ok_or_else(|| invalid("computation has no retained delivery"))?;
        if &observation.transfer().digest()? != transfer_digest {
            return Err(TaskFlowError::Conflict("delivery transfer changed".into()));
        }
        let receipt = circuit_journal::persist_transition(
            &mut tx,
            &history,
            self.owner_agent_id(),
            &claim.command_id,
            &event,
        )
        .await?;
        tx.commit().await.map_err(unavailable)?;
        Ok(receipt)
    }
}
