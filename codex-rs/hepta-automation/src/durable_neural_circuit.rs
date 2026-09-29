//! Durable Neural Circuit activation and recovery on the existing TaskFlow run.
//!
//! This module does not create a second scheduler, ledger or effect authority.
//! It appends a pre-call activation intent and reserves the remaining conserved
//! cost budget before any DecisionCell/organ/wait port is contacted. A committed
//! Wait or Effect boundary carries a resumable checkpoint. If a process dies
//! after the intent but before its receipt, automatic execution is blocked until
//! the owning runtime supplies an identity-bound recovery observation.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;

use crate::CircuitCancellationV1;
use crate::CircuitDecisionCellV1;
use crate::CircuitEffectResolutionV1;
use crate::CircuitEventIngressV1;
use crate::CircuitOrganPortV1;
use crate::CircuitRuntimeCheckpointV1;
use crate::CircuitRuntimeOutcomeV1;
use crate::CircuitRuntimeProfileV1;
use crate::CircuitTerminalStateV1;
use crate::CircuitWaitJoinPortV1;
use crate::NeuralCircuitCandidateV1;
use crate::NeuralCircuitRuntimeError;
use crate::TaskFlowCommand;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowRunState;
use crate::TaskFlowTransition;
use crate::checkpoint_for_circuit_outcome_v1;
use crate::circuit_runtime_outcome_digest_v1;
use crate::resume_neural_circuit_after_effect_v1;
use crate::resume_neural_circuit_v1;
use crate::run_neural_circuit_v1;
use crate::runtime_profile_digest_v1;
use crate::validate_circuit_runtime_outcome_v1;
use crate::AutomationError;
use crate::AutomationStore;
use crate::TimerPhase;

const CIRCUIT_TASKFLOW_LEASE_MS: u64 = 30_000;
const MAX_RUN_ID_BYTES: usize = 256;

#[derive(Debug, thiserror::Error)]
pub enum DurableNeuralCircuitError {
    #[error(transparent)]
    TaskFlow(#[from] TaskFlowError),
    #[error(transparent)]
    Runtime(#[from] NeuralCircuitRuntimeError),
    #[error(transparent)]
    Automation(#[from] AutomationError),
    #[error("durable Neural Circuit input is invalid: {0}")]
    Invalid(String),
    #[error("durable Neural Circuit identity or state conflicts: {0}")]
    Conflict(String),
    #[error("durable Neural Circuit evidence is corrupt: {0}")]
    Corrupt(String),
    #[error("durable Neural Circuit store is unavailable")]
    Unavailable,
    #[error("durable Neural Circuit activation requires owner reconciliation")]
    RecoveryRequired,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DurableCircuitCommitStatusV1 {
    Committed,
    AlreadyCommitted,
    Recovered,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DurableCircuitRunStateV1 {
    Admitted,
    Executing,
    Waiting,
    EffectPending,
    Terminal,
    RecoveryRequired,
}

impl DurableCircuitRunStateV1 {
    fn as_str(self) -> &'static str {
        match self {
            Self::Admitted => "admitted",
            Self::Executing => "executing",
            Self::Waiting => "waiting",
            Self::EffectPending => "effect_pending",
            Self::Terminal => "terminal",
            Self::RecoveryRequired => "recovery_required",
        }
    }

    fn parse(value: &str) -> Result<Self, DurableNeuralCircuitError> {
        match value {
            "admitted" => Ok(Self::Admitted),
            "executing" => Ok(Self::Executing),
            "waiting" => Ok(Self::Waiting),
            "effect_pending" => Ok(Self::EffectPending),
            "terminal" => Ok(Self::Terminal),
            "recovery_required" => Ok(Self::RecoveryRequired),
            _ => Err(DurableNeuralCircuitError::Corrupt(format!(
                "unknown durable circuit state {value:?}"
            ))),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ActivationKind {
    Start,
    ResumeWait,
    ResolveEffect,
}

impl ActivationKind {
    fn as_str(self) -> &'static str {
        match self {
            Self::Start => "start",
            Self::ResumeWait => "resume_wait",
            Self::ResolveEffect => "resolve_effect",
        }
    }

    fn parse(value: &str) -> Result<Self, DurableNeuralCircuitError> {
        match value {
            "start" => Ok(Self::Start),
            "resume_wait" => Ok(Self::ResumeWait),
            "resolve_effect" => Ok(Self::ResolveEffect),
            _ => Err(DurableNeuralCircuitError::Corrupt(format!(
                "unknown activation kind {value:?}"
            ))),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct DurableCircuitExecutionReceiptV1 {
    pub run_id: String,
    pub activation_seq: u64,
    pub status: DurableCircuitCommitStatusV1,
    pub state: DurableCircuitRunStateV1,
    pub outcome: CircuitRuntimeOutcomeV1,
    pub outcome_digest: Sha256Digest,
    pub consumed_cost_units: u64,
    pub projection_pending: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct DurableCircuitSnapshotV1 {
    pub run_id: String,
    pub circuit_digest: Sha256Digest,
    pub event_digest: Sha256Digest,
    pub runtime_profile_digest: Sha256Digest,
    pub state: DurableCircuitRunStateV1,
    pub activation_seq: u64,
    pub cost_budget_units: u64,
    pub consumed_cost_units: u64,
    pub reserved_cost_units: u64,
    pub checkpoint: Option<CircuitRuntimeCheckpointV1>,
    pub outcome: Option<CircuitRuntimeOutcomeV1>,
    pub projection_pending: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct CircuitRuntimeRecoveryRequestV1 {
    pub run_id: String,
    pub activation_seq: u64,
    pub activation_kind: String,
    pub input_digest: Sha256Digest,
    pub predecessor_checkpoint_digest: Option<Sha256Digest>,
    pub reserved_cost_units: u64,
}

#[derive(Clone, Debug)]
pub struct CircuitRuntimeRecoveredOutcomeV1 {
    pub outcome: CircuitRuntimeOutcomeV1,
    pub evidence_digest: Sha256Digest,
}

pub trait CircuitRuntimeRecoveryObserverV1 {
    fn observe(
        &mut self,
        request: &CircuitRuntimeRecoveryRequestV1,
    ) -> Result<Option<CircuitRuntimeRecoveredOutcomeV1>, NeuralCircuitRuntimeError>;
}

#[derive(Clone)]
pub(crate) struct StoredCircuit {
    pub(crate) state: DurableCircuitRunStateV1,
    pub(crate) activation_seq: u64,
    pub(crate) cost_budget_units: u64,
    pub(crate) consumed_cost_units: u64,
    pub(crate) reserved_cost_units: u64,
    pub(crate) checkpoint: Option<CircuitRuntimeCheckpointV1>,
    pub(crate) outcome: Option<CircuitRuntimeOutcomeV1>,
    pub(crate) outcome_digest: Option<Sha256Digest>,
    pub(crate) projection_pending: bool,
}

#[derive(Clone)]
struct ActivationReservation {
    activation_seq: u64,
    kind: ActivationKind,
    input_digest: Sha256Digest,
    predecessor_checkpoint: Option<CircuitRuntimeCheckpointV1>,
    reserved_cost_units: u64,
    consumed_cost_units_before: u64,
    recorded_choice_count_before: usize,
}

impl AutomationStore {
    #[allow(clippy::too_many_arguments)]
    pub async fn execute_durable_neural_circuit_v1<D, O, W, C>(
        &self,
        run_id: &str,
        thread_id: &str,
        candidate: &NeuralCircuitCandidateV1,
        event: &CircuitEventIngressV1,
        profile: &CircuitRuntimeProfileV1,
        fence: &TaskFlowFence,
        now_ms: u64,
        decision_cell: &mut D,
        organ_port: &mut O,
        wait_port: &mut W,
        cancellation: &C,
    ) -> Result<DurableCircuitExecutionReceiptV1, DurableNeuralCircuitError>
    where
        D: CircuitDecisionCellV1,
        O: CircuitOrganPortV1,
        W: CircuitWaitJoinPortV1,
        C: CircuitCancellationV1,
    {
        let stored = self
            .admit_durable_neural_circuit(
                run_id, thread_id, candidate, event, profile, fence, now_ms,
            )
            .await?;
        if stored.state == DurableCircuitRunStateV1::Executing
            || stored.state == DurableCircuitRunStateV1::RecoveryRequired
        {
            return Err(DurableNeuralCircuitError::RecoveryRequired);
        }
        if let Some(receipt) = self
            .replay_committed_circuit_outcome(
                run_id, candidate, event, profile, fence, now_ms, &stored,
            )
            .await?
        {
            return Ok(receipt);
        }
        if stored.state != DurableCircuitRunStateV1::Admitted {
            return Err(DurableNeuralCircuitError::Conflict(
                "initial circuit execution is not in admitted state".to_string(),
            ));
        }
        self.ensure_taskflow_running(run_id, fence, now_ms).await?;
        let reservation = self
            .begin_circuit_activation(
                run_id,
                ActivationKind::Start,
                DurableCircuitRunStateV1::Admitted,
                candidate,
                event,
                profile,
                None::<&CircuitEffectResolutionV1>,
                fence,
                now_ms,
            )
            .await?;
        let outcome = run_neural_circuit_v1(
            candidate,
            event,
            profile,
            decision_cell,
            organ_port,
            wait_port,
            cancellation,
        )?;
        self.commit_circuit_activation(
            run_id,
            candidate,
            event,
            profile,
            fence,
            reservation,
            outcome,
            None,
            DurableCircuitCommitStatusV1::Committed,
            now_ms,
        )
        .await
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn resume_durable_neural_circuit_wait_v1<D, O, W, C>(
        &self,
        run_id: &str,
        candidate: &NeuralCircuitCandidateV1,
        event: &CircuitEventIngressV1,
        profile: &CircuitRuntimeProfileV1,
        fence: &TaskFlowFence,
        now_ms: u64,
        decision_cell: &mut D,
        organ_port: &mut O,
        wait_port: &mut W,
        cancellation: &C,
    ) -> Result<DurableCircuitExecutionReceiptV1, DurableNeuralCircuitError>
    where
        D: CircuitDecisionCellV1,
        O: CircuitOrganPortV1,
        W: CircuitWaitJoinPortV1,
        C: CircuitCancellationV1,
    {
        let stored = self.load_exact_circuit(run_id, candidate, event, profile).await?;
        self.project_committed_circuit_outcome(run_id, fence, now_ms, &stored)
            .await?;
        if stored.state == DurableCircuitRunStateV1::Executing
            || stored.state == DurableCircuitRunStateV1::RecoveryRequired
        {
            return Err(DurableNeuralCircuitError::RecoveryRequired);
        }
        if stored.state != DurableCircuitRunStateV1::Waiting {
            return Err(DurableNeuralCircuitError::Conflict(
                "circuit is not waiting".to_string(),
            ));
        }
        let checkpoint = stored.checkpoint.clone().ok_or_else(|| {
            DurableNeuralCircuitError::Corrupt("waiting circuit has no checkpoint".to_string())
        })?;
        self.resume_taskflow_wait(run_id, fence, now_ms).await?;
        let reservation = self
            .begin_circuit_activation(
                run_id,
                ActivationKind::ResumeWait,
                DurableCircuitRunStateV1::Waiting,
                candidate,
                event,
                profile,
                None::<&CircuitEffectResolutionV1>,
                fence,
                now_ms,
            )
            .await?;
        let outcome = resume_neural_circuit_v1(
            candidate,
            event,
            profile,
            &checkpoint,
            decision_cell,
            organ_port,
            wait_port,
            cancellation,
        )?;
        self.commit_circuit_activation(
            run_id,
            candidate,
            event,
            profile,
            fence,
            reservation,
            outcome,
            None,
            DurableCircuitCommitStatusV1::Committed,
            now_ms,
        )
        .await
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn resolve_durable_neural_circuit_effect_v1<D, O, W, C>(
        &self,
        run_id: &str,
        candidate: &NeuralCircuitCandidateV1,
        event: &CircuitEventIngressV1,
        profile: &CircuitRuntimeProfileV1,
        resolution: &CircuitEffectResolutionV1,
        fence: &TaskFlowFence,
        now_ms: u64,
        decision_cell: &mut D,
        organ_port: &mut O,
        wait_port: &mut W,
        cancellation: &C,
    ) -> Result<DurableCircuitExecutionReceiptV1, DurableNeuralCircuitError>
    where
        D: CircuitDecisionCellV1,
        O: CircuitOrganPortV1,
        W: CircuitWaitJoinPortV1,
        C: CircuitCancellationV1,
    {
        let stored = self.load_exact_circuit(run_id, candidate, event, profile).await?;
        if stored.state == DurableCircuitRunStateV1::Executing
            || stored.state == DurableCircuitRunStateV1::RecoveryRequired
        {
            return Err(DurableNeuralCircuitError::RecoveryRequired);
        }
        if stored.state != DurableCircuitRunStateV1::EffectPending {
            return Err(DurableNeuralCircuitError::Conflict(
                "circuit has no committed Effect boundary".to_string(),
            ));
        }
        let checkpoint = stored.checkpoint.clone().ok_or_else(|| {
            DurableNeuralCircuitError::Corrupt(
                "effect-pending circuit has no checkpoint".to_string(),
            )
        })?;
        self.ensure_taskflow_running(run_id, fence, now_ms).await?;
        let reservation = self
            .begin_circuit_activation(
                run_id,
                ActivationKind::ResolveEffect,
                DurableCircuitRunStateV1::EffectPending,
                candidate,
                event,
                profile,
                Some(resolution),
                fence,
                now_ms,
            )
            .await?;
        let outcome = resume_neural_circuit_after_effect_v1(
            candidate,
            event,
            profile,
            &checkpoint,
            resolution,
            decision_cell,
            organ_port,
            wait_port,
            cancellation,
        )?;
        self.commit_circuit_activation(
            run_id,
            candidate,
            event,
            profile,
            fence,
            reservation,
            outcome,
            None,
            DurableCircuitCommitStatusV1::Committed,
            now_ms,
        )
        .await
    }

    pub async fn recover_durable_neural_circuit_activation_v1<R>(
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
        let stored = self.load_exact_circuit(run_id, candidate, event, profile).await?;
        if stored.state != DurableCircuitRunStateV1::Executing {
            if stored.state == DurableCircuitRunStateV1::RecoveryRequired {
                return Err(DurableNeuralCircuitError::RecoveryRequired);
            }
            return Err(DurableNeuralCircuitError::Conflict(
                "circuit has no unobserved activation".to_string(),
            ));
        }
        let row = sqlx::query(
            "SELECT activation_kind, input_digest, predecessor_checkpoint_digest,
                    reserved_cost_units, recorded_choice_count_before
             FROM neural_circuit_activation_intents
             WHERE owner_agent_id = ? AND run_id = ? AND activation_seq = ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .bind(to_i64(stored.activation_seq)?)
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| DurableNeuralCircuitError::Unavailable)?
        .ok_or_else(|| {
            DurableNeuralCircuitError::Corrupt(
                "executing circuit has no activation intent".to_string(),
            )
        })?;
        let activation_kind: String = row
            .try_get("activation_kind")
            .map_err(|_| corrupt("activation kind column"))?;
        let input_digest = parse_digest(
            row.try_get::<String, _>("input_digest")
                .map_err(|_| corrupt("activation input digest column"))?,
        )?;
        let predecessor_checkpoint_digest = row
            .try_get::<Option<String>, _>("predecessor_checkpoint_digest")
            .map_err(|_| corrupt("predecessor checkpoint column"))?
            .map(parse_digest)
            .transpose()?;
        let recorded_choice_count_before = to_usize(
            row.try_get::<i64, _>("recorded_choice_count_before")
                .map_err(|_| corrupt("recorded choice count column"))?,
        )?;
        let request = CircuitRuntimeRecoveryRequestV1 {
            run_id: run_id.to_string(),
            activation_seq: stored.activation_seq,
            activation_kind: activation_kind.clone(),
            input_digest: input_digest.clone(),
            predecessor_checkpoint_digest,
            reserved_cost_units: stored.reserved_cost_units,
        };
        self.validate_circuit_taskflow_fence(run_id, fence, now_ms)
            .await?;
        let Some(recovered) = observer.observe(&request)? else {
            self.mark_circuit_recovery_required(
                run_id,
                stored.activation_seq,
                fence,
                now_ms,
            )
            .await?;
            return Ok(None);
        };
        validate_digest_text(&recovered.evidence_digest)?;
        let reservation = ActivationReservation {
            activation_seq: stored.activation_seq,
            kind: ActivationKind::parse(&activation_kind)?,
            input_digest,
            predecessor_checkpoint: stored.checkpoint,
            reserved_cost_units: stored.reserved_cost_units,
            consumed_cost_units_before: stored.consumed_cost_units,
            recorded_choice_count_before,
        };
        self.commit_circuit_activation(
            run_id,
            candidate,
            event,
            profile,
            fence,
            reservation,
            recovered.outcome,
            Some(recovered.evidence_digest),
            DurableCircuitCommitStatusV1::Recovered,
            now_ms,
        )
        .await
        .map(Some)
    }

    pub async fn durable_neural_circuit_snapshot_v1(
        &self,
        run_id: &str,
    ) -> Result<Option<DurableCircuitSnapshotV1>, DurableNeuralCircuitError> {
        validate_run_id(run_id)?;
        let row = sqlx::query(
            "SELECT * FROM neural_circuit_runs WHERE owner_agent_id = ? AND run_id = ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| DurableNeuralCircuitError::Unavailable)?;
        row.map(|row| snapshot_from_row(&row)).transpose()
    }

    async fn admit_durable_neural_circuit(
        &self,
        run_id: &str,
        thread_id: &str,
        candidate: &NeuralCircuitCandidateV1,
        event: &CircuitEventIngressV1,
        profile: &CircuitRuntimeProfileV1,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<StoredCircuit, DurableNeuralCircuitError> {
        validate_run_id(run_id)?;
        if thread_id.is_empty()
            || thread_id.len() > MAX_RUN_ID_BYTES
            || thread_id.chars().any(char::is_control)
        {
            return Err(DurableNeuralCircuitError::Invalid(
                "thread_id is invalid".to_string(),
            ));
        }
        candidate.validate()?;
        event.validate()?;
        profile.validate()?;
        let (definition, compilation) = candidate.compile_taskflow()?;
        self.register_taskflow_definition(&definition, fence, now_ms)
            .await?;
        self.create_taskflow_run(
            run_id,
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            thread_id,
            now_ms,
        )
        .await?;
        let candidate_json = json(candidate)?;
        let event_json = json(event)?;
        let profile_json = json(profile)?;
        let profile_digest = runtime_profile_digest_v1(profile)?;
        sqlx::query(
            "INSERT OR IGNORE INTO neural_circuit_runs (
                owner_agent_id, run_id, circuit_id, circuit_version,
                circuit_digest, taskflow_definition_digest, candidate_json,
                event_digest, event_json, runtime_profile_digest,
                runtime_profile_json, state, activation_seq, cost_budget_units,
                consumed_cost_units, reserved_cost_units, checkpoint_json,
                checkpoint_digest, outcome_json, outcome_digest,
                projection_pending, created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'admitted', 0, ?, 0, 0,
                       NULL, NULL, NULL, NULL, 0, ?, ?)",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .bind(&candidate.circuit_id)
        .bind(i64::from(candidate.version))
        .bind(candidate.circuit_digest.as_str())
        .bind(compilation.taskflow_definition_digest.as_str())
        .bind(&candidate_json)
        .bind(event.event_digest.as_str())
        .bind(&event_json)
        .bind(profile_digest.as_str())
        .bind(&profile_json)
        .bind(to_i64(profile.cost_budget_units)?)
        .bind(to_i64(now_ms)?)
        .bind(to_i64(now_ms)?)
        .execute(self.taskflow_pool())
        .await
        .map_err(map_sql_write)?;
        self.load_exact_circuit(run_id, candidate, event, profile)
            .await
    }

    pub(crate) async fn load_exact_circuit(
        &self,
        run_id: &str,
        candidate: &NeuralCircuitCandidateV1,
        event: &CircuitEventIngressV1,
        profile: &CircuitRuntimeProfileV1,
    ) -> Result<StoredCircuit, DurableNeuralCircuitError> {
        validate_run_id(run_id)?;
        candidate.validate()?;
        event.validate()?;
        profile.validate()?;
        let candidate_json = json(candidate)?;
        let event_json = json(event)?;
        let profile_json = json(profile)?;
        let profile_digest = runtime_profile_digest_v1(profile)?;
        let row = sqlx::query(
            "SELECT * FROM neural_circuit_runs WHERE owner_agent_id = ? AND run_id = ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| DurableNeuralCircuitError::Unavailable)?
        .ok_or_else(|| {
            DurableNeuralCircuitError::Conflict("durable circuit run does not exist".to_string())
        })?;
        let stored_candidate_json: String = row
            .try_get("candidate_json")
            .map_err(|_| corrupt("candidate JSON column"))?;
        let stored_event_json: String = row
            .try_get("event_json")
            .map_err(|_| corrupt("event JSON column"))?;
        let stored_profile_json: String = row
            .try_get("runtime_profile_json")
            .map_err(|_| corrupt("runtime profile JSON column"))?;
        let stored_circuit_digest: String = row
            .try_get("circuit_digest")
            .map_err(|_| corrupt("circuit digest column"))?;
        let stored_event_digest: String = row
            .try_get("event_digest")
            .map_err(|_| corrupt("event digest column"))?;
        let stored_profile_digest: String = row
            .try_get("runtime_profile_digest")
            .map_err(|_| corrupt("runtime profile digest column"))?;
        if stored_candidate_json != candidate_json
            || stored_event_json != event_json
            || stored_profile_json != profile_json
            || stored_circuit_digest != candidate.circuit_digest.as_str()
            || stored_event_digest != event.event_digest.as_str()
            || stored_profile_digest != profile_digest.as_str()
        {
            return Err(DurableNeuralCircuitError::Conflict(
                "run id is already bound to another circuit, event or profile".to_string(),
            ));
        }
        stored_from_row(&row)
    }

    async fn begin_circuit_activation<T: Serialize>(
        &self,
        run_id: &str,
        kind: ActivationKind,
        expected_state: DurableCircuitRunStateV1,
        candidate: &NeuralCircuitCandidateV1,
        event: &CircuitEventIngressV1,
        profile: &CircuitRuntimeProfileV1,
        semantic_input: Option<&T>,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<ActivationReservation, DurableNeuralCircuitError> {
        let (mut tx, phase) = self.begin_timer_write().await?;
        if phase != TimerPhase::Active {
            return Err(TaskFlowError::StaleFence.into());
        }
        self.check_circuit_taskflow_fence_tx(&mut tx, run_id, fence, now_ms)
            .await?;
        let row = sqlx::query(
            "SELECT * FROM neural_circuit_runs WHERE owner_agent_id = ? AND run_id = ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| DurableNeuralCircuitError::Unavailable)?
        .ok_or_else(|| {
            DurableNeuralCircuitError::Conflict("durable circuit run does not exist".to_string())
        })?;
        let stored = stored_from_row(&row)?;
        if stored.state == DurableCircuitRunStateV1::Executing
            || stored.state == DurableCircuitRunStateV1::RecoveryRequired
        {
            return Err(DurableNeuralCircuitError::RecoveryRequired);
        }
        if stored.state != expected_state {
            return Err(DurableNeuralCircuitError::Conflict(format!(
                "activation expected {}, observed {}",
                expected_state.as_str(),
                stored.state.as_str()
            )));
        }
        let reserved_cost_units = stored
            .cost_budget_units
            .checked_sub(stored.consumed_cost_units)
            .ok_or_else(|| corrupt("consumed cost exceeds circuit budget"))?;
        if reserved_cost_units == 0 {
            return Err(NeuralCircuitRuntimeError::CostBudgetExhausted.into());
        }
        let activation_seq = stored
            .activation_seq
            .checked_add(1)
            .ok_or_else(|| corrupt("activation sequence overflow"))?;
        let predecessor_checkpoint_digest = stored
            .checkpoint
            .as_ref()
            .map(|checkpoint| checkpoint.checkpoint_digest.clone());
        let input_digest = canonical_digest(
            b"hepta.neural-circuit.durable-activation-input.v1\0",
            &(
                run_id,
                activation_seq,
                kind.as_str(),
                &candidate.circuit_digest,
                &event.event_digest,
                runtime_profile_digest_v1(profile)?,
                &predecessor_checkpoint_digest,
                semantic_input,
            ),
        )?;
        let command_id = format!("circuit:{}", input_digest.as_str());
        let recorded_choice_count_before = stored
            .checkpoint
            .as_ref()
            .map_or(0, |checkpoint| checkpoint.recorded_choices.len());
        sqlx::query(
            "INSERT INTO neural_circuit_activation_intents (
                owner_agent_id, run_id, activation_seq, activation_kind,
                command_id, input_digest, predecessor_checkpoint_digest,
                reserved_cost_units, recorded_choice_count_before, created_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .bind(to_i64(activation_seq)?)
        .bind(kind.as_str())
        .bind(&command_id)
        .bind(input_digest.as_str())
        .bind(
            predecessor_checkpoint_digest
                .as_ref()
                .map(Sha256Digest::as_str),
        )
        .bind(to_i64(reserved_cost_units)?)
        .bind(to_i64_usize(recorded_choice_count_before)?)
        .bind(to_i64(now_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(map_sql_write)?;
        let updated = sqlx::query(
            "UPDATE neural_circuit_runs
             SET state = 'executing', activation_seq = ?, reserved_cost_units = ?,
                 projection_pending = 0, updated_at_ms = ?
             WHERE owner_agent_id = ? AND run_id = ? AND state = ?
               AND activation_seq = ? AND reserved_cost_units = 0",
        )
        .bind(to_i64(activation_seq)?)
        .bind(to_i64(reserved_cost_units)?)
        .bind(to_i64(now_ms)?)
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .bind(expected_state.as_str())
        .bind(to_i64(stored.activation_seq)?)
        .execute(&mut *tx)
        .await
        .map_err(map_sql_write)?;
        if updated.rows_affected() != 1 {
            return Err(DurableNeuralCircuitError::Conflict(
                "activation reservation lost its state CAS".to_string(),
            ));
        }
        tx.commit()
            .await
            .map_err(|_| DurableNeuralCircuitError::Unavailable)?;
        Ok(ActivationReservation {
            activation_seq,
            kind,
            input_digest,
            predecessor_checkpoint: stored.checkpoint,
            reserved_cost_units,
            consumed_cost_units_before: stored.consumed_cost_units,
            recorded_choice_count_before,
        })
    }

    #[allow(clippy::too_many_arguments)]
    async fn commit_circuit_activation(
        &self,
        run_id: &str,
        candidate: &NeuralCircuitCandidateV1,
        event: &CircuitEventIngressV1,
        profile: &CircuitRuntimeProfileV1,
        fence: &TaskFlowFence,
        reservation: ActivationReservation,
        outcome: CircuitRuntimeOutcomeV1,
        recovery_evidence_digest: Option<Sha256Digest>,
        status: DurableCircuitCommitStatusV1,
        now_ms: u64,
    ) -> Result<DurableCircuitExecutionReceiptV1, DurableNeuralCircuitError> {
        validate_circuit_runtime_outcome_v1(candidate, event, profile, &outcome)?;
        validate_outcome_prefix(&reservation, &outcome)?;
        let outcome_digest =
            circuit_runtime_outcome_digest_v1(candidate, event, profile, &outcome)?;
        let outcome_json = json(&outcome)?;
        let trace = outcome.trace();
        let consumed_delta = trace
            .consumed_cost_units
            .checked_sub(reservation.consumed_cost_units_before)
            .ok_or_else(|| corrupt("runtime outcome rewound consumed cost"))?;
        if consumed_delta > reservation.reserved_cost_units {
            return Err(DurableNeuralCircuitError::Conflict(
                "runtime outcome exceeded its pre-call reservation".to_string(),
            ));
        }
        let checkpoint = checkpoint_for_circuit_outcome_v1(&outcome)?;
        let checkpoint_json = checkpoint.as_ref().map(json).transpose()?;
        let checkpoint_digest = checkpoint
            .as_ref()
            .map(|value| value.checkpoint_digest.clone());
        let (run_state, outcome_kind, projection_pending) = match &outcome {
            CircuitRuntimeOutcomeV1::Terminal(_) => {
                (DurableCircuitRunStateV1::Terminal, "terminal", true)
            }
            CircuitRuntimeOutcomeV1::WaitPending(_) => {
                (DurableCircuitRunStateV1::Waiting, "wait_pending", true)
            }
            CircuitRuntimeOutcomeV1::EffectPending(_) => (
                DurableCircuitRunStateV1::EffectPending,
                "effect_pending",
                false,
            ),
        };
        let (mut tx, _) = self.begin_timer_write().await?;
        self.check_circuit_taskflow_fence_tx(&mut tx, run_id, fence, now_ms)
            .await?;
        if let Some(existing) = sqlx::query(
            "SELECT outcome_json, outcome_digest FROM neural_circuit_activation_receipts
             WHERE owner_agent_id = ? AND run_id = ? AND activation_seq = ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .bind(to_i64(reservation.activation_seq)?)
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| DurableNeuralCircuitError::Unavailable)?
        {
            let existing_json: String = existing
                .try_get("outcome_json")
                .map_err(|_| corrupt("existing outcome JSON column"))?;
            let existing_digest: String = existing
                .try_get("outcome_digest")
                .map_err(|_| corrupt("existing outcome digest column"))?;
            if existing_json != outcome_json || existing_digest != outcome_digest.as_str() {
                return Err(DurableNeuralCircuitError::Conflict(
                    "activation receipt already exists with different bytes".to_string(),
                ));
            }
            tx.commit()
                .await
                .map_err(|_| DurableNeuralCircuitError::Unavailable)?;
            let stored = self.load_exact_circuit(run_id, candidate, event, profile).await?;
            self.project_committed_circuit_outcome(run_id, fence, now_ms, &stored)
                .await?;
            return receipt_from_stored(
                run_id,
                DurableCircuitCommitStatusV1::AlreadyCommitted,
                &stored,
            );
        }
        let state_row = sqlx::query(
            "SELECT state, activation_seq, reserved_cost_units, consumed_cost_units
             FROM neural_circuit_runs WHERE owner_agent_id = ? AND run_id = ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .fetch_optional(&mut *tx)
        .await
        .map_err(|_| DurableNeuralCircuitError::Unavailable)?
        .ok_or_else(|| corrupt("durable circuit run disappeared"))?;
        let state: String = state_row
            .try_get("state")
            .map_err(|_| corrupt("circuit state column"))?;
        let activation_seq = to_u64(
            state_row
                .try_get("activation_seq")
                .map_err(|_| corrupt("activation sequence column"))?,
        )?;
        let reserved = to_u64(
            state_row
                .try_get("reserved_cost_units")
                .map_err(|_| corrupt("reserved cost column"))?,
        )?;
        let consumed_before = to_u64(
            state_row
                .try_get("consumed_cost_units")
                .map_err(|_| corrupt("consumed cost column"))?,
        )?;
        if state != DurableCircuitRunStateV1::Executing.as_str()
            || activation_seq != reservation.activation_seq
            || reserved != reservation.reserved_cost_units
            || consumed_before != reservation.consumed_cost_units_before
        {
            return Err(DurableNeuralCircuitError::Conflict(
                "activation receipt lost its execution fence".to_string(),
            ));
        }
        sqlx::query(
            "INSERT INTO neural_circuit_activation_receipts (
                owner_agent_id, run_id, activation_seq, outcome_kind,
                outcome_json, outcome_digest, consumed_cost_delta,
                recovery_evidence_digest, committed_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .bind(to_i64(reservation.activation_seq)?)
        .bind(outcome_kind)
        .bind(&outcome_json)
        .bind(outcome_digest.as_str())
        .bind(to_i64(consumed_delta)?)
        .bind(
            recovery_evidence_digest
                .as_ref()
                .map(Sha256Digest::as_str),
        )
        .bind(to_i64(now_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(map_sql_write)?;
        for (index, choice) in trace
            .recorded_choices
            .iter()
            .enumerate()
            .skip(reservation.recorded_choice_count_before)
        {
            sqlx::query(
                "INSERT INTO neural_circuit_recorded_choices (
                    owner_agent_id, run_id, activation_seq, choice_index,
                    choice_json, receipt_digest
                 ) VALUES (?, ?, ?, ?, ?, ?)",
            )
            .bind(self.owner_agent_id().as_str())
            .bind(run_id)
            .bind(to_i64(reservation.activation_seq)?)
            .bind(to_i64_usize(index)?)
            .bind(json(choice)?)
            .bind(choice.receipt_digest.as_str())
            .execute(&mut *tx)
            .await
            .map_err(map_sql_write)?;
        }
        let updated = sqlx::query(
            "UPDATE neural_circuit_runs
             SET state = ?, consumed_cost_units = ?, reserved_cost_units = 0,
                 checkpoint_json = ?, checkpoint_digest = ?, outcome_json = ?,
                 outcome_digest = ?, projection_pending = ?, updated_at_ms = ?
             WHERE owner_agent_id = ? AND run_id = ? AND state = 'executing'
               AND activation_seq = ? AND reserved_cost_units = ?",
        )
        .bind(run_state.as_str())
        .bind(to_i64(trace.consumed_cost_units)?)
        .bind(checkpoint_json.as_deref())
        .bind(checkpoint_digest.as_ref().map(Sha256Digest::as_str))
        .bind(&outcome_json)
        .bind(outcome_digest.as_str())
        .bind(if projection_pending { 1_i64 } else { 0_i64 })
        .bind(to_i64(now_ms)?)
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .bind(to_i64(reservation.activation_seq)?)
        .bind(to_i64(reservation.reserved_cost_units)?)
        .execute(&mut *tx)
        .await
        .map_err(map_sql_write)?;
        if updated.rows_affected() != 1 {
            return Err(DurableNeuralCircuitError::Conflict(
                "activation commit lost its state CAS".to_string(),
            ));
        }
        tx.commit()
            .await
            .map_err(|_| DurableNeuralCircuitError::Unavailable)?;
        let stored = self.load_exact_circuit(run_id, candidate, event, profile).await?;
        self.project_committed_circuit_outcome(run_id, fence, now_ms, &stored)
            .await?;
        let projected = self.load_exact_circuit(run_id, candidate, event, profile).await?;
        receipt_from_stored(run_id, status, &projected)
    }

    async fn replay_committed_circuit_outcome(
        &self,
        run_id: &str,
        candidate: &NeuralCircuitCandidateV1,
        event: &CircuitEventIngressV1,
        profile: &CircuitRuntimeProfileV1,
        fence: &TaskFlowFence,
        now_ms: u64,
        stored: &StoredCircuit,
    ) -> Result<Option<DurableCircuitExecutionReceiptV1>, DurableNeuralCircuitError> {
        let Some(outcome) = stored.outcome.as_ref() else {
            return Ok(None);
        };
        let receipt = sqlx::query(
            "SELECT outcome_digest FROM neural_circuit_activation_receipts
             WHERE owner_agent_id = ? AND run_id = ? AND activation_seq = ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .bind(to_i64(stored.activation_seq)?)
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| DurableNeuralCircuitError::Unavailable)?
        .ok_or_else(|| corrupt("committed circuit outcome has no activation receipt"))?;
        let receipt_digest: String = receipt
            .try_get("outcome_digest")
            .map_err(|_| corrupt("activation receipt digest column"))?;
        if stored.outcome_digest.as_ref().map(Sha256Digest::as_str)
            != Some(receipt_digest.as_str())
        {
            return Err(corrupt(
                "committed circuit outcome does not match its activation receipt",
            ));
        }
        validate_circuit_runtime_outcome_v1(candidate, event, profile, outcome)?;
        self.project_committed_circuit_outcome(run_id, fence, now_ms, stored)
            .await?;
        let projected = self.load_exact_circuit(run_id, candidate, event, profile).await?;
        receipt_from_stored(
            run_id,
            DurableCircuitCommitStatusV1::AlreadyCommitted,
            &projected,
        )
        .map(Some)
    }

    pub(crate) async fn ensure_taskflow_running(
        &self,
        run_id: &str,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<(), DurableNeuralCircuitError> {
        let run = self
            .taskflow_run(run_id)
            .await?
            .ok_or_else(|| corrupt("TaskFlow run is missing"))?;
        if !matches!(run.state, TaskFlowRunState::Queued | TaskFlowRunState::Running) {
            return Err(DurableNeuralCircuitError::Conflict(
                "TaskFlow run is not executable".to_string(),
            ));
        }
        let claimed = self
            .claim_taskflow_run(run_id, fence, now_ms, CIRCUIT_TASKFLOW_LEASE_MS)
            .await?;
        if claimed.state == TaskFlowRunState::Queued {
            self.apply_taskflow_command(&TaskFlowCommand::new(
                run_id,
                command_id(b"circuit-start", run_id, 0),
                fence.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                now_ms,
            )?)
            .await?;
        }
        Ok(())
    }

    async fn resume_taskflow_wait(
        &self,
        run_id: &str,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<(), DurableNeuralCircuitError> {
        let run = self
            .taskflow_run(run_id)
            .await?
            .ok_or_else(|| corrupt("TaskFlow run is missing"))?;
        if run.state == TaskFlowRunState::Running {
            return Ok(());
        }
        if run.state != TaskFlowRunState::Waiting {
            return Err(DurableNeuralCircuitError::Conflict(
                "TaskFlow run is not waiting".to_string(),
            ));
        }
        let claimed = self
            .claim_taskflow_run(run_id, fence, now_ms, CIRCUIT_TASKFLOW_LEASE_MS)
            .await?;
        let token = claimed
            .wait_token
            .clone()
            .ok_or_else(|| corrupt("waiting TaskFlow run has no wait token"))?;
        self.apply_taskflow_command(&TaskFlowCommand::new(
            run_id,
            command_id(b"circuit-resume", run_id, claimed.revision),
            fence.clone(),
            claimed.revision,
            TaskFlowTransition::Resume { token },
            now_ms,
        )?)
        .await?;
        Ok(())
    }

    async fn project_committed_circuit_outcome(
        &self,
        run_id: &str,
        fence: &TaskFlowFence,
        now_ms: u64,
        stored: &StoredCircuit,
    ) -> Result<(), DurableNeuralCircuitError> {
        if !stored.projection_pending {
            return Ok(());
        }
        let outcome = stored
            .outcome
            .as_ref()
            .ok_or_else(|| corrupt("projection is pending without an outcome"))?;
        let mut run = self
            .taskflow_run(run_id)
            .await?
            .ok_or_else(|| corrupt("TaskFlow run is missing"))?;
        let transition = match outcome {
            CircuitRuntimeOutcomeV1::WaitPending(boundary) => {
                if run.state == TaskFlowRunState::Waiting
                    && run.wait_token.as_deref() == Some(boundary.boundary_digest.as_str())
                {
                    self.clear_circuit_projection_pending(
                    run_id,
                    stored.activation_seq,
                    fence,
                    now_ms,
                )
                    .await?;
                    return Ok(());
                }
                TaskFlowTransition::Wait {
                    token: boundary.boundary_digest.as_str().to_string(),
                    resume_node: None,
                }
            }
            CircuitRuntimeOutcomeV1::Terminal(receipt) => {
                if matches!(
                    run.state,
                    TaskFlowRunState::Succeeded
                        | TaskFlowRunState::Failed
                        | TaskFlowRunState::Cancelled
                ) {
                    if !self
                        .taskflow_terminal_matches_circuit(run_id, receipt)
                        .await?
                    {
                        return Err(DurableNeuralCircuitError::Conflict(
                            "TaskFlow terminal projection conflicts with the circuit receipt"
                                .to_string(),
                        ));
                    }
                    self.clear_circuit_projection_pending(
                    run_id,
                    stored.activation_seq,
                    fence,
                    now_ms,
                )
                    .await?;
                    return Ok(());
                }
                match receipt.state {
                    CircuitTerminalStateV1::Succeeded => TaskFlowTransition::Succeed {
                        output_digest: receipt.receipt_digest.clone(),
                    },
                    CircuitTerminalStateV1::Failed => TaskFlowTransition::Fail {
                        reason: format!("circuit:{}", receipt.receipt_digest.as_str()),
                    },
                    CircuitTerminalStateV1::Cancelled => TaskFlowTransition::Cancel {
                        reason: format!("circuit:{}", receipt.receipt_digest.as_str()),
                    },
                }
            }
            CircuitRuntimeOutcomeV1::EffectPending(_) => {
                self.clear_circuit_projection_pending(
                    run_id,
                    stored.activation_seq,
                    fence,
                    now_ms,
                )
                    .await?;
                return Ok(());
            }
        };
        if run.lease_expires_at_ms.is_none_or(|expires| expires <= now_ms) {
            run = self
                .claim_taskflow_run(run_id, fence, now_ms, CIRCUIT_TASKFLOW_LEASE_MS)
                .await?;
        }
        let outcome_digest = stored
            .outcome_digest
            .as_ref()
            .ok_or_else(|| corrupt("projection outcome digest is missing"))?;
        self.apply_taskflow_command(&TaskFlowCommand::new(
            run_id,
            format!("circuit-project:{}", outcome_digest.as_str()),
            fence.clone(),
            run.revision,
            transition,
            now_ms,
        )?)
        .await?;
        self.clear_circuit_projection_pending(
            run_id,
            stored.activation_seq,
            fence,
            now_ms,
        )
        .await
    }

    async fn clear_circuit_projection_pending(
        &self,
        run_id: &str,
        activation_seq: u64,
        _fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<(), DurableNeuralCircuitError> {
        let (mut tx, _) = self.begin_timer_write().await?;
        let result = sqlx::query(
            "UPDATE neural_circuit_runs SET projection_pending = 0, updated_at_ms = ?
             WHERE owner_agent_id = ? AND run_id = ? AND activation_seq = ?",
        )
        .bind(to_i64(now_ms)?)
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .bind(to_i64(activation_seq)?)
        .execute(&mut *tx)
        .await
        .map_err(map_sql_write)?;
        if result.rows_affected() != 1 {
            return Err(DurableNeuralCircuitError::Conflict(
                "projection acknowledgement lost its activation fence".to_string(),
            ));
        }
        tx.commit()
            .await
            .map_err(|_| DurableNeuralCircuitError::Unavailable)?;
        Ok(())
    }

    pub(crate) async fn validate_circuit_taskflow_fence(
        &self,
        run_id: &str,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<(), DurableNeuralCircuitError> {
        let (mut tx, _) = self.begin_timer_write().await?;
        self.check_circuit_taskflow_fence_tx(&mut tx, run_id, fence, now_ms)
            .await?;
        tx.commit()
            .await
            .map_err(|_| DurableNeuralCircuitError::Unavailable)
    }

    pub(crate) async fn check_circuit_taskflow_fence_tx(
        &self,
        tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
        run_id: &str,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<(), DurableNeuralCircuitError> {
        if fence.owner_agent_id != *self.owner_agent_id() {
            return Err(TaskFlowError::StaleFence.into());
        }
        let row = sqlx::query(
            "SELECT state, owner_id, owner_epoch, generation, fencing_token,
                    lease_expires_at_ms, cancel_requested
             FROM taskflow_runs WHERE owner_agent_id = ? AND run_id = ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .fetch_optional(&mut **tx)
        .await
        .map_err(|_| DurableNeuralCircuitError::Unavailable)?
        .ok_or_else(|| corrupt("TaskFlow run is missing"))?;
        let state: String = row
            .try_get("state")
            .map_err(|_| corrupt("TaskFlow state column"))?;
        let owner_id: Option<String> = row
            .try_get("owner_id")
            .map_err(|_| corrupt("TaskFlow owner column"))?;
        let owner_epoch: Option<i64> = row
            .try_get("owner_epoch")
            .map_err(|_| corrupt("TaskFlow owner epoch column"))?;
        let generation: Option<i64> = row
            .try_get("generation")
            .map_err(|_| corrupt("TaskFlow generation column"))?;
        let fencing_token: Option<String> = row
            .try_get("fencing_token")
            .map_err(|_| corrupt("TaskFlow fencing token column"))?;
        let lease_expires_at_ms: Option<i64> = row
            .try_get("lease_expires_at_ms")
            .map_err(|_| corrupt("TaskFlow lease column"))?;
        let cancel_requested: i64 = row
            .try_get("cancel_requested")
            .map_err(|_| corrupt("TaskFlow cancellation column"))?;
        let now_i64 = to_i64(now_ms)?;
        if state != "running"
            || owner_id.as_deref() != Some(fence.owner_id.as_str())
            || owner_epoch != Some(to_i64(fence.owner_epoch)?)
            || generation != Some(to_i64(fence.generation)?)
            || fencing_token.as_deref() != Some(fence.fencing_token.as_str())
            || lease_expires_at_ms.is_none_or(|expires| expires <= now_i64)
            || cancel_requested != 0
        {
            return Err(TaskFlowError::StaleFence.into());
        }
        Ok(())
    }

    async fn taskflow_terminal_matches_circuit(
        &self,
        run_id: &str,
        receipt: &crate::CircuitTerminalReceiptV1,
    ) -> Result<bool, DurableNeuralCircuitError> {
        let row = sqlx::query(
            "SELECT transition, payload_json FROM taskflow_events
             WHERE owner_agent_id = ? AND run_id = ?
             ORDER BY event_seq DESC LIMIT 1",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| DurableNeuralCircuitError::Unavailable)?
        .ok_or_else(|| corrupt("terminal TaskFlow run has no event"))?;
        let transition: String = row
            .try_get("transition")
            .map_err(|_| corrupt("terminal TaskFlow transition column"))?;
        let payload_json: String = row
            .try_get("payload_json")
            .map_err(|_| corrupt("terminal TaskFlow payload column"))?;
        let payload: TaskFlowTransition = serde_json::from_str(&payload_json)
            .map_err(|_| corrupt("terminal TaskFlow payload is invalid"))?;
        let expected_reason = format!("circuit:{}", receipt.receipt_digest.as_str());
        Ok(match (&receipt.state, transition.as_str(), payload) {
            (
                CircuitTerminalStateV1::Succeeded,
                "succeeded",
                TaskFlowTransition::Succeed { output_digest },
            ) => output_digest == receipt.receipt_digest,
            (
                CircuitTerminalStateV1::Failed,
                "failed",
                TaskFlowTransition::Fail { reason },
            ) => reason == expected_reason,
            (
                CircuitTerminalStateV1::Cancelled,
                "cancelled",
                TaskFlowTransition::Cancel { reason },
            ) => reason == expected_reason,
            _ => false,
        })
    }

    async fn mark_circuit_recovery_required(
        &self,
        run_id: &str,
        activation_seq: u64,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<(), DurableNeuralCircuitError> {
        let (mut tx, _) = self.begin_timer_write().await?;
        self.check_circuit_taskflow_fence_tx(&mut tx, run_id, fence, now_ms)
            .await?;
        let result = sqlx::query(
            "UPDATE neural_circuit_runs
             SET state = 'recovery_required', reserved_cost_units = 0, updated_at_ms = ?
             WHERE owner_agent_id = ? AND run_id = ? AND state = 'executing'
               AND activation_seq = ?",
        )
        .bind(to_i64(now_ms)?)
        .bind(self.owner_agent_id().as_str())
        .bind(run_id)
        .bind(to_i64(activation_seq)?)
        .execute(&mut *tx)
        .await
        .map_err(map_sql_write)?;
        if result.rows_affected() != 1 {
            return Err(DurableNeuralCircuitError::Conflict(
                "recovery-required transition lost its activation fence".to_string(),
            ));
        }
        tx.commit()
            .await
            .map_err(|_| DurableNeuralCircuitError::Unavailable)?;
        Ok(())
    }
}

fn stored_from_row(row: &sqlx::sqlite::SqliteRow) -> Result<StoredCircuit, DurableNeuralCircuitError> {
    let state = DurableCircuitRunStateV1::parse(
        row.try_get::<String, _>("state")
            .map_err(|_| corrupt("circuit state column"))?
            .as_str(),
    )?;
    let checkpoint = row
        .try_get::<Option<String>, _>("checkpoint_json")
        .map_err(|_| corrupt("checkpoint JSON column"))?
        .map(|value| parse_json(&value, "checkpoint JSON"))
        .transpose()?;
    let outcome = row
        .try_get::<Option<String>, _>("outcome_json")
        .map_err(|_| corrupt("outcome JSON column"))?
        .map(|value| parse_json(&value, "outcome JSON"))
        .transpose()?;
    let outcome_digest = row
        .try_get::<Option<String>, _>("outcome_digest")
        .map_err(|_| corrupt("outcome digest column"))?
        .map(parse_digest)
        .transpose()?;
    Ok(StoredCircuit {
        state,
        activation_seq: to_u64(
            row.try_get("activation_seq")
                .map_err(|_| corrupt("activation sequence column"))?,
        )?,
        cost_budget_units: to_u64(
            row.try_get("cost_budget_units")
                .map_err(|_| corrupt("cost budget column"))?,
        )?,
        consumed_cost_units: to_u64(
            row.try_get("consumed_cost_units")
                .map_err(|_| corrupt("consumed cost column"))?,
        )?,
        reserved_cost_units: to_u64(
            row.try_get("reserved_cost_units")
                .map_err(|_| corrupt("reserved cost column"))?,
        )?,
        checkpoint,
        outcome,
        outcome_digest,
        projection_pending: row
            .try_get::<i64, _>("projection_pending")
            .map_err(|_| corrupt("projection pending column"))?
            != 0,
    })
}

fn snapshot_from_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<DurableCircuitSnapshotV1, DurableNeuralCircuitError> {
    let stored = stored_from_row(row)?;
    Ok(DurableCircuitSnapshotV1 {
        run_id: row
            .try_get("run_id")
            .map_err(|_| corrupt("run id column"))?,
        circuit_digest: parse_digest(
            row.try_get("circuit_digest")
                .map_err(|_| corrupt("circuit digest column"))?,
        )?,
        event_digest: parse_digest(
            row.try_get("event_digest")
                .map_err(|_| corrupt("event digest column"))?,
        )?,
        runtime_profile_digest: parse_digest(
            row.try_get("runtime_profile_digest")
                .map_err(|_| corrupt("runtime profile digest column"))?,
        )?,
        state: stored.state,
        activation_seq: stored.activation_seq,
        cost_budget_units: stored.cost_budget_units,
        consumed_cost_units: stored.consumed_cost_units,
        reserved_cost_units: stored.reserved_cost_units,
        checkpoint: stored.checkpoint,
        outcome: stored.outcome,
        projection_pending: stored.projection_pending,
    })
}

fn receipt_from_stored(
    run_id: &str,
    status: DurableCircuitCommitStatusV1,
    stored: &StoredCircuit,
) -> Result<DurableCircuitExecutionReceiptV1, DurableNeuralCircuitError> {
    Ok(DurableCircuitExecutionReceiptV1 {
        run_id: run_id.to_string(),
        activation_seq: stored.activation_seq,
        status,
        state: stored.state,
        outcome: stored
            .outcome
            .clone()
            .ok_or_else(|| corrupt("committed circuit has no outcome"))?,
        outcome_digest: stored
            .outcome_digest
            .clone()
            .ok_or_else(|| corrupt("committed circuit has no outcome digest"))?,
        consumed_cost_units: stored.consumed_cost_units,
        projection_pending: stored.projection_pending,
    })
}

fn validate_outcome_prefix(
    reservation: &ActivationReservation,
    outcome: &CircuitRuntimeOutcomeV1,
) -> Result<(), DurableNeuralCircuitError> {
    let trace = outcome.trace();
    if trace.consumed_cost_units < reservation.consumed_cost_units_before
        || trace.recorded_choices.len() < reservation.recorded_choice_count_before
    {
        return Err(DurableNeuralCircuitError::Conflict(
            "runtime outcome rewound its durable predecessor".to_string(),
        ));
    }
    if let Some(checkpoint) = reservation.predecessor_checkpoint.as_ref() {
        if trace.recorded_choices[..reservation.recorded_choice_count_before]
            != checkpoint.recorded_choices
            || trace.observation_digests.len() < checkpoint.observation_digests.len()
            || trace.observation_digests[..checkpoint.observation_digests.len()]
                != checkpoint.observation_digests
            || trace.steps < checkpoint.steps
            || trace.depth < checkpoint.depth
        {
            return Err(DurableNeuralCircuitError::Conflict(
                "runtime outcome does not extend the committed checkpoint".to_string(),
            ));
        }
    }
    Ok(())
}

fn outcome_kind(outcome: &CircuitRuntimeOutcomeV1) -> &'static str {
    match outcome {
        CircuitRuntimeOutcomeV1::Terminal(_) => "terminal",
        CircuitRuntimeOutcomeV1::WaitPending(_) => "wait_pending",
        CircuitRuntimeOutcomeV1::EffectPending(_) => "effect_pending",
    }
}

fn validate_run_id(value: &str) -> Result<(), DurableNeuralCircuitError> {
    if value.is_empty() || value.len() > MAX_RUN_ID_BYTES || value.chars().any(char::is_control) {
        return Err(DurableNeuralCircuitError::Invalid(
            "run_id is invalid".to_string(),
        ));
    }
    Ok(())
}

fn command_id(domain: &[u8], run_id: &str, revision: u64) -> String {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(run_id.as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(&revision.to_be_bytes());
    format!("circuit:{}", Sha256Digest::for_bytes(&bytes).as_str())
}

fn canonical_digest<T: Serialize>(
    domain: &[u8],
    value: &T,
) -> Result<Sha256Digest, DurableNeuralCircuitError> {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(
        &serde_json::to_vec(value).map_err(|error| {
            DurableNeuralCircuitError::Invalid(format!("canonical serialization: {error}"))
        })?,
    );
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn json<T: Serialize>(value: &T) -> Result<String, DurableNeuralCircuitError> {
    serde_json::to_string(value).map_err(|error| {
        DurableNeuralCircuitError::Invalid(format!("JSON serialization failed: {error}"))
    })
}

fn parse_json<T: for<'de> Deserialize<'de>>(
    value: &str,
    field: &str,
) -> Result<T, DurableNeuralCircuitError> {
    serde_json::from_str(value)
        .map_err(|error| DurableNeuralCircuitError::Corrupt(format!("{field}: {error}")))
}

fn parse_digest(value: String) -> Result<Sha256Digest, DurableNeuralCircuitError> {
    Sha256Digest::parse(value).map_err(DurableNeuralCircuitError::Corrupt)
}

fn validate_digest_text(value: &Sha256Digest) -> Result<(), DurableNeuralCircuitError> {
    let text = value.as_str();
    if text.len() != 64
        || !text
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        || text.bytes().all(|byte| byte == b'0')
    {
        return Err(DurableNeuralCircuitError::Invalid(
            "evidence digest must be a non-zero lowercase sha256".to_string(),
        ));
    }
    Ok(())
}

fn to_i64(value: u64) -> Result<i64, DurableNeuralCircuitError> {
    i64::try_from(value)
        .map_err(|_| DurableNeuralCircuitError::Invalid("numeric value exceeds SQLite".to_string()))
}

fn to_i64_usize(value: usize) -> Result<i64, DurableNeuralCircuitError> {
    i64::try_from(value)
        .map_err(|_| DurableNeuralCircuitError::Invalid("numeric value exceeds SQLite".to_string()))
}

fn to_u64(value: i64) -> Result<u64, DurableNeuralCircuitError> {
    u64::try_from(value).map_err(|_| corrupt("negative durable numeric value"))
}

fn to_usize(value: i64) -> Result<usize, DurableNeuralCircuitError> {
    usize::try_from(value).map_err(|_| corrupt("invalid durable collection size"))
}

fn map_sql_write(error: sqlx::Error) -> DurableNeuralCircuitError {
    if matches!(&error, sqlx::Error::Database(database) if database.is_unique_violation()) {
        DurableNeuralCircuitError::Conflict("durable circuit write raced or duplicated".to_string())
    } else {
        DurableNeuralCircuitError::Unavailable
    }
}

fn corrupt(message: impl Into<String>) -> DurableNeuralCircuitError {
    DurableNeuralCircuitError::Corrupt(message.into())
}
