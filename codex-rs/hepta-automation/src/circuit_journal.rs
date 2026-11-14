//! Append-only evidence and verified projection reads in AutomationStore's DB.

use std::collections::BTreeMap;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::BoundedCircuitDefinitionV2;
use crate::CircuitCommandReceiptV2;
use crate::CircuitCommandStatusV2;
use crate::CircuitRunV2;
use crate::TaskFlowError;
use crate::circuit_history::CircuitLedgerEventV2;
use crate::circuit_profile::hash;
use crate::circuit_profile::invalid;

pub(crate) struct CircuitHistoryV2 {
    pub definition: BoundedCircuitDefinitionV2,
    pub run: CircuitRunV2,
    pub commands: BTreeMap<String, Sha256Digest>,
    pub last_digest: Sha256Digest,
}

pub(crate) fn encode<T: Serialize>(value: &T) -> Result<String, TaskFlowError> {
    serde_json::to_string(value)
        .map_err(|e| TaskFlowError::Corrupt(format!("circuit serialization: {e}")))
}

pub(crate) fn unavailable(_: sqlx::Error) -> TaskFlowError {
    TaskFlowError::Unavailable
}

fn corrupt(message: &str) -> TaskFlowError {
    TaskFlowError::Corrupt(message.to_string())
}

pub(crate) async fn verify_owner(
    tx: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
) -> Result<(), TaskFlowError> {
    let actual: String =
        sqlx::query_scalar("SELECT owner_agent_id FROM automation_meta WHERE singleton = 1")
            .fetch_one(&mut **tx)
            .await
            .map_err(unavailable)?;
    if actual != owner.as_str() {
        return Err(TaskFlowError::StaleFence);
    }
    Ok(())
}

pub(crate) async fn register_definition(
    tx: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    definition: &BoundedCircuitDefinitionV2,
) -> Result<Sha256Digest, TaskFlowError> {
    let digest = definition.definition_digest()?;
    let json = encode(definition)?;
    if json.len() > 262_144 {
        return Err(invalid("circuit definition exceeds byte bound"));
    }
    let existing: Option<(String, String)> = sqlx::query_as(
        "SELECT definition_digest, definition_json FROM circuit_v2_definitions
         WHERE owner_agent_id = ? AND circuit_id = ? AND version = ?",
    )
    .bind(owner.as_str())
    .bind(&definition.circuit_id)
    .bind(i64::from(definition.version))
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?;
    if let Some((existing_digest, existing_json)) = existing {
        if existing_digest != digest.as_str() || existing_json != json {
            return Err(TaskFlowError::Conflict(
                "circuit version already has different bytes".to_string(),
            ));
        }
        return Ok(digest);
    }
    if let Some(predecessor) = &definition.predecessor_digest {
        let existing: Option<String> = sqlx::query_scalar(
            "SELECT definition_digest FROM circuit_v2_definitions
             WHERE owner_agent_id = ? AND circuit_id = ? AND version = ?",
        )
        .bind(owner.as_str())
        .bind(&definition.circuit_id)
        .bind(i64::from(definition.version - 1))
        .fetch_optional(&mut **tx)
        .await
        .map_err(unavailable)?;
        if existing.as_deref() != Some(predecessor.as_str()) {
            return Err(invalid("circuit predecessor is not registered"));
        }
    }
    sqlx::query("INSERT INTO circuit_v2_definitions VALUES (?, ?, ?, ?, ?)")
        .bind(owner.as_str())
        .bind(&definition.circuit_id)
        .bind(i64::from(definition.version))
        .bind(digest.as_str())
        .bind(json)
        .execute(&mut **tx)
        .await
        .map_err(unavailable)?;
    Ok(digest)
}

pub(crate) fn event_digest(
    run: &CircuitRunV2,
    command_id: &str,
    command_digest: &Sha256Digest,
    previous: &Sha256Digest,
) -> Result<Sha256Digest, TaskFlowError> {
    hash(
        "hepta.circuit.event.v2",
        &(
            &run.owner_agent_id,
            &run.run_id,
            run.revision,
            command_id,
            command_digest,
            previous,
            run.state_digest()?,
        ),
    )
}

pub(crate) async fn append(
    tx: &mut Transaction<'_, Sqlite>,
    run: &CircuitRunV2,
    command_id: &str,
    event: &CircuitLedgerEventV2,
    previous: &Sha256Digest,
) -> Result<Sha256Digest, TaskFlowError> {
    let json = encode(event)?;
    if json.len() > 131_072 {
        return Err(invalid("circuit event exceeds byte bound"));
    }
    let command_digest = hash("hepta.circuit.command.v2", event)?;
    let digest = event_digest(run, command_id, &command_digest, previous)?;
    sqlx::query("INSERT INTO circuit_v2_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
        .bind(&run.owner_agent_id)
        .bind(&run.run_id)
        .bind(i64::try_from(run.revision).map_err(|_| invalid("revision overflow"))?)
        .bind(command_id)
        .bind(command_digest.as_str())
        .bind(json)
        .bind(previous.as_str())
        .bind(run.state_digest()?.as_str())
        .bind(digest.as_str())
        .execute(&mut **tx)
        .await
        .map_err(unavailable)?;
    Ok(digest)
}

pub(crate) async fn load(
    tx: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    run_id: &str,
) -> Result<Option<CircuitHistoryV2>, TaskFlowError> {
    verify_owner(tx, owner).await?;
    let row = sqlx::query(
        "SELECT r.definition_digest, r.revision, r.state_json, r.state_digest,
            r.last_event_digest, d.definition_json FROM circuit_v2_runs r
         LEFT JOIN circuit_v2_definitions d
           ON d.owner_agent_id = r.owner_agent_id AND d.definition_digest = r.definition_digest
         WHERE r.owner_agent_id = ? AND r.run_id = ?",
    )
    .bind(owner.as_str())
    .bind(run_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?;
    let Some(row) = row else {
        return Ok(None);
    };
    let definition_json = row
        .try_get::<Option<String>, _>("definition_json")
        .map_err(unavailable)?
        .ok_or_else(|| corrupt("circuit lost its immutable definition"))?;
    if definition_json.len() > 262_144 {
        return Err(corrupt("oversized circuit definition"));
    }
    let definition: BoundedCircuitDefinitionV2 = serde_json::from_str(&definition_json)
        .map_err(|_| corrupt("invalid circuit definition"))?;
    let stored_digest: String = row.try_get("definition_digest").map_err(unavailable)?;
    if definition.definition_digest()?.as_str() != stored_digest
        || encode(&definition)? != definition_json
    {
        return Err(corrupt("circuit definition binding changed"));
    }
    let max_events = u64::from(definition.limits.max_events)
        + 3 * u64::from(definition.limits.max_activations)
        + 64;
    let mut run = None;
    let mut commands = BTreeMap::new();
    let mut previous = Sha256Digest::for_bytes(b"hepta.circuit.genesis.v2");
    let mut expected_seq = 0_u64;
    loop {
        // Bound memory independently of total run history. Keep the same SQLite
        // snapshot while replaying these pages; no observer can splice a tail.
        let events = sqlx::query(
            "SELECT * FROM circuit_v2_events
            WHERE owner_agent_id = ? AND run_id = ? AND seq >= ? ORDER BY seq LIMIT 128",
        )
        .bind(owner.as_str())
        .bind(run_id)
        .bind(i64::try_from(expected_seq).map_err(|_| corrupt("event count overflow"))?)
        .fetch_all(&mut **tx)
        .await
        .map_err(unavailable)?;
        if events.is_empty() {
            break;
        }
        for event in events {
            if expected_seq > max_events {
                return Err(corrupt("circuit event history exceeds profile"));
            }
            let seq: i64 = event.try_get("seq").map_err(unavailable)?;
            let json: String = event.try_get("event_json").map_err(unavailable)?;
            let previous_digest: String = event.try_get("previous_digest").map_err(unavailable)?;
            if u64::try_from(seq).ok() != Some(expected_seq)
                || previous_digest != previous.as_str()
                || json.len() > 131_072
            {
                return Err(corrupt("circuit event chain is discontinuous or oversized"));
            }
            let payload: CircuitLedgerEventV2 =
                serde_json::from_str(&json).map_err(|_| corrupt("invalid circuit event"))?;
            if encode(&payload)? != json {
                return Err(corrupt("noncanonical circuit event"));
            }
            let command_id: String = event.try_get("command_id").map_err(unavailable)?;
            crate::circuit_profile::text(&command_id)?;
            let command_digest = hash("hepta.circuit.command.v2", &payload)?;
            let stored_command: String = event.try_get("command_digest").map_err(unavailable)?;
            if stored_command != command_digest.as_str()
                || commands
                    .insert(command_id.clone(), command_digest.clone())
                    .is_some()
            {
                return Err(corrupt("circuit command changed or repeats"));
            }
            let (next, _) = payload.replay(run.as_ref(), &definition, owner)?;
            if next.run_id != run_id
                || next.revision != expected_seq
                || next.owner_agent_id != owner.as_str()
            {
                return Err(corrupt("circuit replay identity mismatch"));
            }
            let digest = event_digest(&next, &command_id, &command_digest, &previous)?;
            let stored_event: String = event.try_get("event_digest").map_err(unavailable)?;
            let stored_state: String = event.try_get("state_digest").map_err(unavailable)?;
            if stored_event != digest.as_str() || stored_state != next.state_digest()?.as_str() {
                return Err(corrupt("circuit event or state digest mismatch"));
            }
            previous = digest;
            run = Some(next);
            expected_seq += 1;
        }
    }
    let run = run.ok_or_else(|| corrupt("circuit has no creation event"))?;
    let state_json: String = row.try_get("state_json").map_err(unavailable)?;
    let state_digest: String = row.try_get("state_digest").map_err(unavailable)?;
    let last_digest: String = row.try_get("last_event_digest").map_err(unavailable)?;
    let revision: i64 = row.try_get("revision").map_err(unavailable)?;
    if u64::try_from(revision).ok() != Some(run.revision)
        || state_json.len() > 8_388_608
        || state_json != encode(&run)?
        || state_digest != run.state_digest()?.as_str()
        || last_digest != previous.as_str()
    {
        return Err(corrupt(
            "circuit projection differs from its causal history",
        ));
    }
    Ok(Some(CircuitHistoryV2 {
        definition,
        run,
        commands,
        last_digest: previous,
    }))
}

/// Shared transaction tail for ordinary commands and the sealed computation
/// claim. The caller has already loaded history under the SQLite writer lock.
pub(crate) async fn persist_transition(
    tx: &mut Transaction<'_, Sqlite>,
    history: &CircuitHistoryV2,
    owner: &AgentId,
    command_id: &str,
    event: &CircuitLedgerEventV2,
) -> Result<CircuitCommandReceiptV2, TaskFlowError> {
    if encode(event)?.len() > 131_072 {
        return Err(invalid("circuit command exceeds byte bound"));
    }
    let command_digest = hash("hepta.circuit.command.v2", event)?;
    if let Some(existing) = history.commands.get(command_id) {
        if existing != &command_digest {
            return Err(TaskFlowError::Conflict(
                "circuit command ID has different bytes".to_string(),
            ));
        }
        return Ok(CircuitCommandReceiptV2 {
            status: CircuitCommandStatusV2::AlreadyApplied,
            run: history.run.clone(),
            dispatches: Vec::new(),
        });
    }
    // Reserve claim/unknown/reconciliation slots for every admitted activation
    // beyond the normal event horizon, plus a bounded lease-transition allowance.
    let maximum = u64::from(history.definition.limits.max_events)
        + 3 * u64::from(history.definition.limits.max_activations)
        + 64;
    if history.run.revision >= maximum {
        return Err(invalid("circuit recovery history bound reached"));
    }
    let (run, dispatches) = event.replay(Some(&history.run), &history.definition, owner)?;
    let state_json = encode(&run)?;
    if state_json.len() > 8_388_608 {
        return Err(invalid("circuit state exceeds byte bound"));
    }
    let last_digest = event_digest(&run, command_id, &command_digest, &history.last_digest)?;
    let changed = sqlx::query(
        "UPDATE circuit_v2_runs
         SET revision = ?, state_json = ?, state_digest = ?, last_event_digest = ?
         WHERE owner_agent_id = ? AND run_id = ? AND revision = ? AND state_digest = ?",
    )
    .bind(i64::try_from(run.revision).map_err(|_| invalid("revision overflow"))?)
    .bind(state_json)
    .bind(run.state_digest()?.as_str())
    .bind(last_digest.as_str())
    .bind(owner.as_str())
    .bind(&run.run_id)
    .bind(i64::try_from(history.run.revision).map_err(|_| invalid("revision overflow"))?)
    .bind(history.run.state_digest()?.as_str())
    .execute(&mut **tx)
    .await
    .map_err(unavailable)?;
    if changed.rows_affected() != 1 {
        return Err(TaskFlowError::StaleFence);
    }
    append(tx, &run, command_id, event, &history.last_digest).await?;
    Ok(CircuitCommandReceiptV2 {
        status: CircuitCommandStatusV2::Applied,
        run,
        dispatches,
    })
}
