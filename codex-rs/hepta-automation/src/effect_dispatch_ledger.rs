//! Append-only provider-contact evidence for final-use-authorized TaskFlow effects.
//!
//! These rows do not execute effects and grant no authority. The attempt row
//! only records that a verified final-use claim crossed the durable dispatch
//! boundary; the observation row records exactly one provider-owned recovery
//! fact. Keeping both immutable lets recovery repair the TaskFlow step without
//! ever inferring terminality from process-local control flow.

use std::collections::BTreeSet;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckSource;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use sqlx::QueryBuilder;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqliteConnection;

use crate::AutomationStore;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::effect_dispatch_identity::validate_effect_dispatch_history;
use crate::effect_dispatch_identity::validate_effect_dispatch_identity_tx;
use crate::effect_dispatch_provider_receipt::ProviderReceiptV1;
use crate::effect_dispatch_provider_receipt::bind_provider_receipt;
use crate::effect_dispatch_provider_receipt::validate_provider_projection;
use crate::taskflow::load_taskflow_run_tx;

const MAX_EFFECT_DISPATCH_WIRE_BYTES: usize = 64 * 1024;

pub(crate) const EFFECT_DISPATCH_SELECT: &str =
    "SELECT a.*,
            COALESCE(r.observation, o.observation) AS observation,
            COALESCE(r.evidence_digest, o.evidence_digest) AS evidence_digest,
            COALESCE(r.observed_at_ms, o.observed_at_ms) AS observed_at_ms,
            CASE WHEN r.run_id IS NOT NULL THEN CAST(substr(CAST(r.provider_receipt_json AS BLOB),1,1025) AS TEXT)
                 ELSE CAST(substr(CAST(o.provider_receipt_json AS BLOB),1,1025) AS TEXT) END AS provider_receipt_json,
            CAST(substr(CAST(o.provider_receipt_json AS BLOB),1,1025) AS TEXT) AS initial_provider_receipt_json,
            o.evidence_digest AS initial_evidence_digest, o.observation AS initial_observation,
            CAST(substr(CAST(r.provider_receipt_json AS BLOB),1,1025) AS TEXT) AS reconciled_provider_receipt_json,
            r.evidence_digest AS reconciled_evidence_digest, r.observation AS reconciled_observation,
            CAST(substr(CAST(b.receipt_json AS BLOB),1,1025) AS TEXT) AS binding_receipt_json,
            b.receipt_digest AS binding_receipt_digest, b.attempt AS binding_attempt
     FROM taskflow_effect_dispatch_attempts a
     LEFT JOIN taskflow_effect_dispatch_observations o
       ON o.owner_agent_id=a.owner_agent_id AND o.run_id=a.run_id
      AND o.step_id=a.step_id AND o.attempt=a.attempt
     LEFT JOIN taskflow_effect_dispatch_reconciliations r
       ON r.owner_agent_id=a.owner_agent_id AND r.run_id=a.run_id
      AND r.step_id=a.step_id AND r.attempt=a.attempt
     LEFT JOIN taskflow_effect_provider_bindings b
       ON b.owner_agent_id=a.owner_agent_id AND b.run_id=a.run_id AND b.step_id=a.step_id
      AND b.attempt <= a.attempt";

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
    pub(crate) run_id: String,
    pub(crate) step_id: String,
    pub(crate) attempt: u32,
    pub(crate) intent_digest: Sha256Digest,
    pub(crate) payload_digest: Sha256Digest,
    /// Exact provider occurrence key frozen before physical contact. Legacy
    /// pre-v20 rows retain `None` and remain recovery-only.
    pub(crate) provider_effect_key: Option<ProviderEffectKey>,
    /// Exact immutable provider bytes frozen with the attempt. Legacy pre-v20
    /// rows retain `None`; their digest-only recovery semantics are unchanged.
    pub(crate) wire_payload: Option<Vec<u8>>,
    pub(crate) binding_digest: Sha256Digest,
    pub(crate) destination_id: String,
    pub(crate) authority_epoch: u64,
    pub(crate) grant_id: String,
    pub(crate) grant_nonce_digest: Sha256Digest,
    pub(crate) record_command_id: String,
    pub(crate) started_at_ms: u64,
    pub(crate) observation: Option<EffectDispatchObservation>,
    pub(crate) provider_binding: Option<ProviderReceiptV1>,
    pub(crate) provider_binding_attempt: Option<u32>,
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
        fence: &TaskFlowFence,
        intent_digest: &Sha256Digest,
        payload_digest: &Sha256Digest,
        provider_effect_key: &ProviderEffectKey,
        wire_payload: &[u8],
        binding_digest: &Sha256Digest,
        destination_id: &str,
        authority_epoch: u64,
        grant_id: &str,
        grant_nonce_digest: &Sha256Digest,
        record_command_id: &str,
        started_at_ms: u64,
    ) -> Result<EffectDispatchStart, TaskFlowError> {
        if wire_payload.is_empty()
            || wire_payload.len() > MAX_EFFECT_DISPATCH_WIRE_BYTES
            || Sha256Digest::for_bytes(wire_payload) != *payload_digest
            || ProviderEffectKey::parse(provider_effect_key.as_str().to_owned()).is_err()
        {
            return Err(TaskFlowError::Invalid(
                "effect dispatch recovery material".to_string(),
            ));
        }
        let owner = self.taskflow_owner_agent_id().as_str();
        let mut transaction = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        if let Some(existing) =
            read_effect_attempt(&mut transaction, owner, run_id, step_id, attempt).await?
        {
            if existing.intent_digest != *intent_digest
                || existing.payload_digest != *payload_digest
                || existing.provider_effect_key.as_ref() != Some(provider_effect_key)
                || existing.wire_payload.as_deref() != Some(wire_payload)
                || existing.binding_digest != *binding_digest
                || existing.destination_id != destination_id
                || existing.record_command_id != record_command_id
            {
                return Err(TaskFlowError::Conflict(
                    "effect dispatch attempt is bound to different bytes".to_string(),
                ));
            }
            transaction
                .commit()
                .await
                .map_err(|_| TaskFlowError::Unavailable)?;
            return Ok(EffectDispatchStart::Existing(existing));
        }
        // Historical step reads permit reconciliation after lease expiry or
        // cancellation. Only the original run owner's current live lease can
        // authorize insertion of a new physical dispatch barrier.
        let run = load_taskflow_run_tx(&mut transaction, self.taskflow_owner_agent_id(), run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Conflict("effect TaskFlow run is missing".to_string()))?;
        // A fresh attempt cannot bypass uncertainty by using another attempt
        // number. Serialize this check with insertion and decode so concurrent
        // preclaimed attempts cannot both cross the provider boundary, and a
        // failed decode cannot leave a committed invalid barrier.
        let blocked: bool = sqlx::query_scalar(
            "SELECT EXISTS (
                SELECT 1 FROM taskflow_effect_dispatch_attempts a
                LEFT JOIN taskflow_effect_dispatch_observations o
                  ON o.owner_agent_id=a.owner_agent_id AND o.run_id=a.run_id
                 AND o.step_id=a.step_id AND o.attempt=a.attempt
                LEFT JOIN taskflow_effect_dispatch_reconciliations r
                  ON r.owner_agent_id=a.owner_agent_id AND r.run_id=a.run_id
                 AND r.step_id=a.step_id AND r.attempt=a.attempt
                WHERE a.owner_agent_id=? AND a.run_id=? AND a.step_id=?
                  AND (a.attempt >= ?
                       OR COALESCE(r.observation, o.observation, 'unobserved') != 'proven_absent')
             )",
        )
        .bind(owner)
        .bind(run_id)
        .bind(step_id)
        .bind(i64::from(attempt))
        .fetch_one(&mut *transaction)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        if blocked {
            return Err(TaskFlowError::Conflict(
                "a new effect attempt requires proved absence of every prior attempt".to_string(),
            ));
        }
        let mut prior_query = QueryBuilder::<Sqlite>::new(EFFECT_DISPATCH_SELECT);
        prior_query
            .push(" WHERE a.owner_agent_id=")
            .push_bind(owner)
            .push(" AND a.run_id=")
            .push_bind(run_id)
            .push(" AND a.step_id=")
            .push_bind(step_id)
            .push(" ORDER BY a.attempt DESC LIMIT 1");
        let previous = prior_query
            .build()
            .fetch_optional(&mut *transaction)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?
            .map(effect_attempt_from_row)
            .transpose()?;
        if let Some(previous) = &previous {
            validate_effect_dispatch_identity_tx(
                &mut transaction,
                previous,
                provider_effect_key,
                payload_digest,
                wire_payload,
                destination_id,
            )
            .await?;
        }
        let previous_absence = previous
            .as_ref()
            .map(|previous| {
                let observation = previous.observation.as_ref().ok_or_else(|| {
                    TaskFlowError::Corrupt("prior effect absence is missing".to_string())
                })?;
                Ok::<_, TaskFlowError>((previous.attempt, &observation.evidence_digest))
            })
            .transpose()?;
        self.validate_effect_dispatch_step_tx(
            &mut transaction,
            &run,
            step_id,
            attempt,
            fence,
            intent_digest,
            payload_digest,
            previous_absence,
            started_at_ms,
        )
        .await?;
        sqlx::query(
            "INSERT INTO taskflow_effect_dispatch_attempts (
                owner_agent_id, run_id, step_id, attempt, intent_digest,
                payload_digest, provider_effect_key, wire_payload, binding_digest,
                destination_id, authority_epoch, grant_id, grant_nonce_digest,
                record_command_id, started_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(owner)
        .bind(run_id)
        .bind(step_id)
        .bind(i64::from(attempt))
        .bind(intent_digest.as_str())
        .bind(payload_digest.as_str())
        .bind(provider_effect_key.as_str())
        .bind(wire_payload)
        .bind(binding_digest.as_str())
        .bind(destination_id)
        .bind(to_i64(authority_epoch)?)
        .bind(grant_id)
        .bind(grant_nonce_digest.as_str())
        .bind(record_command_id)
        .bind(to_i64(started_at_ms)?)
        .execute(&mut *transaction)
        .await
        .map_err(|error| {
            if is_constraint(&error) {
                TaskFlowError::Conflict(
                    "effect dispatch identity conflicts with durable evidence".to_string(),
                )
            } else {
                TaskFlowError::Unavailable
            }
        })?;
        let inserted = read_effect_attempt(&mut transaction, owner, run_id, step_id, attempt)
            .await?
            .ok_or_else(|| {
                TaskFlowError::Corrupt("effect dispatch attempt vanished after insert".to_string())
            })?;
        transaction
            .commit()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        Ok(EffectDispatchStart::Inserted(inserted))
    }

    pub(crate) async fn effect_dispatch_attempt(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
    ) -> Result<Option<EffectDispatchAttempt>, TaskFlowError> {
        let mut transaction = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let result = read_effect_attempt(
            &mut transaction,
            self.taskflow_owner_agent_id().as_str(),
            run_id,
            step_id,
            attempt,
        )
        .await?;
        transaction
            .rollback()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        Ok(result)
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
        let mut query = QueryBuilder::<Sqlite>::new(EFFECT_DISPATCH_SELECT);
        query
            .push(" WHERE a.owner_agent_id = ")
            .push_bind(self.taskflow_owner_agent_id().as_str())
            .push(
                "
               AND r.run_id IS NULL
               AND (o.run_id IS NULL OR o.observation = 'indeterminate')
             ORDER BY a.started_at_ms, a.run_id, a.step_id, a.attempt LIMIT ",
            )
            .push_bind(
                i64::try_from(limit).map_err(|_| {
                    TaskFlowError::Invalid("effect recovery scan limit".to_string())
                })?,
            );
        let mut transaction = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let rows = query
            .build()
            .fetch_all(&mut *transaction)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let attempts = rows
            .into_iter()
            .map(effect_attempt_from_row)
            .collect::<Result<Vec<_>, _>>()?;
        let mut checked = BTreeSet::new();
        for attempt in &attempts {
            if checked.insert((&attempt.run_id, &attempt.step_id)) {
                validate_effect_dispatch_history(&mut transaction, attempt).await?;
            }
        }
        transaction
            .rollback()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        Ok(attempts)
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) async fn record_effect_dispatch_observation(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
        fence: &TaskFlowFence,
        kind: EffectDispatchObservationKind,
        evidence_digest: &Sha256Digest,
        observed_at_ms: u64,
        provider_ack: Option<(&ProviderEffectAck, ProviderEffectAckSource)>,
    ) -> Result<EffectDispatchAttempt, TaskFlowError> {
        let owner = self.taskflow_owner_agent_id().as_str();
        let mut transaction = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let current = read_effect_attempt(&mut transaction, owner, run_id, step_id, attempt)
            .await?
            .ok_or_else(|| {
                TaskFlowError::Conflict("effect dispatch attempt is missing".to_string())
            })?;
        let step = self
            .read_verified_step_tx(&mut transaction, run_id, step_id, attempt, Some(fence))
            .await?
            .ok_or_else(|| {
                TaskFlowError::Conflict("effect observation has no durable step".to_string())
            })?;
        if current.intent_digest != step.intent_digest
            || current.payload_digest != step.payload_digest
        {
            return Err(TaskFlowError::Conflict(
                "effect observation differs from the durable step".to_string(),
            ));
        }
        let provider_json = bind_provider_receipt(
            &mut transaction,
            owner,
            &current,
            (kind, evidence_digest, observed_at_ms),
            provider_ack,
        )
        .await?;
        let statement = if let Some(observation) = &current.observation {
            let exact = observation.kind == kind && observation.evidence_digest == *evidence_digest;
            let accepted_lookup = observation.kind == EffectDispatchObservationKind::Indeterminate
                && kind == EffectDispatchObservationKind::Indeterminate
                && provider_ack.is_some_and(|(ack, source)| {
                    ack.status == ProviderEffectAckStatus::Accepted
                        && source == ProviderEffectAckSource::StatusLookup
                });
            if exact || accepted_lookup {
                // Persist the first observed provider identity even when the
                // TaskFlow projection remains the original Unknown fact.
                let refreshed =
                    read_effect_attempt(&mut transaction, owner, run_id, step_id, attempt)
                        .await?
                        .ok_or_else(|| {
                            TaskFlowError::Corrupt("effect attempt vanished".to_string())
                        })?;
                transaction
                    .commit()
                    .await
                    .map_err(|_| TaskFlowError::Unavailable)?;
                return Ok(refreshed);
            }
            if observation.kind != EffectDispatchObservationKind::Indeterminate
                || kind == EffectDispatchObservationKind::Indeterminate
            {
                return Err(TaskFlowError::Conflict(
                    "effect observation is already terminal or bound to different bytes"
                        .to_string(),
                ));
            }
            "INSERT INTO taskflow_effect_dispatch_reconciliations
             (owner_agent_id, run_id, step_id, attempt, observation,
              evidence_digest, observed_at_ms, provider_receipt_json)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        } else {
            "INSERT INTO taskflow_effect_dispatch_observations
             (owner_agent_id, run_id, step_id, attempt, observation,
              evidence_digest, observed_at_ms, provider_receipt_json)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        };
        sqlx::query(statement)
            .bind(owner)
            .bind(run_id)
            .bind(step_id)
            .bind(i64::from(attempt))
            .bind(kind.as_str())
            .bind(evidence_digest.as_str())
            .bind(to_i64(observed_at_ms)?)
            .bind(provider_json)
            .execute(&mut *transaction)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let refreshed = read_effect_attempt(&mut transaction, owner, run_id, step_id, attempt)
            .await?
            .ok_or_else(|| TaskFlowError::Corrupt("effect attempt vanished".to_string()))?;
        transaction
            .commit()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        Ok(refreshed)
    }
}

async fn read_effect_attempt(
    connection: &mut SqliteConnection,
    owner: &str,
    run_id: &str,
    step_id: &str,
    attempt: u32,
) -> Result<Option<EffectDispatchAttempt>, TaskFlowError> {
    let mut query = QueryBuilder::<Sqlite>::new(EFFECT_DISPATCH_SELECT);
    query
        .push(" WHERE a.owner_agent_id=")
        .push_bind(owner)
        .push(" AND a.run_id=")
        .push_bind(run_id)
        .push(" AND a.step_id=")
        .push_bind(step_id)
        .push(" AND a.attempt=")
        .push_bind(i64::from(attempt));
    let row = query
        .build()
        .fetch_optional(&mut *connection)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
    let attempt = row.map(effect_attempt_from_row).transpose()?;
    if let Some(attempt) = attempt.as_ref() {
        validate_effect_dispatch_history(connection, attempt).await?;
    }
    Ok(attempt)
}

pub(crate) fn effect_attempt_from_row(
    row: sqlx::sqlite::SqliteRow,
) -> Result<EffectDispatchAttempt, TaskFlowError> {
    let provider_effect_key: Option<String> = row
        .try_get("provider_effect_key")
        .map_err(|_| TaskFlowError::Corrupt("effect provider key column".to_string()))?;
    let wire_payload: Option<Vec<u8>> = row
        .try_get("wire_payload")
        .map_err(|_| TaskFlowError::Corrupt("effect wire payload column".to_string()))?;
    let payload_digest_text: String = row
        .try_get("payload_digest")
        .map_err(|_| TaskFlowError::Corrupt("effect payload digest".to_string()))?;
    let payload_digest = Sha256Digest::parse(payload_digest_text)
        .map_err(|_| TaskFlowError::Corrupt("effect payload digest".to_string()))?;
    let (provider_effect_key, wire_payload) = match (provider_effect_key, wire_payload) {
        (None, None) => (None, None),
        (Some(key), Some(bytes)) => {
            if bytes.is_empty()
                || bytes.len() > MAX_EFFECT_DISPATCH_WIRE_BYTES
                || Sha256Digest::for_bytes(&bytes) != payload_digest
            {
                return Err(TaskFlowError::Corrupt(
                    "effect recovery wire material".to_string(),
                ));
            }
            let key = ProviderEffectKey::parse(key)
                .map_err(|_| TaskFlowError::Corrupt("effect provider key".to_string()))?;
            (Some(key), Some(bytes))
        }
        _ => {
            return Err(TaskFlowError::Corrupt(
                "partial effect recovery material".to_string(),
            ));
        }
    };
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
    let mut attempt = EffectDispatchAttempt {
        owner_agent_id: AgentId::parse(
            row.try_get::<String, _>("owner_agent_id")
                .map_err(|_| TaskFlowError::Corrupt("effect owner column".to_string()))?,
        )
        .map_err(|_| TaskFlowError::Corrupt("effect owner identity".to_string()))?,
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
        payload_digest,
        provider_effect_key,
        wire_payload,
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
        provider_binding: None,
        provider_binding_attempt: row
            .try_get::<Option<i64>, _>("binding_attempt")
            .map_err(|_| TaskFlowError::Corrupt("provider binding attempt column".to_string()))?
            .map(|value| {
                u32::try_from(value)
                    .map_err(|_| TaskFlowError::Corrupt("provider binding attempt".to_string()))
            })
            .transpose()?,
    };
    attempt.provider_binding = validate_provider_projection(&row, &attempt)?;
    Ok(attempt)
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
                    "effect-start",
                    fence.clone(),
                    claimed.revision,
                    crate::TaskFlowTransition::Start,
                    21,
                )
                .expect("start command"),
            )
            .await
            .expect("start run");
        (temp, layout, store, fence)
    }

    #[tokio::test]
    async fn indeterminate_provider_evidence_reconciles_after_reopen_without_redispatch() {
        let (_temp, layout, store, fence) = prepared_store().await;
        let intent = Sha256Digest::for_bytes(b"effect-intent");
        let wire_payload = b"effect-payload";
        let payload = Sha256Digest::for_bytes(wire_payload);
        let provider_effect_key =
            ProviderEffectKey::for_operation("provider:test", "effect-run", "work")
                .expect("provider effect key");
        let binding = Sha256Digest::for_bytes(b"effect-binding");
        let nonce = Sha256Digest::for_bytes(b"effect-nonce");
        store
            .prepare_taskflow_step(
                "effect-run",
                "work",
                1,
                &fence,
                &intent,
                &payload,
                "prepare-effect",
                22,
            )
            .await
            .expect("prepare effect step");
        store
            .claim_taskflow_step(
                "effect-run",
                "work",
                1,
                &fence,
                &intent,
                &payload,
                "claim-effect",
                23,
            )
            .await
            .expect("claim effect step");
        let started = store
            .begin_effect_dispatch_attempt(
                "effect-run",
                "work",
                1,
                &fence,
                &intent,
                &payload,
                &provider_effect_key,
                wire_payload,
                &binding,
                "provider:test",
                7,
                "grant-1",
                &nonce,
                "record-effect",
                24,
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
                &fence,
                EffectDispatchObservationKind::Indeterminate,
                &unknown,
                25,
                /*provider_ack*/ None,
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
            pending[0].provider_effect_key.as_ref(),
            Some(&provider_effect_key)
        );
        assert_eq!(
            pending[0].wire_payload.as_deref(),
            Some(wire_payload.as_slice())
        );

        let terminal = Sha256Digest::for_bytes(b"provider-terminal");
        let settled = reopened
            .record_effect_dispatch_observation(
                "effect-run",
                "work",
                1,
                &fence,
                EffectDispatchObservationKind::Succeeded,
                &terminal,
                30,
                /*provider_ack*/ None,
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
                &fence,
                EffectDispatchObservationKind::Succeeded,
                &terminal,
                31,
                /*provider_ack*/ None,
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
                    &fence,
                    EffectDispatchObservationKind::Failed,
                    &Sha256Digest::for_bytes(b"different-terminal"),
                    32,
                    /*provider_ack*/ None,
                )
                .await,
            Err(TaskFlowError::Conflict(_))
        ));
        reopened.close().await;
    }

    #[tokio::test]
    async fn effect_dispatch_barrier_absence_cut_requires_settlement_and_new_fence() {
        let (_temp, layout, store, fence) = prepared_store().await;
        let intent = Sha256Digest::for_bytes(b"effect-intent");
        let wire = b"effect-payload";
        let payload = Sha256Digest::for_bytes(wire);
        let key =
            ProviderEffectKey::for_operation("provider:test", "effect-run", "work").expect("key");
        let binding = Sha256Digest::for_bytes(b"effect-binding");
        let nonce = Sha256Digest::for_bytes(b"effect-nonce");
        for attempt in [1, 2] {
            store
                .prepare_taskflow_step(
                    "effect-run",
                    "work",
                    attempt,
                    &fence,
                    &intent,
                    &payload,
                    &format!("prepare-{attempt}"),
                    22,
                )
                .await
                .expect("prepare both attempts");
            store
                .claim_taskflow_step(
                    "effect-run",
                    "work",
                    attempt,
                    &fence,
                    &intent,
                    &payload,
                    &format!("claim-{attempt}"),
                    23,
                )
                .await
                .expect("preclaim both attempts");
        }
        store
            .begin_effect_dispatch_attempt(
                "effect-run",
                "work",
                1,
                &fence,
                &intent,
                &payload,
                &key,
                wire,
                &binding,
                "provider:test",
                7,
                "grant-1",
                &nonce,
                "record-first",
                24,
            )
            .await
            .expect("original dispatch barrier");
        store
            .record_effect_dispatch_observation(
                "effect-run",
                "work",
                1,
                &fence,
                EffectDispatchObservationKind::ProvenAbsent,
                &Sha256Digest::for_bytes(b"actual-before-contact-proof"),
                25,
                /*provider_ack*/ None,
            )
            .await
            .expect("actual owner commits absence before projection settlement");
        assert!(
            store
                .begin_effect_dispatch_attempt(
                    "effect-run",
                    "work",
                    2,
                    &fence,
                    &intent,
                    &payload,
                    &key,
                    wire,
                    &binding,
                    "provider:test",
                    7,
                    "grant-2",
                    &Sha256Digest::for_bytes(b"effect-nonce-2"),
                    "record-second",
                    26,
                )
                .await
                .is_err()
        );
        assert_eq!(
            store
                .effect_dispatch_attempt("effect-run", "work", 2)
                .await
                .expect("no partial second barrier"),
            None
        );
        store.close().await;
        AutomationStore::open(&layout)
            .await
            .expect("absence cut remains recoverable");
    }
}
