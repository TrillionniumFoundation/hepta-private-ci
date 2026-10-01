//! Append-only provider-contact evidence for final-use-authorized TaskFlow effects.
//!
//! These rows do not execute effects and grant no authority. The attempt row
//! only records that a verified final-use claim crossed the durable dispatch
//! boundary; the observation row records exactly one provider-owned recovery
//! fact. Keeping both immutable lets recovery repair the TaskFlow step without
//! ever inferring terminality from process-local control flow.

use crate::AuthorizedProviderDispatchStatus;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;

use crate::AutomationStore;
use crate::TaskFlowError;
use crate::TaskFlowFence;

// Observation and projection are separate crash cuts. An independently
// settled step must not be contradicted by newly appended immutable evidence.
const TERMINAL_STEP_OBSERVATION_GUARD: &str = "WHERE NOT EXISTS (
       SELECT 1 FROM taskflow_step_outbox s
       WHERE s.owner_agent_id = ? AND s.run_id = ? AND s.step_id = ? AND s.attempt = ?
         AND (s.final_outcome IS NOT NULL OR s.observation IN ('succeeded', 'failed'))
         AND (s.receipt_digest != ? OR
              CASE WHEN s.final_outcome = 'cancelled' THEN 'proven_absent'
                   ELSE COALESCE(s.final_outcome, s.observation) END != ?)
         AND NOT EXISTS (
           SELECT 1 FROM taskflow_step_outbox n
           WHERE n.owner_agent_id = s.owner_agent_id AND n.run_id = s.run_id
             AND n.step_id = s.step_id AND n.attempt = s.attempt AND n.event_seq > s.event_seq
         )
     )";

// Serialize acceptance versus rejection/absence in the same SQLite write.
const PROVIDER_CONTINUITY_GUARD: &str = "AND NOT EXISTS (
    SELECT 1 FROM taskflow_effect_dispatch_attempts a
    LEFT JOIN taskflow_effect_dispatch_observations o
      USING (owner_agent_id, run_id, step_id, attempt)
    LEFT JOIN taskflow_effect_provider_acceptances w
      USING (owner_agent_id, run_id, step_id, attempt)
    WHERE a.owner_agent_id = ? AND a.run_id = ? AND a.step_id = ? AND a.attempt = ?
      AND ((? AND (w.run_id IS NOT NULL OR o.provider_dispatch_status = 'accepted'))
           OR (? AND COALESCE(o.provider_dispatch_status, '') != 'unknown'))
)";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum EffectProviderObservation {
    Dispatch(AuthorizedProviderDispatchStatus),
    Lookup(ProviderEffectAckStatus),
}

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
    pub(crate) owner_agent_id: AgentId,
    pub(crate) provider_key_version: u32,
    pub(crate) provider_contract_binding: Option<Sha256Digest>,
    pub(crate) provider_dispatch_status: Option<AuthorizedProviderDispatchStatus>,
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
        admitted_at: impl FnOnce() -> Result<u64, TaskFlowError> + Send,
        fence: &TaskFlowFence,
        provider_contract_binding: Option<&Sha256Digest>,
    ) -> Result<EffectDispatchStart, TaskFlowError> {
        if fence.owner_agent_id != *self.taskflow_owner_agent_id() {
            return Err(TaskFlowError::StaleFence);
        }
        // Acquire the writer before sampling the injected logical clock.
        // A queued SQLite write must not admit using a pre-wait lease time.
        let mut tx = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let started_at_ms = admitted_at()?;
        let inserted = sqlx::query(
            "INSERT INTO taskflow_effect_dispatch_attempts (
                owner_agent_id, run_id, step_id, attempt, intent_digest,
                payload_digest, binding_digest, destination_id, authority_epoch,
                grant_id, grant_nonce_digest, record_command_id, started_at_ms,
                provider_key_version, provider_contract_binding
             ) SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 2, ?
               WHERE EXISTS (
                 SELECT 1 FROM taskflow_runs
                 WHERE owner_agent_id = ? AND run_id = ? AND state = 'running'
                   AND owner_id = ? AND owner_epoch = ? AND generation = ?
                   AND fencing_token = ? AND lease_expires_at_ms > ?
               ) AND EXISTS (
                 SELECT 1 FROM taskflow_step_outbox s
                 WHERE s.owner_agent_id = ? AND s.run_id = ? AND s.step_id = ?
                   AND s.attempt = ? AND s.event_kind = 'claimed'
                   AND s.intent_digest = ? AND s.payload_digest = ?
                   AND NOT EXISTS (
                     SELECT 1 FROM taskflow_step_outbox n
                     WHERE n.owner_agent_id = s.owner_agent_id AND n.run_id = s.run_id
                       AND n.step_id = s.step_id AND n.attempt = s.attempt
                       AND n.event_seq > s.event_seq
                   )
               ) AND NOT EXISTS (
                 SELECT 1 FROM taskflow_step_outbox
                 WHERE owner_agent_id = ? AND run_id = ? AND step_id = ?
                   AND attempt = ? AND command_id = ?
               )",
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
        .bind(provider_contract_binding.map(Sha256Digest::as_str))
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(&fence.owner_id)
        .bind(to_i64(fence.owner_epoch)?)
        .bind(to_i64(fence.generation)?)
        .bind(&fence.fencing_token)
        .bind(to_i64(started_at_ms)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(step_id)
        .bind(i64::from(attempt))
        .bind(intent_digest.as_str())
        .bind(payload_digest.as_str())
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(step_id)
        .bind(i64::from(attempt))
        .bind(record_command_id)
        .execute(&mut *tx)
        .await;
        // Release the reservation before the replay/read paths use the pool.
        tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;

        match inserted {
            Ok(result) => {
                if result.rows_affected() == 0 {
                    return Err(TaskFlowError::StaleFence);
                }
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
                    || existing.provider_contract_binding.as_ref() != provider_contract_binding
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
            "SELECT a.*,
                    COALESCE(r.observation, o.observation) AS observation,
                    COALESCE(r.evidence_digest, o.evidence_digest) AS evidence_digest,
                    COALESCE(r.observed_at_ms, o.observed_at_ms) AS observed_at_ms,
                    CASE WHEN w.run_id IS NOT NULL THEN 'accepted'
                         ELSE o.provider_dispatch_status END AS provider_dispatch_status
             FROM taskflow_effect_dispatch_attempts a
             LEFT JOIN taskflow_effect_dispatch_observations o
               ON o.owner_agent_id = a.owner_agent_id
              AND o.run_id = a.run_id
              AND o.step_id = a.step_id
              AND o.attempt = a.attempt
             LEFT JOIN taskflow_effect_dispatch_reconciliations r
               ON r.owner_agent_id = a.owner_agent_id
              AND r.run_id = a.run_id
              AND r.step_id = a.step_id
              AND r.attempt = a.attempt
             LEFT JOIN taskflow_effect_provider_acceptances w
               ON w.owner_agent_id = a.owner_agent_id AND w.run_id = a.run_id
              AND w.step_id = a.step_id AND w.attempt = a.attempt
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

    pub(crate) async fn pending_effect_dispatch_attempts(
        &self,
        limit: usize,
    ) -> Result<Vec<EffectDispatchAttempt>, TaskFlowError> {
        if limit == 0 || limit > 1_024 {
            return Err(TaskFlowError::Invalid(
                "effect recovery scan limit".to_string(),
            ));
        }
        let rows = sqlx::query(
            "SELECT a.*,
                    COALESCE(r.observation, o.observation) AS observation,
                    COALESCE(r.evidence_digest, o.evidence_digest) AS evidence_digest,
                    COALESCE(r.observed_at_ms, o.observed_at_ms) AS observed_at_ms,
                    CASE WHEN w.run_id IS NOT NULL THEN 'accepted'
                         ELSE o.provider_dispatch_status END AS provider_dispatch_status
             FROM taskflow_effect_dispatch_attempts a
             LEFT JOIN taskflow_effect_dispatch_observations o
               ON o.owner_agent_id = a.owner_agent_id
              AND o.run_id = a.run_id
              AND o.step_id = a.step_id
              AND o.attempt = a.attempt
             LEFT JOIN taskflow_effect_dispatch_reconciliations r
               ON r.owner_agent_id = a.owner_agent_id
              AND r.run_id = a.run_id
              AND r.step_id = a.step_id
              AND r.attempt = a.attempt
             LEFT JOIN taskflow_effect_provider_acceptances w
               ON w.owner_agent_id = a.owner_agent_id AND w.run_id = a.run_id
              AND w.step_id = a.step_id AND w.attempt = a.attempt
             WHERE a.owner_agent_id = ?
               AND r.run_id IS NULL
               AND (o.run_id IS NULL OR o.observation = 'indeterminate')
             ORDER BY a.started_at_ms, a.run_id, a.step_id, a.attempt
             LIMIT ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(
            i64::try_from(limit)
                .map_err(|_| TaskFlowError::Invalid("effect recovery scan limit".to_string()))?,
        )
        .fetch_all(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        rows.into_iter().map(effect_attempt_from_row).collect()
    }

    pub(crate) async fn record_effect_provider_acceptance(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        evidence: &Sha256Digest,
        observed_at_ms: u64,
    ) -> Result<EffectDispatchAttempt, TaskFlowError> {
        let result = sqlx::query("INSERT OR IGNORE INTO taskflow_effect_provider_acceptances
            (owner_agent_id, run_id, step_id, attempt, evidence_digest, observed_at_ms)
            SELECT a.owner_agent_id, a.run_id, a.step_id, a.attempt, ?, ?
            FROM taskflow_effect_dispatch_attempts a
            LEFT JOIN taskflow_effect_dispatch_observations o USING(owner_agent_id, run_id, step_id, attempt)
            LEFT JOIN taskflow_effect_dispatch_reconciliations r USING(owner_agent_id, run_id, step_id, attempt)
            WHERE a.owner_agent_id = ? AND a.run_id = ? AND a.step_id = ? AND a.attempt = ?
              AND (o.observation IS NULL OR o.observation = 'indeterminate') AND r.run_id IS NULL
              AND NOT EXISTS (SELECT 1 FROM taskflow_step_outbox s
                WHERE s.owner_agent_id = a.owner_agent_id AND s.run_id = a.run_id
                  AND s.step_id = a.step_id AND s.attempt = a.attempt
                  AND (s.final_outcome IS NOT NULL OR s.observation IN ('succeeded', 'failed')))")
            .bind(evidence.as_str()).bind(to_i64(observed_at_ms)?)
            .bind(self.taskflow_owner_agent_id().as_str()).bind(run_id).bind(step_id).bind(i64::from(attempt))
            .execute(self.taskflow_pool()).await.map_err(|_| TaskFlowError::Unavailable)?;
        let current = self
            .effect_dispatch_attempt(run_id, step_id, attempt)
            .await?
            .ok_or_else(|| {
                TaskFlowError::Conflict("effect dispatch attempt is missing".to_string())
            })?;
        if result.rows_affected() == 0
            && current.provider_dispatch_status != Some(AuthorizedProviderDispatchStatus::Accepted)
        {
            return Err(TaskFlowError::Conflict(
                "provider acceptance contradicts terminal evidence".to_string(),
            ));
        }
        Ok(current)
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) async fn record_effect_dispatch_observation(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        kind: EffectDispatchObservationKind,
        evidence_digest: &Sha256Digest,
        observed_at_ms: u64,
        provider: Option<EffectProviderObservation>,
    ) -> Result<EffectDispatchAttempt, TaskFlowError> {
        let current = self
            .effect_dispatch_attempt(run_id, step_id, attempt)
            .await?
            .ok_or_else(|| {
                TaskFlowError::Conflict("effect dispatch attempt is missing".to_string())
            })?;

        let forbids_accepted = kind == EffectDispatchObservationKind::ProvenAbsent
            || matches!(
                provider,
                Some(
                    EffectProviderObservation::Lookup(ProviderEffectAckStatus::Rejected)
                        | EffectProviderObservation::Dispatch(
                            AuthorizedProviderDispatchStatus::Rejected
                        )
                )
            );
        let needs_unknown = matches!(
            provider,
            Some(EffectProviderObservation::Lookup(
                ProviderEffectAckStatus::Rejected
            ))
        );
        if (forbids_accepted
            && current.provider_dispatch_status == Some(AuthorizedProviderDispatchStatus::Accepted))
            || (needs_unknown
                && current.provider_dispatch_status
                    != Some(AuthorizedProviderDispatchStatus::Unknown))
        {
            return Err(TaskFlowError::Conflict(
                "provider rejection or absence contradicts admission evidence".to_string(),
            ));
        }
        if let Some(observation) = &current.observation {
            if observation.kind == kind && observation.evidence_digest == *evidence_digest {
                return Ok(current);
            }
            if observation.kind != EffectDispatchObservationKind::Indeterminate
                || kind == EffectDispatchObservationKind::Indeterminate
            {
                return Err(TaskFlowError::Conflict(
                    "effect observation is already terminal or bound to different bytes"
                        .to_string(),
                ));
            }

            let query = format!(
                "INSERT INTO taskflow_effect_dispatch_reconciliations (
                    owner_agent_id, run_id, step_id, attempt, observation,
                    evidence_digest, observed_at_ms
                 ) SELECT ?, ?, ?, ?, ?, ?, ? {TERMINAL_STEP_OBSERVATION_GUARD} {PROVIDER_CONTINUITY_GUARD}",
            );
            // Only static SQL guards are concatenated; every identity and
            // evidence value is supplied through a bind parameter.
            let inserted = sqlx::query(sqlx::AssertSqlSafe(query))
                .bind(self.taskflow_owner_agent_id().as_str())
                .bind(run_id)
                .bind(step_id)
                .bind(i64::from(attempt))
                .bind(kind.as_str())
                .bind(evidence_digest.as_str())
                .bind(to_i64(observed_at_ms)?)
                .bind(self.taskflow_owner_agent_id().as_str())
                .bind(run_id)
                .bind(step_id)
                .bind(i64::from(attempt))
                .bind(evidence_digest.as_str())
                .bind(kind.as_str())
                .bind(self.taskflow_owner_agent_id().as_str())
                .bind(run_id)
                .bind(step_id)
                .bind(i64::from(attempt))
                .bind(forbids_accepted)
                .bind(needs_unknown)
                .execute(self.taskflow_pool())
                .await;

            if matches!(&inserted, Ok(result) if result.rows_affected() == 0) {
                return Err(TaskFlowError::Conflict(
                    "effect reconciliation contradicts terminal step evidence".to_string(),
                ));
            }

            let refreshed = self
                .effect_dispatch_attempt(run_id, step_id, attempt)
                .await?
                .ok_or_else(|| {
                    TaskFlowError::Corrupt(
                        "effect dispatch attempt vanished during reconciliation".to_string(),
                    )
                })?;
            return match inserted {
                Ok(_) => Ok(refreshed),
                Err(error) if is_constraint(&error) => {
                    let Some(observation) = &refreshed.observation else {
                        return Err(TaskFlowError::Conflict(
                            "effect reconciliation conflicts with durable evidence".to_string(),
                        ));
                    };
                    if observation.kind != kind || observation.evidence_digest != *evidence_digest {
                        return Err(TaskFlowError::Conflict(
                            "effect reconciliation is already bound to different bytes".to_string(),
                        ));
                    }
                    Ok(refreshed)
                }
                Err(_) => Err(TaskFlowError::Unavailable),
            };
        }

        let query = format!(
            "INSERT INTO taskflow_effect_dispatch_observations (
                owner_agent_id, run_id, step_id, attempt, observation,
                evidence_digest, observed_at_ms, provider_dispatch_status
             ) SELECT ?, ?, ?, ?, ?, ?, ?, ? {TERMINAL_STEP_OBSERVATION_GUARD} {PROVIDER_CONTINUITY_GUARD}",
        );
        // Only static SQL guards are concatenated; data remains parameterized.
        let inserted = sqlx::query(sqlx::AssertSqlSafe(query))
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(run_id)
            .bind(step_id)
            .bind(i64::from(attempt))
            .bind(kind.as_str())
            .bind(evidence_digest.as_str())
            .bind(to_i64(observed_at_ms)?)
            .bind(match provider {
                Some(EffectProviderObservation::Dispatch(status)) => Some(status.as_str()),
                _ => None,
            })
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(run_id)
            .bind(step_id)
            .bind(i64::from(attempt))
            .bind(evidence_digest.as_str())
            .bind(kind.as_str())
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(run_id)
            .bind(step_id)
            .bind(i64::from(attempt))
            .bind(forbids_accepted)
            .bind(needs_unknown)
            .execute(self.taskflow_pool())
            .await;

        if matches!(&inserted, Ok(result) if result.rows_affected() == 0) {
            return Err(TaskFlowError::Conflict(
                "effect observation contradicts terminal step evidence".to_string(),
            ));
        }

        let refreshed = self
            .effect_dispatch_attempt(run_id, step_id, attempt)
            .await?
            .ok_or_else(|| {
                TaskFlowError::Corrupt(
                    "effect dispatch attempt vanished after observation".to_string(),
                )
            })?;
        match inserted {
            Ok(_) => Ok(refreshed),
            Err(error) if is_constraint(&error) => {
                let Some(observation) = &refreshed.observation else {
                    return Err(TaskFlowError::Conflict(
                        "effect observation conflicts with durable evidence".to_string(),
                    ));
                };
                if observation.kind != kind || observation.evidence_digest != *evidence_digest {
                    return Err(TaskFlowError::Conflict(
                        "effect observation is already bound to different bytes".to_string(),
                    ));
                }
                Ok(refreshed)
            }
            Err(_) => Err(TaskFlowError::Unavailable),
        }
    }
}

fn effect_attempt_from_row(
    row: sqlx::sqlite::SqliteRow,
) -> Result<EffectDispatchAttempt, TaskFlowError> {
    let provider_contract_binding = row
        .try_get::<Option<String>, _>("provider_contract_binding")
        .map_err(|_| TaskFlowError::Corrupt("effect provider contract binding".to_string()))?
        .map(Sha256Digest::parse)
        .transpose()
        .map_err(|_| TaskFlowError::Corrupt("effect provider contract binding".to_string()))?;
    if provider_contract_binding.as_ref().is_some_and(|digest| {
        digest.as_str() == "0000000000000000000000000000000000000000000000000000000000000000"
    }) {
        return Err(TaskFlowError::Corrupt(
            "zero effect provider contract binding".to_string(),
        ));
    }
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
        owner_agent_id: AgentId::parse(
            row.try_get::<String, _>("owner_agent_id")
                .map_err(|_| TaskFlowError::Corrupt("effect owner agent id".to_string()))?,
        )
        .map_err(|_| TaskFlowError::Corrupt("effect owner agent id".to_string()))?,
        provider_key_version: u32::try_from(
            row.try_get::<i64, _>("provider_key_version")
                .map_err(|_| TaskFlowError::Corrupt("effect provider key version".to_string()))?,
        )
        .map_err(|_| TaskFlowError::Corrupt("effect provider key version".to_string()))?,
        provider_contract_binding,
        provider_dispatch_status: row
            .try_get::<Option<String>, _>("provider_dispatch_status")
            .map_err(|_| TaskFlowError::Corrupt("provider dispatch status".to_string()))?
            .map(|status| AuthorizedProviderDispatchStatus::parse(&status))
            .transpose()?,
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

#[cfg(test)]
mod tests {
    use codex_hepta_contracts::AgentId;
    use codex_hepta_contracts::Sha256Digest;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_fleet::WorkspaceBinding;
    use codex_hepta_paths::HeptaFleetRoot;

    use super::*;
    use crate::TaskFlowDefinition;
    use crate::TaskFlowEdgeSpec;
    use crate::TaskFlowFence;
    use crate::TaskFlowNodeKind;
    use crate::TaskFlowNodeSpec;

    const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

    fn fixture() -> (tempfile::TempDir, codex_hepta_paths::HeptaAgentLayout) {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical temp root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let workspace = workspace.canonicalize().expect("canonical workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(AGENT_ID).expect("agent id"),
            WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let layout = registry.register(manifest).expect("register agent").layout;
        (temp, layout)
    }

    async fn prepared_store() -> (
        tempfile::TempDir,
        codex_hepta_paths::HeptaAgentLayout,
        AutomationStore,
        TaskFlowFence,
    ) {
        let (temp, layout) = fixture();
        let store = AutomationStore::open(&layout).await.expect("open store");
        let fence = TaskFlowFence::new(
            AgentId::parse(AGENT_ID).expect("agent id"),
            "effect-owner",
            1,
            1,
            "effect-fence-1",
        )
        .expect("fence");
        let definition = TaskFlowDefinition::new(
            "effect-recovery",
            1,
            "work",
            vec![
                TaskFlowNodeSpec::new("work", TaskFlowNodeKind::Activity),
                TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
                TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
            ],
            vec![
                TaskFlowEdgeSpec::new("work", "success"),
                TaskFlowEdgeSpec::new("work", "failure"),
            ],
            Vec::new(),
            Sha256Digest::for_bytes(b"effect-policy"),
        )
        .expect("definition");
        store
            .register_taskflow_definition(&definition, &fence, 10)
            .await
            .expect("register definition");
        store
            .create_taskflow_run(
                "effect-run",
                &definition.workflow_id,
                definition.version,
                definition.definition_digest(),
                "effect-thread",
                10,
            )
            .await
            .expect("create run");
        let claimed = store
            .claim_taskflow_run("effect-run", &fence, 20, 10_000)
            .await
            .expect("claim run");
        store
            .apply_taskflow_command(
                &crate::TaskFlowCommand::new(
                    "effect-run",
                    "start-effect",
                    fence.clone(),
                    claimed.revision,
                    crate::TaskFlowTransition::Start,
                    20,
                )
                .expect("start command"),
            )
            .await
            .expect("start run");
        let intent = Sha256Digest::for_bytes(b"effect-intent");
        let payload = Sha256Digest::for_bytes(b"effect-payload");
        store
            .prepare_taskflow_step(
                "effect-run",
                "work",
                1,
                &fence,
                &intent,
                &payload,
                "prepare-effect",
                20,
            )
            .await
            .expect("prepare step");
        store
            .claim_taskflow_step(
                "effect-run",
                "work",
                1,
                &fence,
                &intent,
                &payload,
                "claim-effect",
                20,
            )
            .await
            .expect("claim step");
        (temp, layout, store, fence)
    }

    #[tokio::test]
    async fn indeterminate_provider_evidence_reconciles_after_reopen_without_redispatch() {
        let (_temp, layout, store, fence) = prepared_store().await;
        let intent = Sha256Digest::for_bytes(b"effect-intent");
        let payload = Sha256Digest::for_bytes(b"effect-payload");
        let binding = Sha256Digest::for_bytes(b"effect-binding");
        let provider_contract_binding = Sha256Digest::for_bytes(b"provider-contract-binding");
        let nonce = Sha256Digest::for_bytes(b"effect-nonce");
        let started = store
            .begin_effect_dispatch_attempt(
                "effect-run",
                "work",
                1,
                &intent,
                &payload,
                &binding,
                "provider:test",
                7,
                "grant-1",
                &nonce,
                "record-effect",
                || Ok(21),
                &fence,
                Some(&provider_contract_binding),
            )
            .await
            .expect("begin attempt");
        assert!(matches!(started, EffectDispatchStart::Inserted(_)));

        let unknown = Sha256Digest::for_bytes(b"provider-unknown");
        let first = store
            .record_effect_dispatch_observation(
                "effect-run",
                "work",
                1,
                EffectDispatchObservationKind::Indeterminate,
                &unknown,
                22,
                None,
            )
            .await
            .expect("record indeterminate");
        assert_eq!(
            first.observation.as_ref().map(|value| value.kind),
            Some(EffectDispatchObservationKind::Indeterminate)
        );
        assert_eq!(
            store
                .pending_effect_dispatch_attempts(10)
                .await
                .expect("pending")
                .len(),
            1
        );

        store.close().await;
        let reopened = AutomationStore::open(&layout).await.expect("reopen store");
        let pending = reopened
            .pending_effect_dispatch_attempts(10)
            .await
            .expect("pending after reopen");
        assert_eq!(pending.len(), 1);
        assert_eq!(pending[0].grant_id, "grant-1");
        assert_eq!(
            pending[0].provider_contract_binding,
            Some(provider_contract_binding)
        );
        assert!(
            sqlx::query(
                "UPDATE taskflow_effect_dispatch_attempts SET provider_contract_binding = ?"
            )
            .bind(Sha256Digest::for_bytes(b"substituted-contract").as_str())
            .execute(reopened.taskflow_pool())
            .await
            .is_err()
        );

        let terminal = Sha256Digest::for_bytes(b"provider-terminal");
        let settled = reopened
            .record_effect_dispatch_observation(
                "effect-run",
                "work",
                1,
                EffectDispatchObservationKind::Succeeded,
                &terminal,
                30,
                None,
            )
            .await
            .expect("terminal reconciliation");
        assert_eq!(
            settled.observation.as_ref().map(|value| value.kind),
            Some(EffectDispatchObservationKind::Succeeded)
        );
        assert_eq!(
            settled
                .observation
                .as_ref()
                .map(|value| value.evidence_digest.clone()),
            Some(terminal.clone())
        );
        assert!(
            reopened
                .pending_effect_dispatch_attempts(10)
                .await
                .expect("no pending after terminal")
                .is_empty()
        );

        let replay = reopened
            .record_effect_dispatch_observation(
                "effect-run",
                "work",
                1,
                EffectDispatchObservationKind::Succeeded,
                &terminal,
                31,
                None,
            )
            .await
            .expect("terminal replay");
        assert_eq!(replay.observation, settled.observation);
        assert!(matches!(
            reopened
                .record_effect_dispatch_observation(
                    "effect-run",
                    "work",
                    1,
                    EffectDispatchObservationKind::Failed,
                    &Sha256Digest::for_bytes(b"different-terminal"),
                    32,
                    None,
                )
                .await,
            Err(TaskFlowError::Conflict(_))
        ));
        reopened.close().await;
    }
    #[tokio::test]
    async fn concurrent_acceptance_and_rejection_are_serialized_and_acceptance_is_immutable() {
        let (_temp, _layout, store, fence) = prepared_store().await;
        let digest = Sha256Digest::for_bytes(b"ledger-race");
        store
            .begin_effect_dispatch_attempt(
                "effect-run",
                "work",
                1,
                &Sha256Digest::for_bytes(b"effect-intent"),
                &Sha256Digest::for_bytes(b"effect-payload"),
                &digest,
                "provider:test",
                1,
                "race-grant",
                &digest,
                "race-record",
                || Ok(21),
                &fence,
                None,
            )
            .await
            .expect("start");
        store
            .record_effect_dispatch_observation(
                "effect-run",
                "work",
                1,
                EffectDispatchObservationKind::Indeterminate,
                &digest,
                22,
                Some(EffectProviderObservation::Dispatch(
                    AuthorizedProviderDispatchStatus::Unknown,
                )),
            )
            .await
            .expect("unknown");
        let accepted = Sha256Digest::for_bytes(b"accepted");
        let rejected = Sha256Digest::for_bytes(b"rejected");
        let (admission, rejection) = tokio::join!(
            store.record_effect_provider_acceptance("effect-run", "work", 1, &accepted, 23),
            store.record_effect_dispatch_observation(
                "effect-run",
                "work",
                1,
                EffectDispatchObservationKind::Failed,
                &rejected,
                23,
                Some(EffectProviderObservation::Lookup(
                    ProviderEffectAckStatus::Rejected
                ))
            )
        );
        assert_ne!(
            admission.is_ok(),
            rejection.is_ok(),
            "contradictory facts cannot both commit"
        );
        if admission.is_ok() {
            store
                .record_effect_provider_acceptance("effect-run", "work", 1, &rejected, 24)
                .await
                .expect("later accepted lookup retains first witness");
            let row: (i64, String) = sqlx::query_as(
                "SELECT COUNT(*), evidence_digest FROM taskflow_effect_provider_acceptances",
            )
            .fetch_one(store.taskflow_pool())
            .await
            .expect("accepted witness");
            assert_eq!(row, (1, accepted.as_str().to_string()));
            assert!(
                sqlx::query("UPDATE taskflow_effect_provider_acceptances SET evidence_digest = ?")
                    .bind(rejected.as_str())
                    .execute(store.taskflow_pool())
                    .await
                    .is_err()
            );
            assert!(
                sqlx::query("DELETE FROM taskflow_effect_provider_acceptances")
                    .execute(store.taskflow_pool())
                    .await
                    .is_err()
            );
            assert!(sqlx::query("UPDATE taskflow_effect_dispatch_observations SET provider_dispatch_status = 'accepted'")
                .execute(store.taskflow_pool()).await.is_err());
        }
    }
}
