//! Original SQLite transaction operations and startup/recovery semantic audit.

use super::ObjectiveSenderError;
use super::ObjectiveSenderSnapshot;
use super::model::*;
use crate::CognitiveStoreError;
use crate::cognitive_store::unavailable;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use sqlx::Sqlite;
use sqlx::Transaction;

#[path = "objective_sender_integrity.rs"]
mod integrity;
use integrity::decode_request;
use integrity::read_events;
pub(crate) use integrity::verify_sender_store;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum EventKind {
    PermitIssued,
    SubmissionObserved,
    HistoryObserved,
    LocalCancelled,
}

impl EventKind {
    fn text(self) -> &'static str {
        match self {
            Self::PermitIssued => "permit_issued",
            Self::SubmissionObserved => "submission_observed",
            Self::HistoryObserved => "history_observed",
            Self::LocalCancelled => "local_cancelled",
        }
    }

    fn parse(value: &str) -> Result<Self, ObjectiveSenderError> {
        match value {
            "permit_issued" => Ok(Self::PermitIssued),
            "submission_observed" => Ok(Self::SubmissionObserved),
            "history_observed" => Ok(Self::HistoryObserved),
            "local_cancelled" => Ok(Self::LocalCancelled),
            _ => Err(corrupt()),
        }
    }
}

impl From<ObjectiveSenderObservationKind> for EventKind {
    fn from(value: ObjectiveSenderObservationKind) -> Self {
        match value {
            ObjectiveSenderObservationKind::Submission => Self::SubmissionObserved,
            ObjectiveSenderObservationKind::History => Self::HistoryObserved,
        }
    }
}

struct Event {
    kind: EventKind,
    observation: String,
    digest: String,
}

#[derive(Clone, Copy)]
enum ExistingPermit {
    Required,
    Fresh,
}

fn corrupt() -> ObjectiveSenderError {
    CognitiveStoreError::Corrupt("Objective sender domain integrity mismatch".to_string()).into()
}

fn binding_json(
    request: &ObjectiveSenderRequest,
    fence: &OwnerFence,
) -> Result<String, ObjectiveSenderError> {
    if request.origin.agent_id != fence.owner_agent_id {
        return Err(ObjectiveSenderError::IdentityMismatch);
    }
    let json = serde_json::to_string(&Binding {
        origin: request.origin.clone(),
        fence: fence.clone(),
    })
    .map_err(|_| corrupt())?;
    if json.len() > 4096 {
        return Err(ObjectiveSenderInputError::Bound.into());
    }
    Ok(json)
}

pub(super) async fn retain(
    tx: &mut Transaction<'_, Sqlite>,
    request: &ObjectiveSenderRequest,
    fence: &OwnerFence,
) -> Result<(), ObjectiveSenderError> {
    let identity = &request.identity;
    let present: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_objective_sender_requests WHERE
         request_sha256 = ? OR (owner_agent_id = ? AND (run_id = ? OR
         (issuer_id = ? AND key_epoch = ? AND (message_id = ? OR message_sequence = ?))))",
    )
    .bind(identity.original_sha256.as_str())
    .bind(request.origin.agent_id.as_str())
    .bind(&identity.run_id)
    .bind(&identity.issuer_id)
    .bind(identity.key_epoch as i64)
    .bind(&identity.message_id)
    .bind(identity.sequence as i64)
    .fetch_one(&mut **tx)
    .await
    .map_err(unavailable)?;
    if present != 0 {
        return Err(ObjectiveSenderError::AlreadyRetained);
    }
    let binding = binding_json(request, fence)?;
    reserve(
        tx,
        /*requests*/ 1,
        /*events*/ 0,
        (request.original.len() + binding.len() + 1024) as i64,
    )
    .await?;
    let record = request_digest(&request.original, &binding);
    sqlx::query(
        "INSERT INTO cognitive_objective_sender_requests
         (request_sha256, owner_agent_id, run_id, issuer_id, key_epoch, message_id,
          message_sequence, original_json, binding_json, record_sha256, lease_id,
          lease_sha256, permit_sequence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
    )
    .bind(identity.original_sha256.as_str())
    .bind(request.origin.agent_id.as_str())
    .bind(&identity.run_id)
    .bind(&identity.issuer_id)
    .bind(identity.key_epoch as i64)
    .bind(&identity.message_id)
    .bind(identity.sequence as i64)
    .bind(&request.original)
    .bind(&binding)
    .bind(record.as_str())
    .bind(&fence.lease_id)
    .bind(fence.lease_sha256.as_str())
    .execute(&mut **tx)
    .await
    .map_err(unavailable)?;
    append(tx, request, fence, EventKind::PermitIssued, "null").await
}

pub(super) async fn require_request(
    tx: &mut Transaction<'_, Sqlite>,
    request: &ObjectiveSenderRequest,
) -> Result<(), ObjectiveSenderError> {
    let row =
        sqlx::query("SELECT * FROM cognitive_objective_sender_requests WHERE request_sha256 = ?")
            .bind(request.identity.original_sha256.as_str())
            .fetch_optional(&mut **tx)
            .await
            .map_err(unavailable)?
            .ok_or(ObjectiveSenderError::Missing)?;
    let retained = decode_request(tx, &row).await?;
    if retained != *request {
        return Err(ObjectiveSenderError::IdentityMismatch);
    }
    Ok(())
}

pub(super) async fn retained_page(
    tx: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    after: &str,
) -> Result<Vec<ObjectiveSenderRequest>, ObjectiveSenderError> {
    reserve(tx, /*requests*/ 0, /*events*/ 0, /*bytes*/ 0).await?;
    let foreign: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_objective_sender_requests WHERE owner_agent_id <> ?",
    )
    .bind(owner.as_str())
    .fetch_one(&mut **tx)
    .await
    .map_err(unavailable)?;
    if foreign != 0 {
        return Err(corrupt());
    }
    let rows = sqlx::query("SELECT * FROM cognitive_objective_sender_requests WHERE owner_agent_id = ? AND request_sha256 > ? ORDER BY request_sha256 LIMIT 17")
        .bind(owner.as_str()).bind(after).fetch_all(&mut **tx).await.map_err(unavailable)?;
    let mut requests = Vec::with_capacity(rows.len());
    for row in rows {
        let request = decode_request(tx, &row).await?;
        read_events(tx, &request, ExistingPermit::Required).await?;
        requests.push(request);
    }
    Ok(requests)
}

pub(super) async fn append(
    tx: &mut Transaction<'_, Sqlite>,
    request: &ObjectiveSenderRequest,
    fence: &OwnerFence,
    kind: EventKind,
    observation: &str,
) -> Result<(), ObjectiveSenderError> {
    let permit = match kind {
        EventKind::PermitIssued => ExistingPermit::Fresh,
        EventKind::SubmissionObserved | EventKind::HistoryObserved | EventKind::LocalCancelled => {
            ExistingPermit::Required
        }
    };
    let events = read_events(tx, request, permit).await?;
    if events
        .iter()
        .any(|event| event.kind == kind && event.observation == observation)
    {
        return Ok(());
    }
    if events
        .iter()
        .any(|event| event.kind == EventKind::LocalCancelled)
        || (kind == EventKind::LocalCancelled && events.len() != 1)
        || (kind == EventKind::SubmissionObserved && events.iter().any(|event| event.kind == kind))
    {
        return Err(ObjectiveSenderError::ObservationConflict);
    }
    let sequence = events.len() as i64 + 1;
    if sequence > MAX_EVENTS_PER_REQUEST {
        return Err(ObjectiveSenderError::Capacity);
    }
    let previous = events
        .last()
        .map_or(ZERO_DIGEST, |event| event.digest.as_str());
    let binding = binding_json(request, fence)?;
    reserve(
        tx,
        /*requests*/ 0,
        /*events*/ 1,
        (observation.len() + binding.len() + 1024) as i64,
    )
    .await?;
    let request_sha = request.identity.original_sha256.as_str();
    let digest = event_digest(
        request_sha,
        sequence,
        kind.text(),
        observation,
        &binding,
        previous,
    );
    sqlx::query(
        "INSERT INTO cognitive_objective_sender_events
         (request_sha256, event_sequence, event_kind, observation_json, observation_sha256,
          binding_json, previous_sha256, event_sha256, lease_id, lease_sha256)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(request_sha)
    .bind(sequence)
    .bind(kind.text())
    .bind(observation)
    .bind(Sha256Digest::for_bytes(observation.as_bytes()).as_str())
    .bind(&binding)
    .bind(previous)
    .bind(digest.as_str())
    .bind(&fence.lease_id)
    .bind(fence.lease_sha256.as_str())
    .execute(&mut **tx)
    .await
    .map_err(unavailable)?;
    Ok(())
}

pub(super) async fn snapshot(
    tx: &mut Transaction<'_, Sqlite>,
    request: &ObjectiveSenderRequest,
) -> Result<ObjectiveSenderSnapshot, ObjectiveSenderError> {
    let events = read_events(tx, request, ExistingPermit::Required).await?;
    let locally_cancelled = events
        .last()
        .is_some_and(|event| event.kind == EventKind::LocalCancelled);
    let observations = events
        .into_iter()
        .filter_map(|event| match event.kind {
            EventKind::PermitIssued | EventKind::LocalCancelled => None,
            EventKind::SubmissionObserved => Some(ObjectiveSenderObservation {
                kind: ObjectiveSenderObservationKind::Submission,
                exact_json: event.observation,
            }),
            EventKind::HistoryObserved => Some(ObjectiveSenderObservation {
                kind: ObjectiveSenderObservationKind::History,
                exact_json: event.observation,
            }),
        })
        .collect();
    Ok(ObjectiveSenderSnapshot {
        observations,
        locally_cancelled,
    })
}

async fn reserve(
    tx: &mut Transaction<'_, Sqlite>,
    requests: i64,
    events: i64,
    bytes: i64,
) -> Result<(), ObjectiveSenderError> {
    let request_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_objective_sender_requests")
            .fetch_one(&mut **tx)
            .await
            .map_err(unavailable)?;
    let event_count: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_objective_sender_events")
            .fetch_one(&mut **tx)
            .await
            .map_err(unavailable)?;
    let retained: i64 = sqlx::query_scalar(
        "SELECT (SELECT COALESCE(SUM(length(CAST(original_json AS BLOB)) + length(CAST(binding_json AS BLOB)) + 1024), 0) FROM cognitive_objective_sender_requests)
         + (SELECT COALESCE(SUM(length(CAST(observation_json AS BLOB)) + length(CAST(binding_json AS BLOB)) + 1024), 0) FROM cognitive_objective_sender_events)",
    ).fetch_one(&mut **tx).await.map_err(unavailable)?;
    if request_count + requests > MAX_REQUESTS
        || event_count + events > MAX_EVENTS
        || retained + bytes > MAX_RETAINED_BYTES
    {
        return Err(ObjectiveSenderError::Capacity);
    }
    Ok(())
}
