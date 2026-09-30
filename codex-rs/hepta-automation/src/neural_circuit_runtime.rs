//! Durable execution metadata for versioned Neural Circuit candidates.
//!
//! This layer deliberately reuses the existing TaskFlow run owner. It records
//! activation/round identity, an exact decision receipt and a reference to a
//! Fleet-owned resource lease. It does not schedule work, mint resource
//! authority, mutate Fleet state, or reinterpret a committed TaskFlow history.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AutomationStore;
use crate::TaskFlowDefinition;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowNodeKind;
use crate::TaskFlowRun;
use crate::TaskFlowRunState;
use crate::neural_circuit_runtime_verify::activation_from_row;
use crate::neural_circuit_runtime_verify::choice_from_row;
use crate::taskflow::load_taskflow_definition_tx;
use crate::taskflow::load_taskflow_run_tx;

pub const CIRCUIT_RUNTIME_SCHEMA_VERSION: u32 = 1;
const MAX_ID_BYTES: usize = 256;
const MAX_CIRCUIT_RESOURCE_UNITS: u64 = 1_000_000_000_000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitBudgetReservationRefV1 {
    /// Stable identity issued by the Fleet/resource owner.
    pub fleet_lease_id: String,
    pub fleet_lease_revision: u64,
    pub fleet_authority_epoch: u64,
    /// Exact resource profile admitted for this circuit generation.
    pub resource_profile_digest: Sha256Digest,
    /// TaskFlow projections only. These do not reserve capacity by themselves.
    pub compute_units: u64,
    pub inference_units: u64,
    pub provider_effect_units: u64,
    pub queue_units: u64,
    pub child_units: u64,
    /// Capacity held while an external outcome remains unknown.
    pub uncertainty_units: u64,
}

impl CircuitBudgetReservationRefV1 {
    pub fn validate(&self) -> Result<(), TaskFlowError> {
        validate_id(&self.fleet_lease_id, "fleet_lease_id")?;
        if self.fleet_lease_revision == 0 || self.fleet_authority_epoch == 0 {
            return Err(invalid(
                "Fleet lease revision and authority epoch must be non-zero",
            ));
        }
        validate_digest(&self.resource_profile_digest, "resource_profile_digest")?;
        let values = [
            self.compute_units,
            self.inference_units,
            self.provider_effect_units,
            self.queue_units,
            self.child_units,
            self.uncertainty_units,
        ];
        let mut total = 0_u64;
        for value in values {
            total = total
                .checked_add(value)
                .ok_or_else(|| invalid("circuit resource projection overflow"))?;
        }
        if total == 0 || total > MAX_CIRCUIT_RESOURCE_UNITS {
            return Err(invalid(
                "circuit resource projection must be positive and bounded",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn total_units(&self) -> u64 {
        self.compute_units
            .saturating_add(self.inference_units)
            .saturating_add(self.provider_effect_units)
            .saturating_add(self.queue_units)
            .saturating_add(self.child_units)
            .saturating_add(self.uncertainty_units)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitActivationV1 {
    pub run_id: String,
    pub activation_id: String,
    pub round: u32,
    pub node_id: String,
    pub circuit_digest: Sha256Digest,
    pub taskflow_definition_digest: Sha256Digest,
    pub causal_event_digest: Sha256Digest,
    pub route_policy_digest: Sha256Digest,
    pub parameter_bundle_digest: Sha256Digest,
    pub budget: CircuitBudgetReservationRefV1,
}

impl CircuitActivationV1 {
    pub fn validate(&self) -> Result<(), TaskFlowError> {
        validate_id(&self.run_id, "run_id")?;
        validate_id(&self.activation_id, "activation_id")?;
        validate_id(&self.node_id, "node_id")?;
        if self.round == 0 || self.round > 1_000_000 {
            return Err(invalid("activation round must be in 1..=1000000"));
        }
        validate_digest(&self.circuit_digest, "circuit_digest")?;
        validate_digest(
            &self.taskflow_definition_digest,
            "taskflow_definition_digest",
        )?;
        validate_digest(&self.causal_event_digest, "causal_event_digest")?;
        validate_digest(&self.route_policy_digest, "route_policy_digest")?;
        validate_digest(&self.parameter_bundle_digest, "parameter_bundle_digest")?;
        self.budget.validate()
    }

    pub fn digest(&self) -> Result<Sha256Digest, TaskFlowError> {
        self.validate()?;
        canonical_digest(b"hepta.circuit-activation.v1\0", self)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitActivationReceiptV1 {
    pub activation_digest: Sha256Digest,
    pub command_digest: Sha256Digest,
    pub inserted: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitChoiceV1 {
    pub run_id: String,
    pub activation_id: String,
    /// Exact named output/edge selected from the admitted candidate set.
    pub selected_port: String,
    pub candidate_set_digest: Sha256Digest,
    /// Actual deterministic/stochastic behavior policy identity.
    pub behavior_policy_digest: Sha256Digest,
    /// Receipt produced by the DecisionCell/organ owner. TaskFlow never mints it.
    pub decision_receipt_digest: Sha256Digest,
}

impl CircuitChoiceV1 {
    pub fn validate(&self) -> Result<(), TaskFlowError> {
        validate_id(&self.run_id, "run_id")?;
        validate_id(&self.activation_id, "activation_id")?;
        validate_id(&self.selected_port, "selected_port")?;
        validate_digest(&self.candidate_set_digest, "candidate_set_digest")?;
        validate_digest(&self.behavior_policy_digest, "behavior_policy_digest")?;
        validate_digest(&self.decision_receipt_digest, "decision_receipt_digest")
    }

    pub fn digest(&self) -> Result<Sha256Digest, TaskFlowError> {
        self.validate()?;
        canonical_digest(b"hepta.circuit-choice.v1\0", self)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitChoiceReceiptV1 {
    pub choice_digest: Sha256Digest,
    pub command_digest: Sha256Digest,
    pub inserted: bool,
}

impl AutomationStore {
    /// Persist one causally eligible circuit activation under the current
    /// TaskFlow fence. The Fleet lease is only referenced here; the caller must
    /// have obtained and revalidated it through the Fleet owner before entry.
    pub async fn record_circuit_activation_v1(
        &self,
        activation: &CircuitActivationV1,
        fence: &TaskFlowFence,
        command_id: &str,
        now_ms: u64,
    ) -> Result<CircuitActivationReceiptV1, TaskFlowError> {
        activation.validate()?;
        validate_id(command_id, "command_id")?;
        // Acquire the writer before reading ownership. A separate pool read
        // allows takeover/termination to commit before the metadata insert.
        let mut tx = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let (run, definition) = self
            .require_current_circuit_run(&mut tx, &activation.run_id, fence, now_ms)
            .await?;
        if run.definition_digest != activation.taskflow_definition_digest {
            return Err(TaskFlowError::Conflict(
                "circuit activation compiled definition differs from the admitted TaskFlow run"
                    .to_string(),
            ));
        }
        validate_activation_definition(activation, &definition)?;
        let activation_digest = activation.digest()?;
        let command_digest = command_digest(
            b"hepta.circuit-activation-command.v1\0",
            command_id,
            &activation_digest,
            fence,
        )?;
        let result = sqlx::query(
            "INSERT OR IGNORE INTO taskflow_circuit_activations (
                owner_agent_id, run_id, activation_id, round, node_id,
                circuit_digest, taskflow_definition_digest, causal_event_digest, route_policy_digest,
                parameter_bundle_digest, resource_profile_digest,
                fleet_lease_id, fleet_lease_revision, fleet_authority_epoch,
                compute_units, inference_units, provider_effect_units, queue_units,
                child_units, uncertainty_units, command_id, command_digest,
                activation_digest, recorded_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(fence.owner_agent_id.as_str())
        .bind(&activation.run_id)
        .bind(&activation.activation_id)
        .bind(i64::from(activation.round))
        .bind(&activation.node_id)
        .bind(activation.circuit_digest.as_str())
        .bind(activation.taskflow_definition_digest.as_str())
        .bind(activation.causal_event_digest.as_str())
        .bind(activation.route_policy_digest.as_str())
        .bind(activation.parameter_bundle_digest.as_str())
        .bind(activation.budget.resource_profile_digest.as_str())
        .bind(&activation.budget.fleet_lease_id)
        .bind(to_i64(activation.budget.fleet_lease_revision)?)
        .bind(to_i64(activation.budget.fleet_authority_epoch)?)
        .bind(to_i64(activation.budget.compute_units)?)
        .bind(to_i64(activation.budget.inference_units)?)
        .bind(to_i64(activation.budget.provider_effect_units)?)
        .bind(to_i64(activation.budget.queue_units)?)
        .bind(to_i64(activation.budget.child_units)?)
        .bind(to_i64(activation.budget.uncertainty_units)?)
        .bind(command_id)
        .bind(command_digest.as_str())
        .bind(activation_digest.as_str())
        .bind(to_i64(now_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;

        let inserted = result.rows_affected() == 1;
        if !inserted {
            let row = sqlx::query(
                "SELECT * FROM taskflow_circuit_activations
                 WHERE owner_agent_id = ? AND command_id = ?",
            )
            .bind(fence.owner_agent_id.as_str())
            .bind(command_id)
            .fetch_optional(&mut *tx)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?
            .ok_or_else(|| {
                TaskFlowError::Conflict(
                    "circuit activation identity already exists under another command".to_string(),
                )
            })?;
            let stored_command: String = row.try_get("command_digest").map_err(|_| {
                TaskFlowError::Corrupt("invalid activation command digest".to_string())
            })?;
            let stored_activation: String = row
                .try_get("activation_digest")
                .map_err(|_| TaskFlowError::Corrupt("invalid activation digest".to_string()))?;
            if activation_from_row(&row)?
                .digest()
                .map_err(|_| {
                    TaskFlowError::Corrupt("invalid durable circuit activation payload".to_string())
                })?
                .as_str()
                != stored_activation
            {
                return Err(TaskFlowError::Corrupt(
                    "durable circuit activation digest mismatch".to_string(),
                ));
            }
            if stored_command != command_digest.as_str()
                || stored_activation != activation_digest.as_str()
            {
                return Err(TaskFlowError::Conflict(
                    "circuit activation command was reused with changed semantics".to_string(),
                ));
            }
        }
        tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
        Ok(CircuitActivationReceiptV1 {
            activation_digest,
            command_digest,
            inserted,
        })
    }

    /// Persist the exact branch decision before any downstream effect dispatch.
    /// Replays return the original digest; they never call a DecisionCell again.
    pub async fn record_circuit_choice_v1(
        &self,
        choice: &CircuitChoiceV1,
        fence: &TaskFlowFence,
        command_id: &str,
        now_ms: u64,
    ) -> Result<CircuitChoiceReceiptV1, TaskFlowError> {
        choice.validate()?;
        validate_id(command_id, "command_id")?;
        let mut tx = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let (_, definition) = self
            .require_current_circuit_run(&mut tx, &choice.run_id, fence, now_ms)
            .await?;
        let activation_row = sqlx::query(
            "SELECT * FROM taskflow_circuit_activations
             WHERE owner_agent_id = ? AND run_id = ? AND activation_id = ?",
        )
        .bind(fence.owner_agent_id.as_str())
        .bind(&choice.run_id)
        .bind(&choice.activation_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        let activation_row = activation_row.ok_or_else(|| {
            TaskFlowError::Conflict(
                "circuit choice requires an existing durable activation".to_string(),
            )
        })?;
        let activation = activation_from_row(&activation_row)?;
        let stored_activation_digest: String = activation_row
            .try_get("activation_digest")
            .map_err(|_| TaskFlowError::Corrupt("invalid activation digest column".to_string()))?;
        if activation
            .digest()
            .map_err(|_| {
                TaskFlowError::Corrupt("invalid durable circuit activation payload".to_string())
            })?
            .as_str()
            != stored_activation_digest
        {
            return Err(TaskFlowError::Corrupt(
                "durable circuit activation digest mismatch".to_string(),
            ));
        }
        validate_activation_definition(&activation, &definition).map_err(|_| {
            TaskFlowError::Corrupt(
                "durable circuit activation definition binding is invalid".to_string(),
            )
        })?;
        let activation_node = activation.node_id;
        if !definition
            .edges
            .iter()
            .any(|edge| edge.from == activation_node && edge.to == choice.selected_port)
        {
            return Err(TaskFlowError::Conflict(
                "circuit choice is not an outgoing edge of the durable activation".to_string(),
            ));
        }
        let choice_digest = choice.digest()?;
        let command_digest = command_digest(
            b"hepta.circuit-choice-command.v1\0",
            command_id,
            &choice_digest,
            fence,
        )?;
        let result = sqlx::query(
            "INSERT OR IGNORE INTO taskflow_circuit_choices (
                owner_agent_id, run_id, activation_id, selected_port,
                candidate_set_digest, behavior_policy_digest,
                decision_receipt_digest, command_id, command_digest,
                choice_digest, recorded_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(fence.owner_agent_id.as_str())
        .bind(&choice.run_id)
        .bind(&choice.activation_id)
        .bind(&choice.selected_port)
        .bind(choice.candidate_set_digest.as_str())
        .bind(choice.behavior_policy_digest.as_str())
        .bind(choice.decision_receipt_digest.as_str())
        .bind(command_id)
        .bind(command_digest.as_str())
        .bind(choice_digest.as_str())
        .bind(to_i64(now_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        let inserted = result.rows_affected() == 1;
        if !inserted {
            let row = sqlx::query(
                "SELECT * FROM taskflow_circuit_choices
                 WHERE owner_agent_id = ? AND command_id = ?",
            )
            .bind(fence.owner_agent_id.as_str())
            .bind(command_id)
            .fetch_optional(&mut *tx)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?
            .ok_or_else(|| {
                TaskFlowError::Conflict(
                    "circuit choice identity already exists under another command".to_string(),
                )
            })?;
            let stored_command: String = row
                .try_get("command_digest")
                .map_err(|_| TaskFlowError::Corrupt("invalid choice command digest".to_string()))?;
            let stored_choice: String = row
                .try_get("choice_digest")
                .map_err(|_| TaskFlowError::Corrupt("invalid choice digest".to_string()))?;
            if choice_from_row(&row)?
                .digest()
                .map_err(|_| {
                    TaskFlowError::Corrupt("invalid durable circuit choice payload".to_string())
                })?
                .as_str()
                != stored_choice
            {
                return Err(TaskFlowError::Corrupt(
                    "durable circuit choice digest mismatch".to_string(),
                ));
            }
            if stored_command != command_digest.as_str() || stored_choice != choice_digest.as_str()
            {
                return Err(TaskFlowError::Conflict(
                    "circuit choice command was reused with changed semantics".to_string(),
                ));
            }
        }
        tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
        Ok(CircuitChoiceReceiptV1 {
            choice_digest,
            command_digest,
            inserted,
        })
    }

    async fn require_current_circuit_run(
        &self,
        tx: &mut Transaction<'_, Sqlite>,
        run_id: &str,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<(TaskFlowRun, TaskFlowDefinition), TaskFlowError> {
        if &fence.owner_agent_id != self.taskflow_owner_agent_id() {
            return Err(TaskFlowError::StaleFence);
        }
        let run = load_taskflow_run_tx(tx, self.taskflow_owner_agent_id(), run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Conflict("TaskFlow run does not exist".to_string()))?;
        if run.owner_agent_id != fence.owner_agent_id
            || run.owner_id.as_deref() != Some(fence.owner_id.as_str())
            || run.owner_epoch != Some(fence.owner_epoch)
            || run.generation != Some(fence.generation)
            || run.fencing_token.as_deref() != Some(fence.fencing_token.as_str())
            || run
                .lease_expires_at_ms
                .is_none_or(|expiry| expiry <= now_ms)
        {
            return Err(TaskFlowError::StaleFence);
        }
        if matches!(
            run.state,
            TaskFlowRunState::Succeeded | TaskFlowRunState::Failed | TaskFlowRunState::Cancelled
        ) {
            return Err(TaskFlowError::InvalidTransition(
                "terminal TaskFlow run cannot admit another circuit activation or choice"
                    .to_string(),
            ));
        }
        let definition = load_taskflow_definition_tx(
            tx,
            self.taskflow_owner_agent_id(),
            &run.workflow_id,
            run.workflow_version,
        )
        .await?
        .ok_or_else(|| {
            TaskFlowError::Corrupt("circuit TaskFlow definition is missing".to_string())
        })?;
        if &run.definition_digest != definition.definition_digest() {
            return Err(TaskFlowError::Corrupt(
                "circuit run definition binding is corrupt".to_string(),
            ));
        }
        Ok((run, definition))
    }
}

pub(crate) use crate::neural_circuit_runtime_verify::verify_circuit_runtime_store;

pub(crate) fn validate_activation_definition(
    activation: &CircuitActivationV1,
    definition: &TaskFlowDefinition,
) -> Result<(), TaskFlowError> {
    if &activation.taskflow_definition_digest != definition.definition_digest()
        || crate::neural_circuit::circuit_policy_digest(
            &activation.route_policy_digest,
            &activation.parameter_bundle_digest,
            &activation.budget.resource_profile_digest,
            &activation.circuit_digest,
        )? != definition.policy_digest
    {
        return Err(TaskFlowError::Conflict(
            "circuit activation policy differs from the compiled TaskFlow definition".to_string(),
        ));
    }
    let node = definition
        .nodes
        .iter()
        .find(|node| node.node_id == activation.node_id)
        .ok_or_else(|| {
            TaskFlowError::Conflict(
                "circuit activation node is not in the admitted TaskFlow definition".to_string(),
            )
        })?;
    if matches!(
        node.kind,
        TaskFlowNodeKind::TerminalSuccess | TaskFlowNodeKind::TerminalFailure
    ) {
        return Err(invalid("terminal node cannot own a circuit activation"));
    }
    Ok(())
}

fn command_digest(
    domain: &[u8],
    command_id: &str,
    payload_digest: &Sha256Digest,
    fence: &TaskFlowFence,
) -> Result<Sha256Digest, TaskFlowError> {
    #[derive(Serialize)]
    struct CommandCanonical<'a> {
        command_id: &'a str,
        payload_digest: &'a Sha256Digest,
        fence: &'a TaskFlowFence,
    }
    let canonical = CommandCanonical {
        command_id,
        payload_digest,
        fence,
    };
    canonical_digest(domain, &canonical)
}

fn canonical_digest(domain: &[u8], value: &impl Serialize) -> Result<Sha256Digest, TaskFlowError> {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(
        &serde_json::to_vec(value)
            .map_err(|error| TaskFlowError::Corrupt(format!("circuit serialization: {error}")))?,
    );
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn validate_id(value: &str, field: &str) -> Result<(), TaskFlowError> {
    if value.is_empty() || value.len() > MAX_ID_BYTES || value.chars().any(char::is_control) {
        return Err(invalid(format!("{field} is invalid")));
    }
    Ok(())
}

fn validate_digest(digest: &Sha256Digest, field: &str) -> Result<(), TaskFlowError> {
    let value = digest.as_str();
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(invalid(format!(
            "{field} must be a non-zero lowercase sha256"
        )));
    }
    Ok(())
}

fn to_i64(value: u64) -> Result<i64, TaskFlowError> {
    i64::try_from(value).map_err(|_| invalid("numeric value exceeds SQLite signed range"))
}

fn invalid(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::Invalid(message.into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    fn digest(label: &str) -> Sha256Digest {
        Sha256Digest::for_bytes(label.as_bytes())
    }

    fn budget() -> CircuitBudgetReservationRefV1 {
        CircuitBudgetReservationRefV1 {
            fleet_lease_id: "fleet-lease-1".to_string(),
            fleet_lease_revision: 7,
            fleet_authority_epoch: 3,
            resource_profile_digest: digest("resource-profile"),
            compute_units: 3,
            inference_units: 2,
            provider_effect_units: 1,
            queue_units: 1,
            child_units: 2,
            uncertainty_units: 1,
        }
    }

    #[test]
    fn budget_is_a_bounded_external_lease_reference() {
        let value = budget();
        value.validate().expect("valid budget ref");
        assert_eq!(value.total_units(), 10);

        let mut invalid = value;
        invalid.fleet_lease_revision = 0;
        assert!(invalid.validate().is_err());
    }

    #[test]
    fn activation_and_choice_digests_bind_runtime_history() {
        let activation = CircuitActivationV1 {
            run_id: "run-1".to_string(),
            activation_id: "activation-1".to_string(),
            round: 2,
            node_id: "decide".to_string(),
            circuit_digest: digest("circuit"),
            taskflow_definition_digest: digest("definition"),
            causal_event_digest: digest("event"),
            route_policy_digest: digest("route"),
            parameter_bundle_digest: digest("bundle"),
            budget: budget(),
        };
        let choice = CircuitChoiceV1 {
            run_id: activation.run_id.clone(),
            activation_id: activation.activation_id.clone(),
            selected_port: "continue".to_string(),
            candidate_set_digest: digest("candidates"),
            behavior_policy_digest: digest("behavior"),
            decision_receipt_digest: digest("decision-receipt"),
        };
        assert_ne!(
            activation.digest().expect("activation digest"),
            choice.digest().expect("choice digest")
        );
    }

    async fn fixture() -> (
        tempfile::TempDir,
        AutomationStore,
        TaskFlowFence,
        CircuitActivationV1,
    ) {
        use std::fs;

        use codex_hepta_fleet::AgentManifest;
        use codex_hepta_fleet::FleetRegistry;
        use codex_hepta_fleet::ResourceBudget;
        use codex_hepta_fleet::WorkspaceBinding;
        use codex_hepta_paths::HeptaFleetRoot;

        use crate::CircuitEdgeV1;
        use crate::CircuitNodeRoleV1;
        use crate::CircuitNodeV1;
        use crate::NeuralCircuitCandidateV1;
        use crate::TaskFlowCommand;
        use crate::TaskFlowTransition;

        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical temp root");
        let fleet_path = root.join("fleet");
        let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let workspace = root.join("workspace");
        fs::create_dir(&workspace).expect("workspace");
        let workspace = workspace.canonicalize().expect("canonical workspace");
        let agent_id =
            codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c52")
                .expect("agent id");
        let resources = ResourceBudget::local_default();
        let manifest = AgentManifest::new(
            agent_id.clone(),
            WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
            resources,
        )
        .expect("manifest");
        let layout = registry.register(manifest).expect("register agent").layout;
        let store = AutomationStore::open(&layout)
            .await
            .expect("automation store");

        let circuit = NeuralCircuitCandidateV1::new(
            "runtime-test",
            1,
            None,
            "observe",
            vec![
                CircuitNodeV1::new("observe", CircuitNodeRoleV1::Observe),
                CircuitNodeV1::new("decide", CircuitNodeRoleV1::Decide),
                CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
                CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
            ],
            vec![
                CircuitEdgeV1::new("observe", "decide"),
                CircuitEdgeV1::new("decide", "success"),
                CircuitEdgeV1::new("decide", "failure"),
            ],
            vec![],
            digest("route"),
            digest("bundle"),
            digest("resource-profile"),
        )
        .expect("circuit");
        let (definition, compilation) = circuit.compile_taskflow().expect("compile");
        let fence =
            TaskFlowFence::new(agent_id, "circuit-owner", 1, 1, "circuit-fence").expect("fence");
        store
            .register_taskflow_definition(&definition, &fence, 10)
            .await
            .expect("register");
        store
            .create_taskflow_run(
                "circuit-run",
                &definition.workflow_id,
                definition.version,
                definition.definition_digest(),
                "thread-circuit",
                11,
            )
            .await
            .expect("run");
        let claimed = store
            .claim_taskflow_run("circuit-run", &fence, 12, 60_000)
            .await
            .expect("claim");
        store
            .apply_taskflow_command(
                &TaskFlowCommand::new(
                    "circuit-run",
                    "circuit-start",
                    fence.clone(),
                    claimed.revision,
                    TaskFlowTransition::Start,
                    13,
                )
                .expect("command"),
            )
            .await
            .expect("start");

        let activation = CircuitActivationV1 {
            run_id: "circuit-run".to_string(),
            activation_id: "round-1-decide".to_string(),
            round: 1,
            node_id: "decide".to_string(),
            circuit_digest: circuit.circuit_digest.clone(),
            taskflow_definition_digest: compilation.taskflow_definition_digest,
            causal_event_digest: digest("event-1"),
            route_policy_digest: circuit.route_policy_digest.clone(),
            parameter_bundle_digest: circuit.parameter_bundle_digest.clone(),
            budget: CircuitBudgetReservationRefV1 {
                resource_profile_digest: circuit.resource_profile_digest.clone(),
                ..budget()
            },
        };
        (temp, store, fence, activation)
    }

    #[tokio::test]
    async fn durable_activation_and_choice_replay_without_redeciding() {
        let (_temp, store, fence, activation) = fixture().await;
        let first = store
            .record_circuit_activation_v1(&activation, &fence, "activation-command", 14)
            .await
            .expect("activation");
        assert!(first.inserted);
        let replay = store
            .record_circuit_activation_v1(&activation, &fence, "activation-command", 15)
            .await
            .expect("activation replay");
        assert!(!replay.inserted);
        assert_eq!(replay.activation_digest, first.activation_digest);

        let choice = CircuitChoiceV1 {
            run_id: activation.run_id.clone(),
            activation_id: activation.activation_id.clone(),
            selected_port: "success".to_string(),
            candidate_set_digest: digest("candidate-set"),
            behavior_policy_digest: digest("behavior"),
            decision_receipt_digest: digest("decision-owner-receipt"),
        };
        let recorded = store
            .record_circuit_choice_v1(&choice, &fence, "choice-command", 16)
            .await
            .expect("choice");
        assert!(recorded.inserted);
        let replayed = store
            .record_circuit_choice_v1(&choice, &fence, "choice-command", 17)
            .await
            .expect("choice replay");
        assert!(!replayed.inserted);
        assert_eq!(replayed.choice_digest, recorded.choice_digest);

        let mut changed = choice;
        changed.selected_port = "failure".to_string();
        assert!(
            store
                .record_circuit_choice_v1(&changed, &fence, "choice-command", 18)
                .await
                .is_err()
        );
    }

    #[tokio::test]
    async fn circuit_activation_and_choice_reject_unadmitted_graph_and_policy() {
        let (_temp, store, fence, activation) = fixture().await;
        for field in [
            "node",
            "terminal",
            "circuit",
            "route",
            "parameters",
            "resources",
        ] {
            let mut changed = activation.clone();
            match field {
                "node" => changed.node_id = "absent".to_string(),
                "terminal" => changed.node_id = "success".to_string(),
                "circuit" => changed.circuit_digest = digest("other-circuit"),
                "route" => changed.route_policy_digest = digest("other-route"),
                "parameters" => changed.parameter_bundle_digest = digest("other-parameters"),
                "resources" => changed.budget.resource_profile_digest = digest("other-resources"),
                _ => unreachable!(),
            }
            assert!(matches!(
                store
                    .record_circuit_activation_v1(&changed, &fence, field, 14)
                    .await,
                Err(TaskFlowError::Conflict(_) | TaskFlowError::Invalid(_))
            ));
        }
        store
            .record_circuit_activation_v1(&activation, &fence, "activation", 14)
            .await
            .expect("activation");
        let choice = CircuitChoiceV1 {
            run_id: activation.run_id,
            activation_id: activation.activation_id,
            selected_port: "observe".to_string(),
            candidate_set_digest: digest("candidate-set"),
            behavior_policy_digest: digest("behavior"),
            decision_receipt_digest: digest("decision"),
        };
        assert!(matches!(
            store
                .record_circuit_choice_v1(&choice, &fence, "wrong-edge", 15)
                .await,
            Err(TaskFlowError::Conflict(_))
        ));
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM taskflow_circuit_choices")
            .fetch_one(store.taskflow_pool())
            .await
            .expect("choice count");
        assert_eq!(count, 0);
    }

    #[tokio::test]
    async fn circuit_write_revalidates_run_after_a_competing_writer_commits() {
        use std::time::Duration;

        for kind in ["activation", "choice"] {
            let (_temp, store, fence, activation) = fixture().await;
            if kind == "choice" {
                store
                    .record_circuit_activation_v1(&activation, &fence, "activation", 14)
                    .await
                    .expect("activation");
            }
            let mut writer = store
                .taskflow_pool()
                .begin_with("BEGIN IMMEDIATE")
                .await
                .expect("competing writer");
            // A concurrent writer changes the projection while the metadata
            // call is blocked. Its previously readable run snapshot must not
            // authorize a later INSERT after this transaction commits.
            sqlx::query("UPDATE taskflow_runs SET lease_expires_at_ms = 0 WHERE run_id = ?")
                .bind(&activation.run_id)
                .execute(&mut *writer)
                .await
                .expect("projection edit");
            let runtime = store.clone();
            let mut pending = tokio::spawn(async move {
                if kind == "activation" {
                    runtime
                        .record_circuit_activation_v1(&activation, &fence, "pending", 15)
                        .await
                        .map(|_| ())
                } else {
                    let choice = CircuitChoiceV1 {
                        run_id: activation.run_id,
                        activation_id: activation.activation_id,
                        selected_port: "success".to_string(),
                        candidate_set_digest: digest("candidates"),
                        behavior_policy_digest: digest("behavior"),
                        decision_receipt_digest: digest("decision"),
                    };
                    runtime
                        .record_circuit_choice_v1(&choice, &fence, "pending", 15)
                        .await
                        .map(|_| ())
                }
            });
            assert!(
                tokio::time::timeout(Duration::from_millis(100), &mut pending)
                    .await
                    .is_err()
            );
            writer.commit().await.expect("competing commit");
            assert!(matches!(
                pending.await.expect("metadata writer"),
                Err(TaskFlowError::Corrupt(_))
            ));
        }
    }

    #[tokio::test]
    async fn circuit_store_reopen_rejects_payload_corruption_beyond_first_page() {
        use crate::AutomationError;

        let (_temp, store, fence, activation) = fixture().await;
        for index in 0..129 {
            let mut next = activation.clone();
            next.activation_id = format!("activation-{index}");
            store
                .record_circuit_activation_v1(&next, &fence, &format!("activation-{index}"), 14)
                .await
                .expect("activation");
        }
        verify_circuit_runtime_store(store.taskflow_pool(), store.taskflow_owner_agent_id())
            .await
            .expect("all valid rows");
        sqlx::query("DROP TRIGGER taskflow_circuit_activations_no_update")
            .execute(store.taskflow_pool())
            .await
            .expect("simulate damaged file");
        sqlx::query("UPDATE taskflow_circuit_activations SET causal_event_digest = ? WHERE activation_id = 'activation-128'")
            .bind(digest("corrupt-event").as_str()).execute(store.taskflow_pool()).await.expect("corrupt last row");
        let mut replay = activation;
        replay.activation_id = "activation-128".to_string();
        assert!(matches!(
            store
                .record_circuit_activation_v1(&replay, &fence, "activation-128", 15)
                .await,
            Err(TaskFlowError::Corrupt(_))
        ));
        let root = store.path().parent().expect("store root").to_path_buf();
        let owner = store.taskflow_owner_agent_id().clone();
        store.close().await;
        assert!(matches!(
            AutomationStore::open_root(root, owner).await,
            Err(AutomationError::Corrupt)
        ));
    }

    #[tokio::test]
    async fn circuit_store_reopen_rejects_choice_digest_corruption() {
        use crate::AutomationError;

        let (_temp, store, fence, activation) = fixture().await;
        store
            .record_circuit_activation_v1(&activation, &fence, "activation", 14)
            .await
            .expect("activation");
        let choice = CircuitChoiceV1 {
            run_id: activation.run_id,
            activation_id: activation.activation_id,
            selected_port: "success".to_string(),
            candidate_set_digest: digest("candidate-set"),
            behavior_policy_digest: digest("behavior"),
            decision_receipt_digest: digest("decision"),
        };
        store
            .record_circuit_choice_v1(&choice, &fence, "choice", 15)
            .await
            .expect("choice");
        sqlx::query("DROP TRIGGER taskflow_circuit_choices_no_update")
            .execute(store.taskflow_pool())
            .await
            .expect("simulate damaged file");
        sqlx::query("UPDATE taskflow_circuit_choices SET decision_receipt_digest = ?")
            .bind(digest("corrupt-decision").as_str())
            .execute(store.taskflow_pool())
            .await
            .expect("corrupt choice");
        assert!(matches!(
            store
                .record_circuit_choice_v1(&choice, &fence, "choice", 16)
                .await,
            Err(TaskFlowError::Corrupt(_))
        ));
        let root = store.path().parent().expect("store root").to_path_buf();
        let owner = store.taskflow_owner_agent_id().clone();
        store.close().await;
        assert!(matches!(
            AutomationStore::open_root(root, owner).await,
            Err(AutomationError::Corrupt)
        ));
    }
}
