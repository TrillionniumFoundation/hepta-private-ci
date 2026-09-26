//! Minimal real DecisionCell execution on the existing TaskFlow owner.
//!
//! One bounded threshold cell loads an immutable parameter bundle, records the
//! exact choice before routing, and then advances the existing TaskFlow run.
//! The cell cannot carry capabilities or effects. Restart recovery reuses the
//! recorded choice; a successor circuit or parameter bundle is create-only.

use crate::AutomationStore;
use crate::NeuralCircuitCandidateV1;
use crate::TaskFlowCommand;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowRunState;
use crate::TaskFlowTransition;
use crate::threshold_circuit_model::corrupt;
use crate::threshold_circuit_model::decision_from_row;
use crate::threshold_circuit_model::ensure_decision_matches_invocation;
use crate::threshold_circuit_model::invalid;
use crate::threshold_circuit_model::is_constraint;
use crate::threshold_circuit_model::next_command_time;
use crate::threshold_circuit_model::threshold_command_id;
use crate::threshold_circuit_model::threshold_decision;
use crate::threshold_circuit_model::threshold_run_id;
use crate::threshold_circuit_model::to_i64;
use crate::threshold_circuit_model::transition_phase;
use crate::threshold_circuit_model::validate_invocation;
use crate::threshold_circuit_model::validate_text;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

const THRESHOLD_CELL_SCHEMA_VERSION: u32 = 1;
const MIN_PPM: i32 = -1_000_000;
const MAX_PPM: i32 = 1_000_000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ThresholdDecisionCellParametersV1 {
    pub cell_id: String,
    pub version: u32,
    pub predecessor_digest: Option<Sha256Digest>,
    pub threshold_ppm: i32,
    pub high_node: String,
    pub low_node: String,
    pub parameter_digest: Sha256Digest,
}

impl ThresholdDecisionCellParametersV1 {
    pub fn new(
        cell_id: impl Into<String>,
        version: u32,
        predecessor_digest: Option<Sha256Digest>,
        threshold_ppm: i32,
        high_node: impl Into<String>,
        low_node: impl Into<String>,
    ) -> Result<Self, TaskFlowError> {
        let mut parameters = Self {
            cell_id: cell_id.into(),
            version,
            predecessor_digest,
            threshold_ppm,
            high_node: high_node.into(),
            low_node: low_node.into(),
            parameter_digest: Sha256Digest::for_bytes(b"uncomputed-threshold-cell-v1"),
        };
        parameters.validate_shape()?;
        parameters.parameter_digest = parameters.compute_digest()?;
        Ok(parameters)
    }

    pub fn validate(&self) -> Result<(), TaskFlowError> {
        self.validate_shape()?;
        if self.parameter_digest != self.compute_digest()? {
            return Err(TaskFlowError::Corrupt(
                "threshold cell parameter digest does not match canonical bytes".to_string(),
            ));
        }
        Ok(())
    }

    fn validate_shape(&self) -> Result<(), TaskFlowError> {
        validate_text(&self.cell_id, "cell_id")?;
        validate_text(&self.high_node, "high_node")?;
        validate_text(&self.low_node, "low_node")?;
        if self.high_node == self.low_node {
            return Err(invalid("threshold cell branches must be distinct"));
        }
        if !(MIN_PPM..=MAX_PPM).contains(&self.threshold_ppm) {
            return Err(invalid("threshold cell value is outside ppm bounds"));
        }
        match (self.version, self.predecessor_digest.as_ref()) {
            (0, _) => return Err(invalid("threshold cell version must be non-zero")),
            (1, None) => {}
            (1, Some(_)) => return Err(invalid("first parameter version has a predecessor")),
            (_, None) => return Err(invalid("successor parameter version needs predecessor")),
            (_, Some(_)) => {}
        }
        Ok(())
    }

    fn compute_digest(&self) -> Result<Sha256Digest, TaskFlowError> {
        #[derive(Serialize)]
        struct Canonical<'a> {
            schema_version: u32,
            cell_id: &'a str,
            version: u32,
            predecessor_digest: &'a Option<Sha256Digest>,
            threshold_ppm: i32,
            high_node: &'a str,
            low_node: &'a str,
        }
        let bytes = serde_json::to_vec(&Canonical {
            schema_version: THRESHOLD_CELL_SCHEMA_VERSION,
            cell_id: &self.cell_id,
            version: self.version,
            predecessor_digest: &self.predecessor_digest,
            threshold_ppm: self.threshold_ppm,
            high_node: &self.high_node,
            low_node: &self.low_node,
        })
        .map_err(|error| TaskFlowError::Corrupt(format!("cell serialization: {error}")))?;
        Ok(Sha256Digest::for_bytes(&bytes))
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ThresholdCircuitDispositionV1 {
    Succeeded,
    Failed,
}

impl ThresholdCircuitDispositionV1 {
    fn as_str(self) -> &'static str {
        match self {
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
        }
    }

    pub(crate) fn parse(value: &str) -> Result<Self, TaskFlowError> {
        match value {
            "succeeded" => Ok(Self::Succeeded),
            "failed" => Ok(Self::Failed),
            _ => Err(corrupt("threshold decision disposition")),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ThresholdCircuitInvocationV1 {
    pub operation_id: String,
    pub candidate: NeuralCircuitCandidateV1,
    pub parameters: ThresholdDecisionCellParametersV1,
    pub input_value_ppm: i32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ThresholdCircuitDecisionV1 {
    pub operation_id: String,
    pub run_id: String,
    pub circuit_digest: Sha256Digest,
    pub parameter_digest: Sha256Digest,
    pub input_value_ppm: i32,
    pub selected_node: String,
    pub disposition: ThresholdCircuitDispositionV1,
    pub choice_digest: Sha256Digest,
    pub chosen_at_ms: u64,
}

impl AutomationStore {
    pub async fn run_threshold_circuit_v1(
        &self,
        invocation: &ThresholdCircuitInvocationV1,
        fence: &TaskFlowFence,
        now_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<ThresholdCircuitDecisionV1, TaskFlowError> {
        validate_invocation(invocation)?;
        self.validate_taskflow_fence(fence)?;
        if lease_duration_ms < 8 {
            return Err(invalid("threshold circuit lease is too short"));
        }
        if let Some(existing) = self
            .threshold_circuit_decision_by_operation(&invocation.operation_id)
            .await?
        {
            ensure_decision_matches_invocation(&existing, invocation)?;
            let candidate = self
                .circuit_candidate_by_digest(&existing.circuit_digest)
                .await?
                .ok_or_else(|| corrupt("threshold circuit candidate is missing"))?;
            return self
                .settle_threshold_circuit_choice(
                    existing,
                    &candidate,
                    fence,
                    now_ms,
                    lease_duration_ms,
                )
                .await;
        }

        let definition = self
            .register_threshold_candidate(&invocation.candidate, now_ms)
            .await?;
        self.register_threshold_parameters(&invocation.parameters, now_ms)
            .await?;
        self.register_taskflow_definition(&definition, fence, now_ms)
            .await?;

        let run_id = threshold_run_id(
            self.taskflow_owner_agent_id().as_str(),
            &invocation.operation_id,
        );
        self.create_taskflow_run(
            &run_id,
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            &run_id,
            now_ms,
        )
        .await?;
        let claimed = self
            .claim_taskflow_run(&run_id, fence, now_ms, lease_duration_ms)
            .await?;
        if claimed.state == TaskFlowRunState::Queued {
            self.apply_taskflow_command(&TaskFlowCommand::new(
                &run_id,
                threshold_command_id("start", &invocation.candidate.circuit_digest),
                fence.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                next_command_time(&claimed, now_ms)?,
            )?)
            .await?;
        }

        let loaded = self
            .threshold_parameters_by_digest(&invocation.parameters.parameter_digest)
            .await?
            .ok_or_else(|| corrupt("threshold cell parameters are missing"))?;
        let proposed = threshold_decision(invocation, &loaded, &run_id, now_ms)?;
        let durable = self.insert_threshold_decision(&proposed).await?;
        self.settle_threshold_circuit_choice(
            durable,
            &invocation.candidate,
            fence,
            now_ms,
            lease_duration_ms,
        )
        .await
    }

    pub async fn threshold_circuit_decision_by_operation(
        &self,
        operation_id: &str,
    ) -> Result<Option<ThresholdCircuitDecisionV1>, TaskFlowError> {
        validate_text(operation_id, "operation_id")?;
        let row = sqlx::query(
            "SELECT * FROM automation_circuit_decisions
             WHERE owner_agent_id = ? AND operation_id = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(operation_id)
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        row.map(decision_from_row).transpose()
    }

    async fn insert_threshold_decision(
        &self,
        decision: &ThresholdCircuitDecisionV1,
    ) -> Result<ThresholdCircuitDecisionV1, TaskFlowError> {
        let inserted = sqlx::query(
            "INSERT INTO automation_circuit_decisions (
                 owner_agent_id, operation_id, run_id, circuit_digest,
                 parameter_digest, input_value_ppm, selected_node, disposition,
                 choice_digest, chosen_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&decision.operation_id)
        .bind(&decision.run_id)
        .bind(decision.circuit_digest.as_str())
        .bind(decision.parameter_digest.as_str())
        .bind(decision.input_value_ppm)
        .bind(&decision.selected_node)
        .bind(decision.disposition.as_str())
        .bind(decision.choice_digest.as_str())
        .bind(to_i64(decision.chosen_at_ms)?)
        .execute(self.taskflow_pool())
        .await;
        match inserted {
            Ok(_) => Ok(decision.clone()),
            Err(error) if is_constraint(&error) => {
                let existing = self
                    .threshold_circuit_decision_by_operation(&decision.operation_id)
                    .await?
                    .ok_or_else(|| TaskFlowError::Conflict("circuit choice raced".to_string()))?;
                if existing.operation_id != decision.operation_id
                    || existing.run_id != decision.run_id
                    || existing.circuit_digest != decision.circuit_digest
                    || existing.parameter_digest != decision.parameter_digest
                    || existing.input_value_ppm != decision.input_value_ppm
                    || existing.selected_node != decision.selected_node
                    || existing.disposition != decision.disposition
                    || existing.choice_digest != decision.choice_digest
                {
                    return Err(TaskFlowError::Conflict(
                        "circuit operation is bound to another choice".to_string(),
                    ));
                }
                Ok(existing)
            }
            Err(_) => Err(TaskFlowError::Unavailable),
        }
    }

    async fn settle_threshold_circuit_choice(
        &self,
        decision: ThresholdCircuitDecisionV1,
        candidate: &NeuralCircuitCandidateV1,
        fence: &TaskFlowFence,
        now_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<ThresholdCircuitDecisionV1, TaskFlowError> {
        for _ in 0..6 {
            let run = self
                .taskflow_run(&decision.run_id)
                .await?
                .ok_or_else(|| corrupt("threshold circuit run is missing"))?;
            let (definition, _) = candidate.compile_taskflow()?;
            if run.definition_digest != *definition.definition_digest() {
                return Err(corrupt(
                    "threshold recovery definition differs from recorded candidate",
                ));
            }
            if matches!(
                run.state,
                TaskFlowRunState::Succeeded | TaskFlowRunState::Failed
            ) && run.current_node != decision.selected_node
            {
                return Err(corrupt(
                    "threshold terminal route differs from recorded choice",
                ));
            }
            if run.state == TaskFlowRunState::Succeeded {
                if decision.disposition == ThresholdCircuitDispositionV1::Succeeded {
                    return Ok(decision);
                }
                return Err(corrupt("threshold decision terminal state mismatch"));
            }
            if run.state == TaskFlowRunState::Failed {
                if decision.disposition == ThresholdCircuitDispositionV1::Failed {
                    return Ok(decision);
                }
                return Err(corrupt("threshold decision terminal state mismatch"));
            }

            let run = self
                .claim_taskflow_run(&decision.run_id, fence, now_ms, lease_duration_ms)
                .await?;
            let transition = match run.state {
                TaskFlowRunState::Queued => TaskFlowTransition::Start,
                TaskFlowRunState::Running if run.current_node == candidate.entry_node => {
                    TaskFlowTransition::Wait {
                        token: decision.choice_digest.as_str().to_string(),
                        resume_node: Some(decision.selected_node.clone()),
                    }
                }
                TaskFlowRunState::Waiting if run.current_node == decision.selected_node => {
                    TaskFlowTransition::Resume {
                        token: decision.choice_digest.as_str().to_string(),
                    }
                }
                TaskFlowRunState::Running if run.current_node == decision.selected_node => {
                    match decision.disposition {
                        ThresholdCircuitDispositionV1::Succeeded => TaskFlowTransition::Succeed {
                            output_digest: decision.choice_digest.clone(),
                        },
                        ThresholdCircuitDispositionV1::Failed => TaskFlowTransition::Fail {
                            reason: "threshold_cell_selected_low".to_string(),
                        },
                    }
                }
                _ => {
                    return Err(TaskFlowError::Conflict(
                        "threshold circuit run is outside its recorded route".to_string(),
                    ));
                }
            };
            self.apply_taskflow_command(&TaskFlowCommand::new(
                &run.run_id,
                threshold_command_id(transition_phase(&transition), &decision.choice_digest),
                fence.clone(),
                run.revision,
                transition,
                next_command_time(&run, now_ms)?,
            )?)
            .await?;
        }
        Err(TaskFlowError::Conflict(
            "threshold circuit did not reach a terminal projection".to_string(),
        ))
    }
}

#[cfg(test)]
#[path = "threshold_circuit_tests.rs"]
mod tests;
