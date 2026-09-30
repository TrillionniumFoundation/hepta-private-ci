//! Reopen-time verification of immutable circuit payloads and graph bindings.
//! Rows are scanned in bounded pages within one SQLite snapshot.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteRow;

use crate::CircuitActivationV1;
use crate::CircuitBudgetReservationRefV1;
use crate::CircuitChoiceV1;
use crate::TaskFlowDefinition;
use crate::TaskFlowError;
use crate::neural_circuit_runtime::validate_activation_definition;

pub(crate) async fn verify_circuit_runtime_store(
    pool: &SqlitePool,
    owner_agent_id: &AgentId,
) -> Result<(), TaskFlowError> {
    let mut tx = pool.begin().await.map_err(|_| TaskFlowError::Unavailable)?;
    for choices in [false, true] {
        let mut last_rowid: Option<i64> = None;
        loop {
            let rows = sqlx::query(if choices {
                "SELECT c.rowid AS evidence_rowid, c.*, a.node_id, d.definition_json
                 FROM taskflow_circuit_choices c
                 LEFT JOIN taskflow_circuit_activations a
                   ON a.owner_agent_id = c.owner_agent_id AND a.run_id = c.run_id
                  AND a.activation_id = c.activation_id
                 LEFT JOIN taskflow_runs r
                   ON r.owner_agent_id = c.owner_agent_id AND r.run_id = c.run_id
                 LEFT JOIN taskflow_definitions d
                   ON d.owner_agent_id = r.owner_agent_id AND d.workflow_id = r.workflow_id
                  AND d.version = r.workflow_version
                 WHERE (? IS NULL OR c.rowid > ?) ORDER BY c.rowid LIMIT 128"
            } else {
                "SELECT a.rowid AS evidence_rowid, a.*, d.definition_json
                 FROM taskflow_circuit_activations a
                 LEFT JOIN taskflow_runs r
                   ON r.owner_agent_id = a.owner_agent_id AND r.run_id = a.run_id
                 LEFT JOIN taskflow_definitions d
                   ON d.owner_agent_id = r.owner_agent_id AND d.workflow_id = r.workflow_id
                  AND d.version = r.workflow_version
                 WHERE (? IS NULL OR a.rowid > ?) ORDER BY a.rowid LIMIT 128"
            })
            .bind(last_rowid)
            .bind(last_rowid)
            .fetch_all(&mut *tx)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
            if rows.is_empty() {
                break;
            }
            for row in rows {
                last_rowid = Some(row.try_get("evidence_rowid").map_err(|_| corrupt())?);
                if text(&row, "owner_agent_id")? != owner_agent_id.as_str() {
                    return Err(corrupt());
                }
                let definition: TaskFlowDefinition =
                    serde_json::from_str(&text(&row, "definition_json")?).map_err(|_| corrupt())?;
                definition.validate().map_err(|_| corrupt())?;
                let command_id = text(&row, "command_id")?;
                if command_id.is_empty()
                    || command_id.len() > 256
                    || command_id.chars().any(char::is_control)
                    || digest(&row, "command_digest")?
                        .as_str()
                        .bytes()
                        .all(|b| b == b'0')
                {
                    return Err(corrupt());
                }
                let _ = number(&row, "recorded_at_ms")?;
                if choices {
                    let choice = choice_from_row(&row)?;
                    let activation_node = text(&row, "node_id")?;
                    if choice.digest().map_err(|_| corrupt())? != digest(&row, "choice_digest")?
                        || !definition.edges.iter().any(|edge| {
                            edge.from == activation_node && edge.to == choice.selected_port
                        })
                    {
                        return Err(corrupt());
                    }
                } else {
                    let activation = activation_from_row(&row)?;
                    if activation.digest().map_err(|_| corrupt())?
                        != digest(&row, "activation_digest")?
                    {
                        return Err(corrupt());
                    }
                    validate_activation_definition(&activation, &definition)
                        .map_err(|_| corrupt())?;
                }
            }
        }
    }
    tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
    Ok(())
}

fn text(row: &SqliteRow, field: &str) -> Result<String, TaskFlowError> {
    row.try_get(field).map_err(|_| corrupt())
}

fn number(row: &SqliteRow, field: &str) -> Result<u64, TaskFlowError> {
    u64::try_from(row.try_get::<i64, _>(field).map_err(|_| corrupt())?).map_err(|_| corrupt())
}

fn digest(row: &SqliteRow, field: &str) -> Result<Sha256Digest, TaskFlowError> {
    Sha256Digest::parse(text(row, field)?).map_err(|_| corrupt())
}

fn corrupt() -> TaskFlowError {
    TaskFlowError::Corrupt("circuit runtime payload or graph binding is invalid".to_string())
}

pub(crate) fn activation_from_row(row: &SqliteRow) -> Result<CircuitActivationV1, TaskFlowError> {
    Ok(CircuitActivationV1 {
        run_id: text(row, "run_id")?,
        activation_id: text(row, "activation_id")?,
        round: u32::try_from(number(row, "round")?).map_err(|_| corrupt())?,
        node_id: text(row, "node_id")?,
        circuit_digest: digest(row, "circuit_digest")?,
        taskflow_definition_digest: digest(row, "taskflow_definition_digest")?,
        causal_event_digest: digest(row, "causal_event_digest")?,
        route_policy_digest: digest(row, "route_policy_digest")?,
        parameter_bundle_digest: digest(row, "parameter_bundle_digest")?,
        budget: CircuitBudgetReservationRefV1 {
            fleet_lease_id: text(row, "fleet_lease_id")?,
            fleet_lease_revision: number(row, "fleet_lease_revision")?,
            fleet_authority_epoch: number(row, "fleet_authority_epoch")?,
            resource_profile_digest: digest(row, "resource_profile_digest")?,
            compute_units: number(row, "compute_units")?,
            inference_units: number(row, "inference_units")?,
            provider_effect_units: number(row, "provider_effect_units")?,
            queue_units: number(row, "queue_units")?,
            child_units: number(row, "child_units")?,
            uncertainty_units: number(row, "uncertainty_units")?,
        },
    })
}

pub(crate) fn choice_from_row(row: &SqliteRow) -> Result<CircuitChoiceV1, TaskFlowError> {
    Ok(CircuitChoiceV1 {
        run_id: text(row, "run_id")?,
        activation_id: text(row, "activation_id")?,
        selected_port: text(row, "selected_port")?,
        candidate_set_digest: digest(row, "candidate_set_digest")?,
        behavior_policy_digest: digest(row, "behavior_policy_digest")?,
        decision_receipt_digest: digest(row, "decision_receipt_digest")?,
    })
}
