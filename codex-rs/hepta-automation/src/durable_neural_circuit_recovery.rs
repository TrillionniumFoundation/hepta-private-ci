//! Recovery continuation for a Neural Circuit activation that an operator has
//! explicitly quarantined after the owning DecisionCell/organ outcome remained
//! unknown. Automatic execution stays blocked; only the identity-bound recovery
//! observer used by the durable owner may re-arm the exact original reservation.

use sqlx::Row;

use crate::AutomationStore;
use crate::CircuitRuntimeRecoveryObserverV1;
use crate::CircuitRuntimeProfileV1;
use crate::DurableCircuitExecutionReceiptV1;
use crate::DurableCircuitRunStateV1;
use crate::DurableNeuralCircuitError;
use crate::NeuralCircuitCandidateV1;
use crate::CircuitEventIngressV1;
use crate::TaskFlowFence;

impl AutomationStore {
    /// Settle either an executing activation or a previously quarantined
    /// `recovery_required` activation. Re-arming restores only the reservation
    /// recorded by the immutable activation intent; it never allocates a new
    /// activation, calls a DecisionCell, or changes the semantic input digest.
    #[allow(clippy::too_many_arguments)]
    pub async fn settle_durable_neural_circuit_recovery_v1<R>(
        &self,
        run_id: &str,
        candidate: &NeuralCircuitCandidateV1,
        event: &CircuitEventIngressV1,
        profile: &CircuitRuntimeProfileV1,
        fence: &TaskFlowFence,
        now_ms: u64,
        observer: &mut R,
    ) -> Result<Option<DurableCircuitExecutionReceiptV1>, DurableNeuralCircuitError>
    where
        R: CircuitRuntimeRecoveryObserverV1,
    {
        let snapshot = self
            .durable_neural_circuit_snapshot_v1(run_id)
            .await?
            .ok_or_else(|| {
                DurableNeuralCircuitError::Conflict(
                    "durable circuit run does not exist".to_string(),
                )
            })?;
        match snapshot.state {
            DurableCircuitRunStateV1::Executing => {}
            DurableCircuitRunStateV1::RecoveryRequired => {
                let row = sqlx::query(
                    "SELECT reserved_cost_units FROM neural_circuit_activation_intents
                     WHERE owner_agent_id = ? AND run_id = ? AND activation_seq = ?",
                )
                .bind(self.owner_agent_id().as_str())
                .bind(run_id)
                .bind(to_i64(snapshot.activation_seq)?)
                .fetch_optional(self.taskflow_pool())
                .await
                .map_err(|_| DurableNeuralCircuitError::Unavailable)?
                .ok_or_else(|| {
                    DurableNeuralCircuitError::Corrupt(
                        "recovery-required circuit has no activation intent".to_string(),
                    )
                })?;
                let reserved = to_u64(
                    row.try_get::<i64, _>("reserved_cost_units")
                        .map_err(|_| {
                            DurableNeuralCircuitError::Corrupt(
                                "activation reservation column is invalid".to_string(),
                            )
                        })?,
                )?;
                if reserved == 0
                    || snapshot
                        .consumed_cost_units
                        .checked_add(reserved)
                        .is_none_or(|total| total > snapshot.cost_budget_units)
                {
                    return Err(DurableNeuralCircuitError::Corrupt(
                        "activation reservation exceeds the durable circuit budget".to_string(),
                    ));
                }
                let updated = sqlx::query(
                    "UPDATE neural_circuit_runs
                     SET state = 'executing', reserved_cost_units = ?, updated_at_ms = ?
                     WHERE owner_agent_id = ? AND run_id = ?
                       AND state = 'recovery_required' AND activation_seq = ?
                       AND reserved_cost_units = 0
                       AND consumed_cost_units + ? <= cost_budget_units",
                )
                .bind(to_i64(reserved)?)
                .bind(to_i64(now_ms)?)
                .bind(self.owner_agent_id().as_str())
                .bind(run_id)
                .bind(to_i64(snapshot.activation_seq)?)
                .bind(to_i64(reserved)?)
                .execute(self.taskflow_pool())
                .await
                .map_err(|_| DurableNeuralCircuitError::Unavailable)?;
                if updated.rows_affected() != 1 {
                    return Err(DurableNeuralCircuitError::Conflict(
                        "recovery reservation lost its activation fence".to_string(),
                    ));
                }
            }
            _ => {
                return Err(DurableNeuralCircuitError::Conflict(
                    "circuit has no unsettled activation".to_string(),
                ));
            }
        }

        self.recover_durable_neural_circuit_activation_v1(
            run_id, candidate, event, profile, fence, now_ms, observer,
        )
        .await
    }
}

fn to_i64(value: u64) -> Result<i64, DurableNeuralCircuitError> {
    i64::try_from(value)
        .map_err(|_| DurableNeuralCircuitError::Invalid("numeric value exceeds SQLite".to_string()))
}

fn to_u64(value: i64) -> Result<u64, DurableNeuralCircuitError> {
    u64::try_from(value).map_err(|_| {
        DurableNeuralCircuitError::Corrupt(
            "activation reservation contains a negative value".to_string(),
        )
    })
}
