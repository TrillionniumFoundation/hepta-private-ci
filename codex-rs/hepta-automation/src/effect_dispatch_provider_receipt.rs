//! Bounded provider receipt facts within the existing TaskFlow effect ledger.
//! A receipt records an observation; it grants no dispatch or final-use authority.

use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckSource;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sqlx::QueryBuilder;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

use crate::TaskFlowError;
use crate::effect_dispatch_identity::validate_effect_dispatch_history;
use crate::effect_dispatch_ledger::EFFECT_DISPATCH_SELECT;
use crate::effect_dispatch_ledger::EffectDispatchAttempt;
use crate::effect_dispatch_ledger::EffectDispatchObservationKind;
use crate::effect_dispatch_ledger::effect_attempt_from_row;

const MAX_PROVIDER_RECEIPT_BYTES: usize = 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ProviderReceiptV1 {
    schema_version: u32,
    pub(crate) source: ProviderEffectAckSource,
    pub(crate) ack: ProviderEffectAck,
}

pub(crate) fn provider_receipt_digest(
    ack: &ProviderEffectAck,
    source: ProviderEffectAckSource,
) -> Sha256Digest {
    let mut bytes = b"hepta.automation.provider-receipt.v1\0".to_vec();
    bytes.extend_from_slice(&ack.schema_version.to_be_bytes());
    for field in [
        source.as_str(),
        ack.key.as_str(),
        ack.payload_sha256.as_str(),
        ack.provider_operation_id_sha256.as_str(),
    ] {
        bytes.extend_from_slice(field.as_bytes());
        bytes.push(0);
    }
    bytes.push(match ack.status {
        ProviderEffectAckStatus::Accepted => 1,
        ProviderEffectAckStatus::Completed => 2,
        ProviderEffectAckStatus::Rejected => 3,
    });
    Sha256Digest::for_bytes(&bytes)
}

impl ProviderReceiptV1 {
    fn parse(json: &str, intent: &ProviderEffectIntent) -> Result<Self, TaskFlowError> {
        if json.len() > MAX_PROVIDER_RECEIPT_BYTES {
            return Err(corrupt());
        }
        let receipt: Self = serde_json::from_str(json).map_err(|_| corrupt())?;
        if receipt.schema_version != 1
            || receipt.ack.validate_for(intent).is_err()
            || receipt.json()? != json
        {
            return Err(corrupt());
        }
        Ok(receipt)
    }

    fn json(&self) -> Result<String, TaskFlowError> {
        let json = serde_json::to_string(self).map_err(|_| corrupt())?;
        if json.len() > MAX_PROVIDER_RECEIPT_BYTES {
            return Err(corrupt());
        }
        Ok(json)
    }

    fn digest(&self) -> Sha256Digest {
        provider_receipt_digest(&self.ack, self.source)
    }

    pub(crate) fn kind(&self) -> EffectDispatchObservationKind {
        match self.ack.status {
            ProviderEffectAckStatus::Accepted => EffectDispatchObservationKind::Indeterminate,
            ProviderEffectAckStatus::Completed => EffectDispatchObservationKind::Succeeded,
            ProviderEffectAckStatus::Rejected => EffectDispatchObservationKind::Failed,
        }
    }
}

fn intent(attempt: &EffectDispatchAttempt) -> Result<ProviderEffectIntent, TaskFlowError> {
    let key = attempt.provider_effect_key.clone().ok_or_else(corrupt)?;
    Ok(ProviderEffectIntent::new(
        key,
        attempt.payload_digest.clone(),
    ))
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum ReceiptContinuation {
    Ordinary,
    SameAttemptAfterIndeterminate,
}

fn late_dispatch_completion(first: &ProviderReceiptV1, next: &ProviderReceiptV1) -> bool {
    first.source == ProviderEffectAckSource::StatusLookup
        && first.ack.status == ProviderEffectAckStatus::Accepted
        && next.source == ProviderEffectAckSource::DispatchResponse
        && next.ack.status == ProviderEffectAckStatus::Completed
}

fn compatible(
    first: &ProviderReceiptV1,
    next: Option<&ProviderReceiptV1>,
    kind: EffectDispatchObservationKind,
    continuation: ReceiptContinuation,
) -> Result<(), TaskFlowError> {
    let next = match next {
        Some(next) => next,
        None if kind == EffectDispatchObservationKind::Indeterminate => return Ok(()),
        None => return Err(conflict()),
    };
    if first.ack.provider_operation_id_sha256 != next.ack.provider_operation_id_sha256
        || (first.ack.status == ProviderEffectAckStatus::Accepted
            && next.ack.status == ProviderEffectAckStatus::Rejected)
        || (first.ack.status != ProviderEffectAckStatus::Accepted
            && first.ack.status != next.ack.status)
        || (first.source == ProviderEffectAckSource::StatusLookup
            && next.source == ProviderEffectAckSource::DispatchResponse
            && !(continuation == ReceiptContinuation::SameAttemptAfterIndeterminate
                && late_dispatch_completion(first, next)))
    {
        return Err(conflict());
    }
    Ok(())
}

/// Called inside the same write transaction as the existing observation. The
/// first accepted operation is never replaced, including by opaque recovery.
pub(crate) async fn bind_provider_receipt(
    transaction: &mut Transaction<'_, Sqlite>,
    owner: &str,
    attempt: &EffectDispatchAttempt,
    observation: (EffectDispatchObservationKind, &Sha256Digest, u64),
    ack: Option<(&ProviderEffectAck, ProviderEffectAckSource)>,
) -> Result<Option<String>, TaskFlowError> {
    let (kind, evidence_digest, observed_at_ms) = observation;
    let next = ack.map(|(ack, source)| ProviderReceiptV1 {
        schema_version: 1,
        source,
        ack: ack.clone(),
    });
    if let Some(next) = &next
        && (next.ack.validate_for(&intent(attempt)?).is_err()
            || next.kind() != kind
            || next.digest() != *evidence_digest)
    {
        return Err(conflict());
    }
    if let Some(first) = &attempt.provider_binding {
        let continuation = if attempt.provider_binding_attempt == Some(attempt.attempt)
            && attempt.observation.as_ref().is_some_and(|observation| {
                observation.kind == EffectDispatchObservationKind::Indeterminate
            }) {
            ReceiptContinuation::SameAttemptAfterIndeterminate
        } else {
            ReceiptContinuation::Ordinary
        };
        compatible(first, next.as_ref(), kind, continuation)?;
    }
    let Some(next) = next else {
        return Ok(None);
    };
    let json = next.json()?;
    if attempt.provider_binding.is_none() {
        sqlx::query(
            "INSERT INTO taskflow_effect_provider_bindings (
                owner_agent_id, run_id, step_id, attempt,
                receipt_json, receipt_digest, observed_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(owner)
        .bind(&attempt.run_id)
        .bind(&attempt.step_id)
        .bind(i64::from(attempt.attempt))
        .bind(&json)
        .bind(evidence_digest.as_str())
        .bind(i64::try_from(observed_at_ms).map_err(|_| conflict())?)
        .execute(&mut **transaction)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
    }
    Ok(Some(json))
}

pub(crate) fn validate_provider_projection(
    row: &sqlx::sqlite::SqliteRow,
    attempt: &EffectDispatchAttempt,
) -> Result<Option<ProviderReceiptV1>, TaskFlowError> {
    let binding_json: Option<String> =
        row.try_get("binding_receipt_json").map_err(|_| corrupt())?;
    let binding_digest: Option<String> = row
        .try_get("binding_receipt_digest")
        .map_err(|_| corrupt())?;
    let binding_attempt: Option<i64> = row.try_get("binding_attempt").map_err(|_| corrupt())?;
    let binding = match (binding_json, binding_digest, binding_attempt) {
        (None, None, None) => None,
        (Some(json), Some(digest), Some(first_attempt)) => {
            if first_attempt <= 0 || first_attempt > i64::from(attempt.attempt) {
                return Err(corrupt());
            }
            let binding = ProviderReceiptV1::parse(&json, &intent(attempt)?)?;
            if binding.digest().as_str() != digest {
                return Err(corrupt());
            }
            Some(binding)
        }
        _ => return Err(corrupt()),
    };
    let initial_kind: Option<String> = row.try_get("initial_observation").map_err(|_| corrupt())?;
    let reconciled_kind: Option<String> = row
        .try_get("reconciled_observation")
        .map_err(|_| corrupt())?;
    if reconciled_kind.is_some()
        && initial_kind.as_deref() != Some(EffectDispatchObservationKind::Indeterminate.as_str())
    {
        return Err(corrupt());
    }
    let mut initial_receipt = None;
    let mut reconciled_receipt = None;
    for prefix in ["initial", "reconciled"] {
        let json: Option<String> = row
            .try_get(format!("{prefix}_provider_receipt_json").as_str())
            .map_err(|_| corrupt())?;
        let Some(json) = json else { continue };
        let receipt = ProviderReceiptV1::parse(&json, &intent(attempt)?)?;
        let digest: String = row
            .try_get(format!("{prefix}_evidence_digest").as_str())
            .map_err(|_| corrupt())?;
        let kind: String = row
            .try_get(format!("{prefix}_observation").as_str())
            .map_err(|_| corrupt())?;
        if receipt.digest().as_str() != digest || receipt.kind().as_str() != kind {
            return Err(corrupt());
        }
        let first = binding.as_ref().ok_or_else(corrupt)?;
        let continuation = if prefix == "reconciled"
            && binding_attempt == Some(i64::from(attempt.attempt))
            && initial_kind.as_deref()
                == Some(EffectDispatchObservationKind::Indeterminate.as_str())
        {
            ReceiptContinuation::SameAttemptAfterIndeterminate
        } else {
            ReceiptContinuation::Ordinary
        };
        if prefix == "reconciled"
            && receipt.source != ProviderEffectAckSource::StatusLookup
            && !(continuation == ReceiptContinuation::SameAttemptAfterIndeterminate
                && late_dispatch_completion(first, &receipt))
        {
            return Err(corrupt());
        }
        compatible(first, Some(&receipt), receipt.kind(), continuation).map_err(|_| corrupt())?;
        if prefix == "initial" {
            initial_receipt = Some(receipt);
        } else {
            reconciled_receipt = Some(receipt);
        }
    }
    if let Some(first) = &binding {
        if attempt.observation.is_none() {
            return Err(corrupt());
        }
        if binding_attempt == Some(i64::from(attempt.attempt)) {
            if first.source == ProviderEffectAckSource::DispatchResponse
                && initial_receipt.as_ref() != Some(first)
            {
                return Err(corrupt());
            }
            // A lookup Accepted may bind an operation while preserving an
            // immutable Unknown observation. Terminal first receipts require
            // their matching observation in the same original transaction.
            if first.ack.status != ProviderEffectAckStatus::Accepted
                && initial_receipt.as_ref() != Some(first)
                && reconciled_receipt.as_ref() != Some(first)
            {
                return Err(corrupt());
            }
        }
        if let Some(observation) = &attempt.observation
            && observation.kind != EffectDispatchObservationKind::Indeterminate
        {
            let json: Option<String> = row
                .try_get("provider_receipt_json")
                .map_err(|_| corrupt())?;
            if json.is_none() {
                return Err(corrupt());
            }
        }
    }
    Ok(binding)
}

/// Full restart audit uses keyset pages; no receipt or row count is unbounded
/// in memory. Ordinary reads retain the existing indexed attempt lookup.
pub(crate) async fn verify_provider_receipts(
    pool: &SqlitePool,
    owner: &str,
) -> Result<(), TaskFlowError> {
    let mut transaction = pool.begin().await.map_err(|_| TaskFlowError::Unavailable)?;
    for (table, message) in [
        (
            "taskflow_effect_dispatch_attempts",
            "TaskFlow effect dispatch attempts are immutable",
        ),
        (
            "taskflow_effect_dispatch_observations",
            "TaskFlow effect dispatch observations are immutable",
        ),
        (
            "taskflow_effect_dispatch_reconciliations",
            "TaskFlow effect reconciliations are immutable",
        ),
        (
            "taskflow_effect_provider_bindings",
            "TaskFlow provider operation bindings are immutable",
        ),
    ] {
        for action in ["UPDATE", "DELETE"] {
            let suffix = action.to_ascii_lowercase();
            let name = format!("{table}_no_{suffix}");
            let expected = format!(
                "CREATE TRIGGER {name} BEFORE {action} ON {table}
                 BEGIN SELECT RAISE(ABORT, '{message}'); END"
            );
            let actual: Option<String> =
                sqlx::query_scalar("SELECT sql FROM sqlite_schema WHERE type='trigger' AND name=?")
                    .bind(&name)
                    .fetch_optional(&mut *transaction)
                    .await
                    .map_err(|_| TaskFlowError::Unavailable)?;
            if actual
                .as_deref()
                .map(|sql| sql.split_whitespace().collect::<String>())
                != Some(expected.split_whitespace().collect::<String>())
            {
                return Err(corrupt());
            }
        }
    }
    let mut cursor = (String::new(), String::new(), 0_i64);
    let mut checked_step: Option<(String, String)> = None;
    loop {
        let rows = {
            let mut query = QueryBuilder::<Sqlite>::new(EFFECT_DISPATCH_SELECT);
            query
                .push(" WHERE a.owner_agent_id=")
                .push_bind(owner)
                .push(" AND (a.run_id, a.step_id, a.attempt) > (")
                .push_bind(&cursor.0)
                .push(", ")
                .push_bind(&cursor.1)
                .push(", ")
                .push_bind(cursor.2)
                .push(") ORDER BY a.run_id, a.step_id, a.attempt LIMIT 128");
            query
                .build()
                .fetch_all(&mut *transaction)
                .await
                .map_err(|_| TaskFlowError::Unavailable)?
        };
        if rows.is_empty() {
            break;
        }
        for row in rows {
            let attempt = effect_attempt_from_row(row)?;
            if checked_step
                .as_ref()
                .is_none_or(|(run, step)| run != &attempt.run_id || step != &attempt.step_id)
            {
                validate_effect_dispatch_history(&mut transaction, &attempt).await?;
                checked_step = Some((attempt.run_id.clone(), attempt.step_id.clone()));
            }
            cursor = (attempt.run_id, attempt.step_id, i64::from(attempt.attempt));
        }
    }
    transaction
        .rollback()
        .await
        .map_err(|_| TaskFlowError::Unavailable)
}

fn conflict() -> TaskFlowError {
    TaskFlowError::Conflict("provider receipt differs from the original effect".to_string())
}

fn corrupt() -> TaskFlowError {
    TaskFlowError::Corrupt("invalid durable provider receipt".to_string())
}
