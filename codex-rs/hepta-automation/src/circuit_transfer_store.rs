//! Commit the original output/receipt before exposing Circuit settlement.
//! A single owner transaction joins the immutable bytes to the existing causal
//! completion; a later delivery ACK is a separate recovery concern.

use crate::AutomationStore;
use crate::CircuitCommandReceiptV2;
use crate::CircuitCommandV2;
use crate::CircuitComputationTransferV1;
use crate::TaskFlowError;
use crate::circuit_computation_input;
use crate::circuit_computation_transfer as transfer;
use crate::circuit_history::CircuitFenceIdentityV2;
use crate::circuit_history::CircuitLedgerEventV2;
use crate::circuit_journal;
use crate::circuit_journal::unavailable;
use crate::circuit_profile::invalid;
use crate::circuit_profile::text;

impl AutomationStore {
    /// Persist the bounded original transfer and the ordinary Complete or
    /// Reconcile in one transaction. No visible completion can precede its
    /// retained output/receipt. This entry does not run or ACK a worker, and
    /// its data argument never authenticates caller-provided measurements.
    pub async fn complete_circuit_computation_with_transfer(
        &self,
        command: &CircuitCommandV2,
        retained: &CircuitComputationTransferV1,
    ) -> Result<CircuitCommandReceiptV2, TaskFlowError> {
        text(&command.run_id)?;
        text(&command.command_id)?;
        if command.fence.owner_agent_id != *self.owner_agent_id() {
            return Err(TaskFlowError::StaleFence);
        }
        let completion = transfer::completion(&command.event)?;
        if completion.receipt_digest != retained.digest()?
            || completion.output_digest != retained.output_digest()
        {
            return Err(invalid("completion differs from its original transfer"));
        }
        let event = CircuitLedgerEventV2::ComputationCompletedWithTransferV1 {
            fence: CircuitFenceIdentityV2::from_fence(&command.fence)?,
            expected_revision: command.expected_revision,
            now_ms: command.now_ms,
            event: command.event.clone(),
        };
        let mut tx = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let history = circuit_journal::load(&mut tx, self.owner_agent_id(), &command.run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Conflict("unknown circuit run".into()))?;
        let activation = history
            .run
            .activations
            .get(&completion.activation_id)
            .ok_or_else(|| invalid("unknown computation"))?;
        let original = transfer::load(
            &mut tx,
            self.owner_agent_id(),
            &command.run_id,
            completion.activation_id,
            history.transfer_digests.get(&completion.activation_id),
            activation.output_digest.as_ref(),
        )
        .await?;
        if let Some(original) = original {
            if &original != retained {
                return Err(TaskFlowError::Conflict(
                    "computation transfer changed".into(),
                ));
            }
        } else {
            // The same replay gate performs the original CAS, owner, lease,
            // clock and activation checks before even inserting the bytes.
            event.replay(
                Some(&history.run),
                &history.definition,
                self.owner_agent_id(),
            )?;
            let input = circuit_computation_input::load(
                &mut tx,
                self.owner_agent_id(),
                &command.run_id,
                completion.activation_id,
                history.input_digests.get(&completion.activation_id),
            )
            .await?;
            if input.is_none() {
                return Err(invalid(
                    "transfer requires an originally retained computation input",
                ));
            }
            transfer::retain(
                &mut tx,
                self.owner_agent_id(),
                &command.run_id,
                completion.activation_id,
                retained,
            )
            .await?;
        }
        let receipt = circuit_journal::persist_transition(
            &mut tx,
            &history,
            self.owner_agent_id(),
            &command.command_id,
            &event,
        )
        .await?;
        tx.commit().await.map_err(unavailable)?;
        Ok(receipt)
    }

    /// Read one immutable transfer against canonical completion history, even
    /// after Circuit termination. This is data readback, never an executable
    /// computation admission or permission to acknowledge a worker outbox.
    pub async fn bounded_circuit_transfer(
        &self,
        run_id: &str,
        activation_id: u64,
    ) -> Result<Option<CircuitComputationTransferV1>, TaskFlowError> {
        text(run_id)?;
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let history = circuit_journal::load(&mut tx, self.owner_agent_id(), run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Conflict("unknown circuit run".into()))?;
        let activation = history
            .run
            .activations
            .get(&activation_id)
            .ok_or_else(|| invalid("unknown computation"))?;
        let retained = transfer::load(
            &mut tx,
            self.owner_agent_id(),
            run_id,
            activation_id,
            history.transfer_digests.get(&activation_id),
            activation.output_digest.as_ref(),
        )
        .await?;
        tx.commit().await.map_err(unavailable)?;
        Ok(retained)
    }
}
