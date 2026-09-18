//! Append-only provider-contact evidence for final-use-authorized TaskFlow effects.
//!
//! These rows do not execute effects and grant no authority. The attempt row
//! only records that a verified final-use claim crossed the durable dispatch
//! boundary; the observation row records exactly one provider-owned recovery
//! fact. Keeping both immutable lets recovery repair the TaskFlow step without
//! ever inferring terminality from process-local control flow.

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;

use crate::AutomationStore;
use crate::TaskFlowError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum EffectDispatchObservationKind {
    ProvenAbsent,
    Succeeded,
    Failed,
    Indeterminate,
}

impl EffectDispatchObservationKind {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::ProvenAbsent => "proven_absent",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Indeterminate => "indeterminate",
        }
    }

    fn parse(value: &str) -> Result<Self, TaskFlowError> {
        match value {
            "proven_absent" => Ok(Self::ProvenAbsent),
            "succeeded" => Ok(Self::Succeeded),
            "failed" => Ok(Self::Failed),
            "indeterminate" => Ok(Self::Indeterminate),
            _ => Err(TaskFlowError::Corrupt(
                "unknown effect dispatch observation".to_string(),
            )),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct EffectDispatchObservation {
    pub(crate) kind: EffectDispatchObservationKind,
    pub(crate) evidence_digest: Sha256Digest,
    pub(crate) observed_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct EffectDispatchAttempt {
    pub(crate) run_id: String,
    pub(crate) step_id: String,
    pub(crate) attempt: u32,
    pub(crate) intent_digest: Sha256Digest,
    pub(crate) payload_digest: Sha256Digest,
    pub(crate) binding_digest: Sha256Digest,
    pub(crate) destination_id: String,
    pub(crate) authority_epoch: u64,
    pub(crate) grant_id: String,
    pub(crate) grant_nonce_digest: Sha256Digest,
    pub(crate) record_command_id: String,
    pub(crate) started_at_ms: u64,
    pub(crate) observation: Option<EffectDispatchObservation>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum EffectDispatchStart {
    Inserted(EffectDispatchAttempt),
    Existing(EffectDispatchAttempt),
}

impl AutomationStore {
    #[allow(clippy::too_many_arguments)]
    pub(crate) async fn begin_effect_dispatch_attempt(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        intent_digest: &Sha256Digest,
        payload_digest: &Sha256Digest,
        binding_digest: &Sha256Digest,
        destination_id: &str,
        authority_epoch: u64,
        grant_id: &str,
        grant_nonce_digest: &Sha256Digest,
        record_command_id: &str,
        started_at_ms: u64,
    ) -> Result<EffectDispatchStart, TaskFlowError> {
        let inserted = sqlx::query(
            "INSERT INTO taskflow_effect_dispatch_attempts (
                owner_agent_id, run_id, step_id, attempt, intent_digest,
                payload_digest, binding_digest, destination_id, authority_epoch,
                grant_id, grant_nonce_digest, record_command_id, started_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(step_id)
        .bind(i64::from(attempt))
        .bind(intent_digest.as_str())
        .bind(payload_digest.as_str())
        .bind(binding_digest.as_str())
        .bind(destination_id)
        .bind(to_i64(authority_epoch)?)
        .bind(grant_id)
        .bind(grant_nonce_digest.as_str())
        .bind(record_command_id)
        .bind(to_i64(started_at_ms)?)
        .execute(self.taskflow_pool())
        .await;

        match inserted {
            Ok(_) => {
                let attempt = self
                    .effect_dispatch_attempt(run_id, step_id, attempt)
                    .await?
                    .ok_or_else(|| {
                        TaskFlowError::Corrupt(
                            "effect dispatch attempt vanished after insert".to_string(),
                        )
                    })?;
                Ok(EffectDispatchStart::Inserted(attempt))
            }
            Err(error) if is_constraint(&error) => {
                let existing = self
                    .effect_dispatch_attempt(run_id, step_id, attempt)
                    .await?
                    .ok_or_else(|| {
                        TaskFlowError::Conflict(
                            "effect dispatch identity conflicts with durable evidence".to_string(),
                        )
                    })?;
                if existing.intent_digest != *intent_digest
                    || existing.payload_digest != *payload_digest
                    || existing.binding_digest != *binding_digest
                    || existing.destination_id != destination_id
                    || existing.record_command_id != record_command_id
                {
                    return Err(TaskFlowError::Conflict(
                        "effect dispatch attempt is bound to different bytes".to_string(),
                    ));
                }
                Ok(EffectDispatchStart::Existing(existing))
            }
            Err(_) => Err(TaskFlowError::Unavailable),
        }
    }

    pub(crate) async fn effect_dispatch_attempt(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
    ) -> Result<Option<EffectDispatchAttempt>, TaskFlowError> {
        let row = sqlx::query(
            "SELECT a.*, o.observation, o.evidence_digest, o.observed_at_ms
             FROM taskflow_effect_dispatch_attempts a
             LEFT JOIN taskflow_effect_dispatch_observations o
               ON o.owner_agent_id = a.owner_agent_id
              AND o.run_id = a.run_id
              AND o.step_id = a.step_id
              AND o.attempt = a.attempt
             WHERE a.owner_agent_id = ? AND a.run_id = ? AND a.step_id = ?
               AND a.attempt = ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(step_id)
        .bind(i64::from(attempt))
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        row.map(effect_attempt_from_row).transpose()
    }

    pub(crate) async fn record_effect_dispatch_observation(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        kind: EffectDispatchObservationKind,
        evidence_digest: &Sha256Digest,
        observed_at_ms: u64,
    ) -> Result<EffectDispatchAttempt, TaskFlowError> {
        let inserted = sqlx::query(
            "INSERT INTO taskflow_effect_dispatch_observations (
                owner_agent_id, run_id, step_id, attempt, observation,
                evidence_digest, observed_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(step_id)
        .bind(i64::from(attempt))
        .bind(kind.as_str())
        .bind(evidence_digest.as_str())
        .bind(to_i64(observed_at_ms)?)
        .execute(self.taskflow_pool())
        .await;

        let current = self
            .effect_dispatch_attempt(run_id, step_id, attempt)
            .await?
            .ok_or_else(|| TaskFlowError::Conflict("effect dispatch attempt is missing".to_string()))?;
        match inserted {
            Ok(_) => Ok(current),
            Err(error) if is_constraint(&error) => {
                let Some(observation) = &current.observation else {
                    return Err(TaskFlowError::Conflict(
                        "effect observation conflicts with durable evidence".to_string(),
                    ));
                };
                if observation.kind != kind
                    || observation.evidence_digest != *evidence_digest
                    || observation.observed_at_ms != observed_at_ms
                {
                    return Err(TaskFlowError::Conflict(
                        "effect observation is already bound to different bytes".to_string(),
                    ));
                }
                Ok(current)
            }
            Err(_) => Err(TaskFlowError::Unavailable),
        }
    }
}

fn effect_attempt_from_row(
    row: sqlx::sqlite::SqliteRow,
) -> Result<EffectDispatchAttempt, TaskFlowError> {
    let observation_kind: Option<String> = row
        .try_get("observation")
        .map_err(|_| TaskFlowError::Corrupt("effect observation column".to_string()))?;
    let evidence_digest: Option<String> = row
        .try_get("evidence_digest")
        .map_err(|_| TaskFlowError::Corrupt("effect evidence digest column".to_string()))?;
    let observed_at_ms: Option<i64> = row
        .try_get("observed_at_ms")
        .map_err(|_| TaskFlowError::Corrupt("effect observation timestamp column".to_string()))?;
    let observation = match (observation_kind, evidence_digest, observed_at_ms) {
        (None, None, None) => None,
        (Some(kind), Some(digest), Some(observed_at_ms)) => Some(EffectDispatchObservation {
            kind: EffectDispatchObservationKind::parse(&kind)?,
            evidence_digest: Sha256Digest::parse(digest)
                .map_err(|_| TaskFlowError::Corrupt("effect evidence digest".to_string()))?,
            observed_at_ms: to_u64(observed_at_ms)?,
        }),
        _ => {
            return Err(TaskFlowError::Corrupt(
                "partial effect dispatch observation".to_string(),
            ));
        }
    };
    Ok(EffectDispatchAttempt {
        run_id: row
            .try_get("run_id")
            .map_err(|_| TaskFlowError::Corrupt("effect run id".to_string()))?,
        step_id: row
            .try_get("step_id")
            .map_err(|_| TaskFlowError::Corrupt("effect step id".to_string()))?,
        attempt: u32::try_from(
            row.try_get::<i64, _>("attempt")
                .map_err(|_| TaskFlowError::Corrupt("effect attempt".to_string()))?,
        )
        .map_err(|_| TaskFlowError::Corrupt("effect attempt".to_string()))?,
        intent_digest: Sha256Digest::parse(
            row.try_get::<String, _>("intent_digest")
                .map_err(|_| TaskFlowError::Corrupt("effect intent digest".to_string()))?,
        )
        .map_err(|_| TaskFlowError::Corrupt("effect intent digest".to_string()))?,
        payload_digest: Sha256Digest::parse(
            row.try_get::<String, _>("payload_digest")
                .map_err(|_| TaskFlowError::Corrupt("effect payload digest".to_string()))?,
        )
        .map_err(|_| TaskFlowError::Corrupt("effect payload digest".to_string()))?,
        binding_digest: Sha256Digest::parse(
            row.try_get::<String, _>("binding_digest")
                .map_err(|_| TaskFlowError::Corrupt("effect binding digest".to_string()))?,
        )
        .map_err(|_| TaskFlowError::Corrupt("effect binding digest".to_string()))?,
        destination_id: row
            .try_get("destination_id")
            .map_err(|_| TaskFlowError::Corrupt("effect destination".to_string()))?,
        authority_epoch: to_u64(
            row.try_get("authority_epoch")
                .map_err(|_| TaskFlowError::Corrupt("effect authority epoch".to_string()))?,
        )?,
        grant_id: row
            .try_get("grant_id")
            .map_err(|_| TaskFlowError::Corrupt("effect grant id".to_string()))?,
        grant_nonce_digest: Sha256Digest::parse(
            row.try_get::<String, _>("grant_nonce_digest")
                .map_err(|_| TaskFlowError::Corrupt("effect grant nonce digest".to_string()))?,
        )
        .map_err(|_| TaskFlowError::Corrupt("effect grant nonce digest".to_string()))?,
        record_command_id: row
            .try_get("record_command_id")
            .map_err(|_| TaskFlowError::Corrupt("effect record command id".to_string()))?,
        started_at_ms: to_u64(
            row.try_get("started_at_ms")
                .map_err(|_| TaskFlowError::Corrupt("effect start timestamp".to_string()))?,
        )?,
        observation,
    })
}

fn to_u64(value: i64) -> Result<u64, TaskFlowError> {
    u64::try_from(value).map_err(|_| TaskFlowError::Corrupt("negative effect integer".to_string()))
}

fn to_i64(value: u64) -> Result<i64, TaskFlowError> {
    i64::try_from(value).map_err(|_| TaskFlowError::Invalid("effect integer overflow".to_string()))
}

fn is_constraint(error: &sqlx::Error) -> bool {
    matches!(error, sqlx::Error::Database(database) if database.is_unique_violation() || database.is_foreign_key_violation() || database.is_check_violation())
}
