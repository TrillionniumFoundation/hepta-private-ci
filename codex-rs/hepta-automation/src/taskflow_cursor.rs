//! Bounded native-turn snapshots in the existing TaskFlow owner's database.
//!
//! This is an append-only compare-and-swap cursor, not a second run owner.
//! The caller validates its typed frame and atomically retains the observation
//! inside that frame. This store verifies the existing run/fence and history;
//! it grants no model, tool, scheduler or final-use authority.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;
use std::collections::BTreeSet;

use crate::AutomationStore;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowRunState;
use crate::taskflow::load_taskflow_run_tx;

pub const MAX_TASKFLOW_CURSOR_PAYLOAD_BYTES: usize = 512 * 1024;
const MAX_HISTORY_BYTES: i64 = 16 * 1024 * 1024;
const MAX_REVISIONS: i64 = 2048;
const ZERO: &str = "0000000000000000000000000000000000000000000000000000000000000000";

/// Owner-retained snapshot. The digest covers its scope, original writer,
/// predecessor, timestamp and exact payload, not only the payload text.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TaskFlowCursor {
    pub run_id: String,
    pub turn_key: String,
    pub revision: u64,
    pub run_revision: u64,
    pub recorded_at_ms: u64,
    pub evidence_digest: Sha256Digest,
    pub payload: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Entry {
    schema_version: u32,
    owner_agent_id: String,
    run_id: String,
    turn_key: String,
    revision: u64,
    run_revision: u64,
    owner_id: String,
    owner_epoch: u64,
    generation: u64,
    fencing_token: String,
    previous_digest: String,
    payload: String,
    recorded_at_ms: u64,
}

impl AutomationStore {
    /// Observe the original cursor under the current run identity. An expired
    /// lease may observe; it cannot append or acquire execution authority.
    pub async fn taskflow_cursor(
        &self,
        run_id: &str,
        turn_key: &str,
        fence: &TaskFlowFence,
    ) -> Result<Option<TaskFlowCursor>, TaskFlowError> {
        validate_scope(self, run_id, turn_key, fence)?;
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let run = load_taskflow_run_tx(&mut tx, self.taskflow_owner_agent_id(), run_id)
            .await?
            .ok_or_else(|| conflict("cursor run does not exist"))?;
        if run.owner_id.is_some() {
            self.check_run_identity_fence(&run, fence)?;
        } else {
            // A terminal transition or a proven-absence requeue clears the
            // active lease. Read-only recovery uses the last owner tuple from
            // the already verified run history; an older owner cannot read
            // through a newer claim, and a never-claimed run has no witness.
            let previous = sqlx::query(
                "SELECT owner_id, owner_epoch, generation, fencing_token FROM taskflow_events WHERE owner_agent_id = ? AND run_id = ? AND owner_id IS NOT NULL ORDER BY event_seq DESC LIMIT 1",
            ).bind(fence.owner_agent_id.as_str()).bind(run_id)
                .fetch_optional(&mut *tx).await.map_err(unavailable)?
                .ok_or(TaskFlowError::StaleFence)?;
            if previous
                .try_get::<String, _>("owner_id")
                .map_err(unavailable)?
                != fence.owner_id
                || previous
                    .try_get::<i64, _>("owner_epoch")
                    .map_err(unavailable)?
                    != to_i64(fence.owner_epoch)?
                || previous
                    .try_get::<i64, _>("generation")
                    .map_err(unavailable)?
                    != to_i64(fence.generation)?
                || previous
                    .try_get::<String, _>("fencing_token")
                    .map_err(unavailable)?
                    != fence.fencing_token
            {
                return Err(TaskFlowError::StaleFence);
            }
        }
        let (cursor, _) = load_history(&mut tx, fence, run_id, turn_key).await?;
        tx.commit().await.map_err(unavailable)?;
        Ok(cursor)
    }

    /// Append a complete typed-owner snapshot and its observation together.
    /// Exact replay of an already committed successor returns that receipt.
    /// A conflicting predecessor, expired lease or terminal run cannot write.
    #[allow(
        clippy::too_many_arguments,
        reason = "all owner and CAS bindings are explicit"
    )]
    pub async fn commit_taskflow_cursor(
        &self,
        run_id: &str,
        turn_key: &str,
        fence: &TaskFlowFence,
        previous: Option<&TaskFlowCursor>,
        payload: &str,
        now_ms: u64,
    ) -> Result<TaskFlowCursor, TaskFlowError> {
        validate_scope(self, run_id, turn_key, fence)?;
        if payload.is_empty() || payload.len() > MAX_TASKFLOW_CURSOR_PAYLOAD_BYTES {
            return Err(TaskFlowError::Invalid("cursor payload bound".into()));
        }
        if previous.is_some_and(|p| p.run_id != run_id || p.turn_key != turn_key) {
            return Err(conflict("cursor predecessor scope"));
        }
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let run = load_taskflow_run_tx(&mut tx, self.taskflow_owner_agent_id(), run_id)
            .await?
            .ok_or_else(|| conflict("cursor run does not exist"))?;
        self.check_run_fence(&run, fence, now_ms)?;
        if now_ms < run.updated_at_ms || previous.is_some_and(|p| now_ms < p.recorded_at_ms) {
            return Err(conflict("cursor timestamp precedes its owner state"));
        }
        if matches!(
            run.state,
            TaskFlowRunState::Succeeded | TaskFlowRunState::Failed | TaskFlowRunState::Cancelled
        ) {
            return Err(conflict("terminal run cannot advance its cursor"));
        }
        let (current, retained_bytes) = load_history(&mut tx, fence, run_id, turn_key).await?;
        let revision = previous
            .map_or(0, |p| p.revision)
            .checked_add(1)
            .ok_or_else(|| conflict("cursor revision overflow"))?;
        let previous_digest = previous.map_or(ZERO, |p| p.evidence_digest.as_str());
        if let Some(current) = &current
            && current.revision == revision
            && current.payload == payload
        {
            // The predecessor was verified while replaying the whole chain.
            let row: String = sqlx::query_scalar(
                "SELECT previous_digest FROM taskflow_native_cursors WHERE owner_agent_id = ? AND run_id = ? AND turn_key = ? AND revision = ?",
            ).bind(fence.owner_agent_id.as_str()).bind(run_id).bind(turn_key)
                .bind(to_i64(revision)?).fetch_one(&mut *tx).await.map_err(unavailable)?;
            if row == previous_digest {
                tx.commit().await.map_err(unavailable)?;
                return Ok(current.clone());
            }
        }
        if current.as_ref() != previous {
            return Err(conflict("cursor compare-and-swap predecessor"));
        }
        if revision > MAX_REVISIONS as u64 {
            return Err(conflict("cursor revision budget"));
        }
        let entry = Entry {
            schema_version: 1,
            owner_agent_id: fence.owner_agent_id.to_string(),
            run_id: run_id.into(),
            turn_key: turn_key.into(),
            revision,
            run_revision: run.revision,
            owner_id: fence.owner_id.clone(),
            owner_epoch: fence.owner_epoch,
            generation: fence.generation,
            fencing_token: fence.fencing_token.clone(),
            previous_digest: previous_digest.into(),
            payload: payload.into(),
            recorded_at_ms: now_ms,
        };
        let encoded = serde_json::to_vec(&entry).map_err(|_| corrupt("cursor encoding"))?;
        if retained_bytes
            .checked_add(to_i64(encoded.len() as u64)?)
            .is_none_or(|v| v > MAX_HISTORY_BYTES)
        {
            return Err(conflict("cursor retained-byte budget"));
        }
        let digest = Sha256Digest::for_bytes(&encoded);
        sqlx::query(
            "INSERT INTO taskflow_native_cursors (owner_agent_id, run_id, turn_key, revision, previous_digest, evidence_digest, encoded) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ).bind(fence.owner_agent_id.as_str()).bind(run_id).bind(turn_key)
            .bind(to_i64(revision)?).bind(previous_digest).bind(digest.as_str()).bind(encoded)
            .execute(&mut *tx).await.map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(TaskFlowCursor {
            run_id: run_id.into(),
            turn_key: turn_key.into(),
            revision,
            run_revision: run.revision,
            recorded_at_ms: now_ms,
            evidence_digest: digest,
            payload: payload.into(),
        })
    }
}

async fn load_history(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    fence: &TaskFlowFence,
    run_id: &str,
    turn_key: &str,
) -> Result<(Option<TaskFlowCursor>, i64), TaskFlowError> {
    // Bound allocation even if an externally modified database bypassed the
    // API's per-entry and aggregate limits.
    let (count, bytes, malformed): (i64, i64, i64) = sqlx::query_as(
        "SELECT COUNT(*), COALESCE(SUM(length(CAST(encoded AS BLOB))), 0), COALESCE(MAX(CASE WHEN typeof(revision) != 'integer' OR typeof(encoded) != 'blob' OR length(CAST(encoded AS BLOB)) NOT BETWEEN 1 AND 4194304 OR typeof(previous_digest) != 'text' OR typeof(evidence_digest) != 'text' OR length(CAST(previous_digest AS BLOB)) != 64 OR length(CAST(evidence_digest AS BLOB)) != 64 THEN 1 ELSE 0 END), 0) FROM taskflow_native_cursors WHERE owner_agent_id = ? AND run_id = ? AND turn_key = ?",
    ).bind(fence.owner_agent_id.as_str()).bind(run_id).bind(turn_key)
        .fetch_one(&mut **tx).await.map_err(unavailable)?;
    if malformed != 0
        || !(0..=MAX_REVISIONS).contains(&count)
        || !(0..=MAX_HISTORY_BYTES).contains(&bytes)
    {
        return Err(corrupt("cursor history budget"));
    }
    let rows = sqlx::query(
        "SELECT revision, previous_digest, evidence_digest, encoded FROM taskflow_native_cursors WHERE owner_agent_id = ? AND run_id = ? AND turn_key = ? ORDER BY revision",
    ).bind(fence.owner_agent_id.as_str()).bind(run_id).bind(turn_key)
        .fetch_all(&mut **tx).await.map_err(unavailable)?;
    let mut previous = ZERO.to_string();
    let mut cursor = None;
    let mut verified_writers = BTreeSet::new();
    let mut last_run_revision = 0;
    let mut last_timestamp = 0;
    for (index, row) in rows.into_iter().enumerate() {
        let revision: i64 = row.try_get("revision").map_err(unavailable)?;
        let encoded: Vec<u8> = row.try_get("encoded").map_err(unavailable)?;
        let recorded_digest: String = row.try_get("evidence_digest").map_err(unavailable)?;
        let recorded_previous: String = row.try_get("previous_digest").map_err(unavailable)?;
        let digest = Sha256Digest::for_bytes(&encoded);
        let entry: Entry =
            serde_json::from_slice(&encoded).map_err(|_| corrupt("cursor document"))?;
        if revision != (index + 1) as i64
            || entry.revision != revision as u64
            || entry.schema_version != 1
            || entry.owner_agent_id != fence.owner_agent_id.as_str()
            || entry.run_id != run_id
            || entry.turn_key != turn_key
            || entry.previous_digest != previous
            || recorded_previous != previous
            || recorded_digest != digest.as_str()
            || entry.payload.is_empty()
            || entry.payload.len() > MAX_TASKFLOW_CURSOR_PAYLOAD_BYTES
            || entry.owner_id.is_empty()
            || entry.owner_id.len() > 256
            || entry.fencing_token.is_empty()
            || entry.fencing_token.len() > 256
            || entry.owner_epoch == 0
            || entry.generation == 0
            || entry.run_revision < last_run_revision
            || entry.recorded_at_ms < last_timestamp
        {
            return Err(corrupt("cursor scope, chain or payload"));
        }
        let writer = (
            entry.run_revision,
            entry.owner_id.clone(),
            entry.owner_epoch,
            entry.generation,
            entry.fencing_token.clone(),
        );
        if !verified_writers.contains(&writer) {
            let claimed: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM taskflow_events WHERE owner_agent_id = ? AND run_id = ? AND revision = ? AND owner_id = ? AND owner_epoch = ? AND generation = ? AND fencing_token = ? AND recorded_at_ms <= ?",
            ).bind(&entry.owner_agent_id).bind(&entry.run_id)
                .bind(to_i64(entry.run_revision)?).bind(&entry.owner_id)
                .bind(to_i64(entry.owner_epoch)?).bind(to_i64(entry.generation)?)
                .bind(&entry.fencing_token).bind(to_i64(entry.recorded_at_ms)?)
                .fetch_one(&mut **tx).await.map_err(unavailable)?;
            if claimed != 1 {
                return Err(corrupt("cursor writer has no verified run provenance"));
            }
            verified_writers.insert(writer);
        }
        last_run_revision = entry.run_revision;
        last_timestamp = entry.recorded_at_ms;
        previous = digest.as_str().to_owned();
        cursor = Some(TaskFlowCursor {
            run_id: entry.run_id,
            turn_key: entry.turn_key,
            revision: entry.revision,
            run_revision: entry.run_revision,
            recorded_at_ms: entry.recorded_at_ms,
            evidence_digest: digest,
            payload: entry.payload,
        });
    }
    Ok((cursor, bytes))
}

fn validate_scope(
    store: &AutomationStore,
    run: &str,
    turn: &str,
    fence: &TaskFlowFence,
) -> Result<(), TaskFlowError> {
    if &fence.owner_agent_id != store.taskflow_owner_agent_id() {
        return Err(TaskFlowError::StaleFence);
    }
    if [run, turn]
        .iter()
        .any(|v| v.is_empty() || v.len() > 256 || v.chars().any(char::is_control))
    {
        return Err(TaskFlowError::Invalid("cursor scope".into()));
    }
    Ok(())
}

fn to_i64(value: u64) -> Result<i64, TaskFlowError> {
    i64::try_from(value).map_err(|_| TaskFlowError::Invalid("cursor integer overflow".into()))
}

fn unavailable(_: sqlx::Error) -> TaskFlowError {
    TaskFlowError::Unavailable
}
fn conflict(message: &str) -> TaskFlowError {
    TaskFlowError::Conflict(message.into())
}
fn corrupt(message: &str) -> TaskFlowError {
    TaskFlowError::Corrupt(message.into())
}
