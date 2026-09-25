//! Create-only candidate and DecisionCell parameter registries.

use crate::AutomationStore;
use crate::NeuralCircuitCandidateV1;
use crate::TaskFlowDefinition;
use crate::TaskFlowError;
use crate::ThresholdDecisionCellParametersV1;
use crate::validate_circuit_successor_v1;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;

impl AutomationStore {
    pub(crate) async fn register_threshold_candidate(
        &self,
        candidate: &NeuralCircuitCandidateV1,
        registered_at_ms: u64,
    ) -> Result<TaskFlowDefinition, TaskFlowError> {
        candidate.validate()?;
        let (definition, _) = candidate.compile_taskflow()?;
        if let Some(existing) = self
            .circuit_candidate_by_identity(&candidate.circuit_id, candidate.version)
            .await?
        {
            if existing != *candidate {
                return Err(TaskFlowError::Conflict(
                    "circuit identity is bound to another candidate".to_string(),
                ));
            }
            return Ok(definition);
        }
        if candidate.version > 1 {
            let previous_version = candidate
                .version
                .checked_sub(1)
                .ok_or_else(|| invalid("circuit predecessor version underflow"))?;
            let previous = self
                .circuit_candidate_by_identity(&candidate.circuit_id, previous_version)
                .await?
                .ok_or_else(|| {
                    TaskFlowError::Conflict(
                        "circuit successor has no registered predecessor".to_string(),
                    )
                })?;
            validate_circuit_successor_v1(&previous, candidate)?;
        }
        let json = serde_json::to_string(candidate).map_err(|error| {
            TaskFlowError::Corrupt(format!("circuit candidate serialization: {error}"))
        })?;
        let inserted = sqlx::query(
            "INSERT INTO automation_circuit_candidates (
                 owner_agent_id, circuit_id, version, candidate_json,
                 circuit_digest, predecessor_digest, definition_digest,
                 registered_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&candidate.circuit_id)
        .bind(i64::from(candidate.version))
        .bind(json)
        .bind(candidate.circuit_digest.as_str())
        .bind(
            candidate
                .predecessor_digest
                .as_ref()
                .map(Sha256Digest::as_str),
        )
        .bind(definition.definition_digest().as_str())
        .bind(to_i64(registered_at_ms)?)
        .execute(self.taskflow_pool())
        .await;
        match inserted {
            Ok(_) => Ok(definition),
            Err(error) if is_constraint(&error) => {
                let existing = self
                    .circuit_candidate_by_identity(&candidate.circuit_id, candidate.version)
                    .await?
                    .ok_or_else(|| {
                        TaskFlowError::Conflict("circuit candidate registration raced".to_string())
                    })?;
                if existing != *candidate {
                    return Err(TaskFlowError::Conflict(
                        "circuit candidate registration conflicted".to_string(),
                    ));
                }
                Ok(definition)
            }
            Err(_) => Err(TaskFlowError::Unavailable),
        }
    }

    pub(crate) async fn circuit_candidate_by_digest(
        &self,
        circuit_digest: &Sha256Digest,
    ) -> Result<Option<NeuralCircuitCandidateV1>, TaskFlowError> {
        let row = sqlx::query(
            "SELECT * FROM automation_circuit_candidates
             WHERE owner_agent_id = ? AND circuit_digest = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(circuit_digest.as_str())
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        row.map(candidate_from_row).transpose()
    }

    async fn circuit_candidate_by_identity(
        &self,
        circuit_id: &str,
        version: u32,
    ) -> Result<Option<NeuralCircuitCandidateV1>, TaskFlowError> {
        let row = sqlx::query(
            "SELECT * FROM automation_circuit_candidates
             WHERE owner_agent_id = ? AND circuit_id = ? AND version = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(circuit_id)
        .bind(i64::from(version))
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        row.map(candidate_from_row).transpose()
    }

    pub(crate) async fn register_threshold_parameters(
        &self,
        parameters: &ThresholdDecisionCellParametersV1,
        registered_at_ms: u64,
    ) -> Result<(), TaskFlowError> {
        parameters.validate()?;
        if let Some(existing) = self
            .threshold_parameters_by_identity(&parameters.cell_id, parameters.version)
            .await?
        {
            if existing != *parameters {
                return Err(TaskFlowError::Conflict(
                    "cell identity is bound to other parameters".to_string(),
                ));
            }
            return Ok(());
        }
        if parameters.version > 1 {
            let previous_version = parameters
                .version
                .checked_sub(1)
                .ok_or_else(|| invalid("parameter predecessor version underflow"))?;
            let previous = self
                .threshold_parameters_by_identity(&parameters.cell_id, previous_version)
                .await?
                .ok_or_else(|| {
                    TaskFlowError::Conflict(
                        "parameter successor has no registered predecessor".to_string(),
                    )
                })?;
            if parameters.predecessor_digest.as_ref() != Some(&previous.parameter_digest) {
                return Err(TaskFlowError::Conflict(
                    "parameter successor does not bind the previous digest".to_string(),
                ));
            }
        }
        let json = serde_json::to_string(parameters).map_err(|error| {
            TaskFlowError::Corrupt(format!("cell parameter serialization: {error}"))
        })?;
        let inserted = sqlx::query(
            "INSERT INTO automation_threshold_cell_parameters (
                 owner_agent_id, cell_id, version, parameter_json,
                 parameter_digest, predecessor_digest, threshold_ppm,
                 high_node, low_node, registered_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&parameters.cell_id)
        .bind(i64::from(parameters.version))
        .bind(json)
        .bind(parameters.parameter_digest.as_str())
        .bind(
            parameters
                .predecessor_digest
                .as_ref()
                .map(Sha256Digest::as_str),
        )
        .bind(parameters.threshold_ppm)
        .bind(&parameters.high_node)
        .bind(&parameters.low_node)
        .bind(to_i64(registered_at_ms)?)
        .execute(self.taskflow_pool())
        .await;
        match inserted {
            Ok(_) => Ok(()),
            Err(error) if is_constraint(&error) => {
                let existing = self
                    .threshold_parameters_by_identity(&parameters.cell_id, parameters.version)
                    .await?
                    .ok_or_else(|| {
                        TaskFlowError::Conflict("cell parameter registration raced".to_string())
                    })?;
                if existing != *parameters {
                    return Err(TaskFlowError::Conflict(
                        "cell parameter registration conflicted".to_string(),
                    ));
                }
                Ok(())
            }
            Err(_) => Err(TaskFlowError::Unavailable),
        }
    }

    pub(crate) async fn threshold_parameters_by_digest(
        &self,
        parameter_digest: &Sha256Digest,
    ) -> Result<Option<ThresholdDecisionCellParametersV1>, TaskFlowError> {
        let row = sqlx::query(
            "SELECT * FROM automation_threshold_cell_parameters
             WHERE owner_agent_id = ? AND parameter_digest = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(parameter_digest.as_str())
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        row.map(parameters_from_row).transpose()
    }

    async fn threshold_parameters_by_identity(
        &self,
        cell_id: &str,
        version: u32,
    ) -> Result<Option<ThresholdDecisionCellParametersV1>, TaskFlowError> {
        let row = sqlx::query(
            "SELECT * FROM automation_threshold_cell_parameters
             WHERE owner_agent_id = ? AND cell_id = ? AND version = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(cell_id)
        .bind(i64::from(version))
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        row.map(parameters_from_row).transpose()
    }
}

fn candidate_from_row(
    row: sqlx::sqlite::SqliteRow,
) -> Result<NeuralCircuitCandidateV1, TaskFlowError> {
    let json: String = row
        .try_get("candidate_json")
        .map_err(|_| corrupt("circuit candidate json"))?;
    let candidate: NeuralCircuitCandidateV1 =
        serde_json::from_str(&json).map_err(|_| corrupt("circuit candidate json"))?;
    candidate.validate()?;
    let stored_digest = parse_digest(&row, "circuit_digest")?;
    if candidate.circuit_digest != stored_digest {
        return Err(corrupt("circuit candidate digest"));
    }
    let (definition, _) = candidate.compile_taskflow()?;
    if definition.definition_digest() != &parse_digest(&row, "definition_digest")? {
        return Err(corrupt("circuit definition digest"));
    }
    let circuit_id: String = row
        .try_get("circuit_id")
        .map_err(|_| corrupt("circuit id"))?;
    let version = to_u32(
        row.try_get("version")
            .map_err(|_| corrupt("circuit version"))?,
    )?;
    if candidate.circuit_id != circuit_id || candidate.version != version {
        return Err(corrupt("circuit candidate identity"));
    }
    Ok(candidate)
}

fn parameters_from_row(
    row: sqlx::sqlite::SqliteRow,
) -> Result<ThresholdDecisionCellParametersV1, TaskFlowError> {
    let json: String = row
        .try_get("parameter_json")
        .map_err(|_| corrupt("cell parameter json"))?;
    let parameters: ThresholdDecisionCellParametersV1 =
        serde_json::from_str(&json).map_err(|_| corrupt("cell parameter json"))?;
    parameters.validate()?;
    let stored_digest = parse_digest(&row, "parameter_digest")?;
    let cell_id: String = row.try_get("cell_id").map_err(|_| corrupt("cell id"))?;
    let version = to_u32(
        row.try_get("version")
            .map_err(|_| corrupt("cell version"))?,
    )?;
    let threshold_ppm: i32 = row
        .try_get("threshold_ppm")
        .map_err(|_| corrupt("cell threshold"))?;
    let high_node: String = row
        .try_get("high_node")
        .map_err(|_| corrupt("cell high node"))?;
    let low_node: String = row
        .try_get("low_node")
        .map_err(|_| corrupt("cell low node"))?;
    if parameters.parameter_digest != stored_digest
        || parameters.cell_id != cell_id
        || parameters.version != version
        || parameters.threshold_ppm != threshold_ppm
        || parameters.high_node != high_node
        || parameters.low_node != low_node
    {
        return Err(corrupt("cell parameter projection"));
    }
    Ok(parameters)
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

fn to_i64(value: u64) -> Result<i64, TaskFlowError> {
    i64::try_from(value).map_err(|_| invalid("registry timestamp overflow"))
}

fn to_u32(value: i64) -> Result<u32, TaskFlowError> {
    u32::try_from(value).map_err(|_| corrupt("registry version"))
}

fn invalid(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::Invalid(message.into())
}

fn corrupt(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::Corrupt(message.into())
}

fn is_constraint(error: &sqlx::Error) -> bool {
    matches!(error, sqlx::Error::Database(database) if database.is_unique_violation() || database.is_foreign_key_violation() || database.is_check_violation())
}
