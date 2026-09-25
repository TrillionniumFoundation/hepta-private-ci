//! Validation and canonical identities for the threshold DecisionCell runtime.

use std::collections::BTreeSet;

use crate::CircuitNodeRoleV1;
use crate::TaskFlowError;
use crate::TaskFlowRun;
use crate::TaskFlowTransition;
use crate::threshold_circuit::ThresholdCircuitDecisionV1;
use crate::threshold_circuit::ThresholdCircuitDispositionV1;
use crate::threshold_circuit::ThresholdCircuitInvocationV1;
use crate::threshold_circuit::ThresholdDecisionCellParametersV1;
use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;
use sqlx::Row;

const MAX_ID_BYTES: usize = 256;
const MIN_PPM: i32 = -1_000_000;
const MAX_PPM: i32 = 1_000_000;

pub(crate) fn validate_invocation(
    invocation: &ThresholdCircuitInvocationV1,
) -> Result<(), TaskFlowError> {
    validate_text(&invocation.operation_id, "operation_id")?;
    if !(MIN_PPM..=MAX_PPM).contains(&invocation.input_value_ppm) {
        return Err(invalid("threshold circuit input is outside ppm bounds"));
    }
    invocation.candidate.validate()?;
    invocation.parameters.validate()?;
    if invocation.candidate.parameter_bundle_digest != invocation.parameters.parameter_digest {
        return Err(TaskFlowError::Conflict(
            "circuit candidate does not bind the supplied cell parameters".to_string(),
        ));
    }
    if !invocation.candidate.capability_set.is_empty()
        || invocation.candidate.nodes.len() != 3
        || invocation.candidate.edges.len() != 2
    {
        return Err(invalid(
            "minimal threshold circuit must contain one decision and two authority-free exits",
        ));
    }
    let entry = invocation
        .candidate
        .nodes
        .iter()
        .find(|node| node.node_id == invocation.candidate.entry_node)
        .ok_or_else(|| invalid("threshold circuit entry node is missing"))?;
    if entry.role != CircuitNodeRoleV1::Decide {
        return Err(invalid("threshold circuit entry must be a DecisionCell"));
    }
    let high = invocation
        .candidate
        .nodes
        .iter()
        .find(|node| node.node_id == invocation.parameters.high_node)
        .ok_or_else(|| invalid("threshold circuit high branch is missing"))?;
    let low = invocation
        .candidate
        .nodes
        .iter()
        .find(|node| node.node_id == invocation.parameters.low_node)
        .ok_or_else(|| invalid("threshold circuit low branch is missing"))?;
    if high.role != CircuitNodeRoleV1::ExitSuccess || low.role != CircuitNodeRoleV1::ExitFailure {
        return Err(invalid(
            "threshold circuit branches must be success/failure exits",
        ));
    }
    let expected = BTreeSet::from([
        (
            invocation.candidate.entry_node.as_str(),
            invocation.parameters.high_node.as_str(),
        ),
        (
            invocation.candidate.entry_node.as_str(),
            invocation.parameters.low_node.as_str(),
        ),
    ]);
    let actual: BTreeSet<_> = invocation
        .candidate
        .edges
        .iter()
        .map(|edge| (edge.from.as_str(), edge.to.as_str()))
        .collect();
    if actual != expected {
        return Err(invalid(
            "threshold circuit edges do not match the cell branches",
        ));
    }
    Ok(())
}

pub(crate) fn threshold_decision(
    invocation: &ThresholdCircuitInvocationV1,
    loaded: &ThresholdDecisionCellParametersV1,
    run_id: &str,
    chosen_at_ms: u64,
) -> Result<ThresholdCircuitDecisionV1, TaskFlowError> {
    if loaded.parameter_digest != invocation.parameters.parameter_digest {
        return Err(corrupt("loaded threshold parameters changed identity"));
    }
    let (selected_node, disposition) = if invocation.input_value_ppm >= loaded.threshold_ppm {
        (
            loaded.high_node.clone(),
            ThresholdCircuitDispositionV1::Succeeded,
        )
    } else {
        (
            loaded.low_node.clone(),
            ThresholdCircuitDispositionV1::Failed,
        )
    };
    let mut decision = ThresholdCircuitDecisionV1 {
        operation_id: invocation.operation_id.clone(),
        run_id: run_id.to_string(),
        circuit_digest: invocation.candidate.circuit_digest.clone(),
        parameter_digest: loaded.parameter_digest.clone(),
        input_value_ppm: invocation.input_value_ppm,
        selected_node,
        disposition,
        choice_digest: Sha256Digest::for_bytes(b"uncomputed-threshold-choice-v1"),
        chosen_at_ms,
    };
    decision.choice_digest = choice_digest(&decision)?;
    Ok(decision)
}

pub(crate) fn ensure_decision_matches_invocation(
    decision: &ThresholdCircuitDecisionV1,
    invocation: &ThresholdCircuitInvocationV1,
) -> Result<(), TaskFlowError> {
    if decision.operation_id != invocation.operation_id
        || decision.circuit_digest != invocation.candidate.circuit_digest
        || decision.parameter_digest != invocation.parameters.parameter_digest
        || decision.input_value_ppm != invocation.input_value_ppm
    {
        return Err(TaskFlowError::Conflict(
            "circuit operation is bound to another input or generation".to_string(),
        ));
    }
    Ok(())
}

pub(crate) fn decision_from_row(
    row: sqlx::sqlite::SqliteRow,
) -> Result<ThresholdCircuitDecisionV1, TaskFlowError> {
    let disposition = ThresholdCircuitDispositionV1::parse(
        &row.try_get::<String, _>("disposition")
            .map_err(|_| corrupt("threshold decision disposition"))?,
    )?;
    let decision = ThresholdCircuitDecisionV1 {
        operation_id: row
            .try_get("operation_id")
            .map_err(|_| corrupt("threshold decision operation"))?,
        run_id: row
            .try_get("run_id")
            .map_err(|_| corrupt("threshold decision run"))?,
        circuit_digest: parse_digest(&row, "circuit_digest")?,
        parameter_digest: parse_digest(&row, "parameter_digest")?,
        input_value_ppm: row
            .try_get("input_value_ppm")
            .map_err(|_| corrupt("threshold decision input"))?,
        selected_node: row
            .try_get("selected_node")
            .map_err(|_| corrupt("threshold decision selected node"))?,
        disposition,
        choice_digest: parse_digest(&row, "choice_digest")?,
        chosen_at_ms: to_u64(
            row.try_get("chosen_at_ms")
                .map_err(|_| corrupt("threshold decision timestamp"))?,
        )?,
    };
    validate_text(&decision.operation_id, "operation_id")?;
    validate_text(&decision.run_id, "run_id")?;
    validate_text(&decision.selected_node, "selected_node")?;
    if !(MIN_PPM..=MAX_PPM).contains(&decision.input_value_ppm)
        || decision.choice_digest != choice_digest(&decision)?
    {
        return Err(corrupt("threshold decision canonical binding"));
    }
    Ok(decision)
}

pub(crate) fn threshold_run_id(owner: &str, operation_id: &str) -> String {
    let mut bytes = b"hepta.automation.threshold-circuit.run.v1\0".to_vec();
    push_text(&mut bytes, owner);
    push_text(&mut bytes, operation_id);
    format!(
        "threshold-circuit:{}",
        Sha256Digest::for_bytes(&bytes).as_str()
    )
}

pub(crate) fn threshold_command_id(phase: &str, digest: &Sha256Digest) -> String {
    format!("threshold-circuit:{phase}:{}", digest.as_str())
}

pub(crate) fn transition_phase(transition: &TaskFlowTransition) -> &'static str {
    match transition {
        TaskFlowTransition::Start => "start",
        TaskFlowTransition::Wait { .. } => "route",
        TaskFlowTransition::Resume { .. } => "resume",
        TaskFlowTransition::Succeed { .. } => "success",
        TaskFlowTransition::Fail { .. } => "failure",
        _ => "unsupported",
    }
}

pub(crate) fn next_command_time(run: &TaskFlowRun, now_ms: u64) -> Result<u64, TaskFlowError> {
    Ok(now_ms.max(
        run.updated_at_ms
            .checked_add(1)
            .ok_or_else(|| corrupt("threshold circuit timestamp overflow"))?,
    ))
}

fn choice_digest(decision: &ThresholdCircuitDecisionV1) -> Result<Sha256Digest, TaskFlowError> {
    #[derive(Serialize)]
    struct Canonical<'a> {
        schema_version: u32,
        operation_id: &'a str,
        run_id: &'a str,
        circuit_digest: &'a Sha256Digest,
        parameter_digest: &'a Sha256Digest,
        input_value_ppm: i32,
        selected_node: &'a str,
        disposition: ThresholdCircuitDispositionV1,
    }
    let bytes = serde_json::to_vec(&Canonical {
        schema_version: 1,
        operation_id: &decision.operation_id,
        run_id: &decision.run_id,
        circuit_digest: &decision.circuit_digest,
        parameter_digest: &decision.parameter_digest,
        input_value_ppm: decision.input_value_ppm,
        selected_node: &decision.selected_node,
        disposition: decision.disposition,
    })
    .map_err(|error| TaskFlowError::Corrupt(format!("choice serialization: {error}")))?;
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn parse_digest(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<Sha256Digest, TaskFlowError> {
    Sha256Digest::parse(
        row.try_get::<String, _>(column)
            .map_err(|_| corrupt(column))?,
    )
    .map_err(|_| corrupt(column))
}

pub(crate) fn validate_text(value: &str, field: &str) -> Result<(), TaskFlowError> {
    if value.is_empty() || value.len() > MAX_ID_BYTES || value.chars().any(char::is_control) {
        return Err(invalid(format!("{field} is invalid")));
    }
    Ok(())
}

pub(crate) fn to_i64(value: u64) -> Result<i64, TaskFlowError> {
    i64::try_from(value).map_err(|_| invalid("threshold circuit integer overflow"))
}

fn to_u64(value: i64) -> Result<u64, TaskFlowError> {
    u64::try_from(value).map_err(|_| corrupt("threshold circuit negative integer"))
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

pub(crate) fn invalid(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::Invalid(message.into())
}

pub(crate) fn corrupt(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::Corrupt(message.into())
}

pub(crate) fn is_constraint(error: &sqlx::Error) -> bool {
    matches!(error, sqlx::Error::Database(database) if database.is_unique_violation() || database.is_foreign_key_violation() || database.is_check_violation())
}
