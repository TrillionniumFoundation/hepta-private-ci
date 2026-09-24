#!/usr/bin/env python3
"""Materialize the bounded automation.taskflow recovery convergence slice.

This script is intentionally one-shot and assertion-heavy. It edits the existing
TaskFlow/Agentd owners in place; it does not introduce a second scheduler, store,
executor, authority, or closure branch.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one marker, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"{label}: start marker missing")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"{label}: end marker missing")
    return text[:start_index] + replacement + text[end_index + len(end):]


# Schema v20: durable round-robin discovery cursor. The cursor is not effect or
# terminal authority and never changes occurrence identity.
migration_path = ROOT / "codex-rs/hepta-automation/migrations/0020_occurrence_recovery_cursor.sql"
if migration_path.exists():
    raise RuntimeError("schema v20 migration already exists; refuse ambiguous reapplication")
migration_path.write_text(
    """-- Durable round-robin recovery discovery for non-terminal occurrences.
-- The cursor is discovery progress only; it grants no execution, effect, or
-- terminal authority and never changes occurrence identity or outcome.
CREATE TABLE automation_occurrence_recovery_cursor (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    owner_agent_id TEXT NOT NULL,
    last_updated_at_ms INTEGER NOT NULL CHECK (last_updated_at_ms >= 0),
    last_task_id TEXT NOT NULL,
    last_occurrence INTEGER NOT NULL CHECK (last_occurrence > 0)
);

CREATE INDEX automation_occurrence_pending_rotation_idx
ON automation_occurrence_lifecycle (
    owner_agent_id, updated_at_ms, task_id, occurrence
)
WHERE state IN ('admitted', 'running', 'indeterminate');

DROP TRIGGER automation_meta_no_update;
UPDATE automation_meta SET schema_version = 20 WHERE singleton = 1;
CREATE TRIGGER automation_meta_no_update
BEFORE UPDATE ON automation_meta
BEGIN
    SELECT RAISE(ABORT, 'automation owner metadata is immutable');
END;
"""
)

# Update schema constant.
path = "codex-rs/hepta-automation/src/lib.rs"
text = read(path)
text = replace_once(
    text,
    "pub const AUTOMATION_SCHEMA_VERSION: u32 = 19;",
    "pub const AUTOMATION_SCHEMA_VERSION: u32 = 20;",
    "automation schema version",
)
write(path, text)

# Durable fair discovery plus exact identity reads.
path = "codex-rs/hepta-automation/src/lifecycle.rs"
text = read(path)
text = replace_once(
    text,
    "use codex_hepta_contracts::Sha256Digest;",
    "use codex_hepta_contracts::AgentId;\nuse codex_hepta_contracts::Sha256Digest;",
    "AgentId import",
)
start = """    /// Return a bounded set of non-terminal occurrences that already crossed
    /// Core admission or need explicit reconciliation. Claimed pre-admission
    /// work remains owned by the scheduler lease/uncertainty path.
    pub async fn pending_occurrence_work(
"""
end = """}

pub fn deterministic_occurrence_id(
"""
replacement = """    /// Return a bounded read-only snapshot of non-terminal occurrences. This
    /// API does not advance the product recovery cursor and is intended for
    /// diagnostics and bounded inspection, not scheduler discovery.
    pub async fn pending_occurrence_work(
        &self,
        limit: usize,
    ) -> Result<Vec<AutomationOccurrenceWork>, AutomationError> {
        if limit == 0 || limit > MAX_RECOVERY_SCAN {
            return Err(AutomationError::Invalid);
        }
        let rows = sqlx::query(
            \"SELECT o.*, t.thread_id, t.prompt
             FROM automation_occurrence_lifecycle o
             JOIN automation_tasks t ON t.task_id = o.task_id
             WHERE o.owner_agent_id = ?
               AND o.state IN ('admitted', 'running', 'indeterminate')
             ORDER BY o.updated_at_ms, o.task_id, o.occurrence
             LIMIT ?\",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(i64::try_from(limit).map_err(|_| AutomationError::Invalid)?)
        .fetch_all(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        rows.iter()
            .map(|row| occurrence_work_from_row(row, self.taskflow_owner_agent_id()))
            .collect()
    }

    /// Read one known pending occurrence by its exact durable identity. A
    /// caller that already holds `(task_id, occurrence)` must never intersect
    /// that identity with a truncated global recovery page.
    pub async fn pending_occurrence_work_exact(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
    ) -> Result<Option<AutomationOccurrenceWork>, AutomationError> {
        let row = sqlx::query(
            \"SELECT o.*, t.thread_id, t.prompt
             FROM automation_occurrence_lifecycle o
             JOIN automation_tasks t ON t.task_id = o.task_id
             WHERE o.owner_agent_id = ? AND o.task_id = ? AND o.occurrence = ?
               AND o.state IN ('admitted', 'running', 'indeterminate')\",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        row.as_ref()
            .map(|row| occurrence_work_from_row(row, self.taskflow_owner_agent_id()))
            .transpose()
    }

    /// Select one pending occurrence and durably advance a round-robin cursor.
    /// The cursor is owner-local discovery progress only. It prevents one
    /// long-running occurrence from monopolizing every recovery pass while
    /// preserving the occurrence's immutable identity and outcome state.
    pub async fn next_pending_occurrence_work(
        &self,
    ) -> Result<Option<AutomationOccurrenceWork>, AutomationError> {
        let (mut transaction, _) = self.begin_timer_write().await?;
        let cursor = sqlx::query(
            \"SELECT owner_agent_id, last_updated_at_ms, last_task_id, last_occurrence
             FROM automation_occurrence_recovery_cursor WHERE singleton = 1\",
        )
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?;

        let mut row = None;
        if let Some(cursor) = cursor {
            let owner: String = cursor
                .try_get(\"owner_agent_id\")
                .map_err(|_| AutomationError::Corrupt)?;
            if owner != self.taskflow_owner_agent_id().as_str() {
                return Err(AutomationError::AccessDenied);
            }
            let last_updated_at_ms: i64 = cursor
                .try_get(\"last_updated_at_ms\")
                .map_err(|_| AutomationError::Corrupt)?;
            let last_task_id: String = cursor
                .try_get(\"last_task_id\")
                .map_err(|_| AutomationError::Corrupt)?;
            let last_occurrence: i64 = cursor
                .try_get(\"last_occurrence\")
                .map_err(|_| AutomationError::Corrupt)?;
            row = sqlx::query(
                \"SELECT o.*, t.thread_id, t.prompt
                 FROM automation_occurrence_lifecycle o
                 JOIN automation_tasks t ON t.task_id = o.task_id
                 WHERE o.owner_agent_id = ?
                   AND o.state IN ('admitted', 'running', 'indeterminate')
                   AND (o.updated_at_ms > ?
                        OR (o.updated_at_ms = ? AND o.task_id > ?)
                        OR (o.updated_at_ms = ? AND o.task_id = ? AND o.occurrence > ?))
                 ORDER BY o.updated_at_ms, o.task_id, o.occurrence
                 LIMIT 1\",
            )
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(last_updated_at_ms)
            .bind(last_updated_at_ms)
            .bind(&last_task_id)
            .bind(last_updated_at_ms)
            .bind(&last_task_id)
            .bind(last_occurrence)
            .fetch_optional(&mut *transaction)
            .await
            .map_err(unavailable)?;
        }
        if row.is_none() {
            row = sqlx::query(
                \"SELECT o.*, t.thread_id, t.prompt
                 FROM automation_occurrence_lifecycle o
                 JOIN automation_tasks t ON t.task_id = o.task_id
                 WHERE o.owner_agent_id = ?
                   AND o.state IN ('admitted', 'running', 'indeterminate')
                 ORDER BY o.updated_at_ms, o.task_id, o.occurrence
                 LIMIT 1\",
            )
            .bind(self.taskflow_owner_agent_id().as_str())
            .fetch_optional(&mut *transaction)
            .await
            .map_err(unavailable)?;
        }
        let Some(row) = row else {
            transaction.commit().await.map_err(unavailable)?;
            return Ok(None);
        };
        let work = occurrence_work_from_row(&row, self.taskflow_owner_agent_id())?;
        let updated = sqlx::query(
            \"INSERT INTO automation_occurrence_recovery_cursor (
                 singleton, owner_agent_id, last_updated_at_ms, last_task_id, last_occurrence
             ) VALUES (1, ?, ?, ?, ?)
             ON CONFLICT(singleton) DO UPDATE SET
                 last_updated_at_ms = excluded.last_updated_at_ms,
                 last_task_id = excluded.last_task_id,
                 last_occurrence = excluded.last_occurrence
             WHERE automation_occurrence_recovery_cursor.owner_agent_id = excluded.owner_agent_id\",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(to_i64(work.occurrence.updated_at_ms)?)
        .bind(work.occurrence.task_id.to_string())
        .bind(to_i64(work.occurrence.occurrence)?)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::AccessDenied);
        }
        transaction.commit().await.map_err(unavailable)?;
        Ok(Some(work))
    }
}

pub fn deterministic_occurrence_id(
"""
text = replace_between(text, start, end, replacement, "pending recovery APIs")

old_verify = """pub(crate) async fn verify_occurrence_store(
    pool: &sqlx::SqlitePool,
    expected_owner: &str,
) -> Result<(), AutomationError> {
    let rows =
        sqlx::query(\"SELECT * FROM automation_occurrence_lifecycle ORDER BY task_id, occurrence\")
            .fetch_all(pool)
            .await
            .map_err(unavailable)?;
    for row in &rows {
        occurrence_from_row(row, expected_owner)?;
    }
    Ok(())
}

fn occurrence_from_row(
"""
new_verify = """pub(crate) async fn verify_occurrence_store(
    pool: &sqlx::SqlitePool,
    expected_owner: &str,
) -> Result<(), AutomationError> {
    let rows =
        sqlx::query(\"SELECT * FROM automation_occurrence_lifecycle ORDER BY task_id, occurrence\")
            .fetch_all(pool)
            .await
            .map_err(unavailable)?;
    for row in &rows {
        occurrence_from_row(row, expected_owner)?;
    }
    if let Some(cursor) = sqlx::query(
        \"SELECT owner_agent_id, last_updated_at_ms, last_task_id, last_occurrence
         FROM automation_occurrence_recovery_cursor WHERE singleton = 1\",
    )
    .fetch_optional(pool)
    .await
    .map_err(unavailable)?
    {
        let owner: String = cursor
            .try_get(\"owner_agent_id\")
            .map_err(|_| AutomationError::Corrupt)?;
        let updated_at_ms: i64 = cursor
            .try_get(\"last_updated_at_ms\")
            .map_err(|_| AutomationError::Corrupt)?;
        let task_id: String = cursor
            .try_get(\"last_task_id\")
            .map_err(|_| AutomationError::Corrupt)?;
        let occurrence: i64 = cursor
            .try_get(\"last_occurrence\")
            .map_err(|_| AutomationError::Corrupt)?;
        if owner != expected_owner {
            return Err(AutomationError::AccessDenied);
        }
        if updated_at_ms < 0
            || occurrence <= 0
            || AutomationTaskId::parse(task_id).is_err()
        {
            return Err(AutomationError::Corrupt);
        }
    }
    Ok(())
}

fn occurrence_work_from_row(
    row: &sqlx::sqlite::SqliteRow,
    expected_owner: &AgentId,
) -> Result<AutomationOccurrenceWork, AutomationError> {
    let occurrence = occurrence_from_row(row, expected_owner.as_str())?;
    let thread_id: String = row
        .try_get(\"thread_id\")
        .map_err(|_| AutomationError::Corrupt)?;
    let prompt: String = row
        .try_get(\"prompt\")
        .map_err(|_| AutomationError::Corrupt)?;
    Ok(AutomationOccurrenceWork {
        admission: AutomationAdmission {
            agent_id: expected_owner.clone(),
            task_id: occurrence.task_id,
            occurrence: occurrence.occurrence,
            scheduled_for_ms: occurrence.scheduled_for_ms,
            thread_id,
            prompt,
            client_user_message_id: occurrence.client_user_message_id.clone(),
        },
        occurrence,
    })
}

fn occurrence_from_row(
"""
text = replace_once(text, old_verify, new_verify, "occurrence verification/helper")

old_tests = """    #[test]
    fn missed_run_math_is_bounded_and_deterministic() {
        assert_eq!(first_after(1100, 100, 1450).expect(\"first future\"), 1500);
        assert_eq!(latest_not_after(1100, 100, 1450).expect(\"coalesce\"), 1400);
    }
}
"""
new_tests = """    #[test]
    fn missed_run_math_is_bounded_and_deterministic() {
        assert_eq!(first_after(1100, 100, 1450).expect(\"first future\"), 1500);
        assert_eq!(latest_not_after(1100, 100, 1450).expect(\"coalesce\"), 1400);
    }

    #[tokio::test]
    async fn exact_pending_lookup_is_not_limited_by_the_discovery_page() {
        let temp = tempfile::tempdir().expect(\"owner root\");
        let owner = AgentId::parse(\"018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12\")
            .expect(\"owner agent id\");
        let store = AutomationStore::open_root(temp.path().join(\"automation\"), owner.clone())
            .await
            .expect(\"automation store\");
        let mut transaction = store.taskflow_pool().begin().await.expect(\"transaction\");
        let mut exact_task = None;
        for index in 1_u64..=1_025 {
            let task_id = AutomationTaskId::parse(format!(
                \"019153a4-3088-7000-a56a-{index:012x}\"
            ))
            .expect(\"task id\");
            if index == 1_025 {
                exact_task = Some(task_id);
            }
            let task = task_id.to_string();
            let client = format!(\"recovery-client-{index}\");
            let occurrence_id = deterministic_occurrence_id(owner.as_str(), task_id, 1, index);
            let run_id = format!(\"automation-run:{}\", digest_suffix(&occurrence_id));
            sqlx::query(
                \"INSERT INTO automation_tasks (
                     task_id, owner_agent_id, thread_id, prompt, schedule_kind, interval_ms,
                     state, next_run_at_ms, next_occurrence, created_at_ms, updated_at_ms
                 ) VALUES (?, ?, ?, ?, 'once', NULL, 'completed', NULL, 2, ?, ?)\",
            )
            .bind(&task)
            .bind(owner.as_str())
            .bind(format!(\"thread-{index}\"))
            .bind(format!(\"prompt-{index}\"))
            .bind(i64::try_from(index).expect(\"created time\"))
            .bind(i64::try_from(index).expect(\"updated time\"))
            .execute(&mut *transaction)
            .await
            .expect(\"task row\");
            sqlx::query(
                \"INSERT INTO automation_runs (
                     task_id, occurrence, scheduled_for_ms, client_user_message_id, state,
                     lease_generation, lease_token, lease_expires_at_ms,
                     queued_submission_id, submitted_at_ms, schedule_revision
                 ) VALUES (?, 1, ?, ?, 'submitted', NULL, NULL, NULL, ?, ?, 1)\",
            )
            .bind(&task)
            .bind(i64::try_from(index).expect(\"scheduled time\"))
            .bind(&client)
            .bind(format!(\"queue-{index}\"))
            .bind(i64::try_from(index).expect(\"submitted time\"))
            .execute(&mut *transaction)
            .await
            .expect(\"run row\");
            sqlx::query(
                \"INSERT INTO automation_occurrence_lifecycle (
                     task_id, occurrence, occurrence_id, owner_agent_id, schedule_revision,
                     scheduled_for_ms, client_user_message_id, state, overlap_policy,
                     claim_generation, claim_token, taskflow_run_id, queued_submission_id,
                     recovery_phase, created_at_ms, updated_at_ms
                 ) VALUES (?, 1, ?, ?, 1, ?, ?, 'admitted', 'allow', 1, ?, ?, ?,
                           'awaiting_turn', ?, ?)\",
            )
            .bind(&task)
            .bind(&occurrence_id)
            .bind(owner.as_str())
            .bind(i64::try_from(index).expect(\"scheduled time\"))
            .bind(&client)
            .bind(format!(\"claim-{index}\"))
            .bind(&run_id)
            .bind(format!(\"queue-{index}\"))
            .bind(i64::try_from(index).expect(\"created time\"))
            .bind(i64::try_from(index).expect(\"updated time\"))
            .execute(&mut *transaction)
            .await
            .expect(\"occurrence row\");
        }
        transaction.commit().await.expect(\"commit fixtures\");
        let exact_task = exact_task.expect(\"exact task\");
        let page = store
            .pending_occurrence_work(MAX_RECOVERY_SCAN)
            .await
            .expect(\"bounded discovery page\");
        assert_eq!(page.len(), MAX_RECOVERY_SCAN);
        assert!(
            page.iter()
                .all(|work| work.occurrence.task_id != exact_task),
            \"the fixture must place the exact identity beyond the first bounded page\"
        );
        let exact = store
            .pending_occurrence_work_exact(exact_task, 1)
            .await
            .expect(\"exact read\")
            .expect(\"pending occurrence beyond first page\");
        assert_eq!(exact.occurrence.task_id, exact_task);
        assert_eq!(exact.occurrence.occurrence, 1);
    }
}
"""
text = replace_once(text, old_tests, new_tests, "lifecycle recovery tests")
write(path, text)

# Product recovery uses fair discovery and exact known-identity lookup.
path = "codex-rs/hepta-agentd/src/automation_recovery.rs"
text = read(path)
text = replace_once(
    text,
    """    let Some(work) = store.pending_occurrence_work(1).await?.into_iter().next() else {
        return Ok(false);
    };
""",
    """    let Some(work) = store.next_pending_occurrence_work().await? else {
        return Ok(false);
    };
""",
    "fair recovery discovery",
)
text = replace_once(
    text,
    """    store
        .pending_occurrence_work(1024)
        .await?
        .into_iter()
        .find(|work| work.occurrence.task_id == task_id && work.occurrence.occurrence == occurrence)
        .ok_or_else(|| {
            AgentdError::Protocol(
                \"automation occurrence is not in the recovery frontier\".to_string(),
            )
        })
""",
    """    store
        .pending_occurrence_work_exact(task_id, occurrence)
        .await?
        .ok_or_else(|| {
            AgentdError::Protocol(\"automation occurrence is not pending recovery\".to_string())
        })
""",
    "exact recovery lookup",
)
write(path, text)

# The old migration regression now creates the actual v1 schema instead of
# destructively deleting current tables underneath current triggers.
path = "codex-rs/hepta-automation/tests/automation.rs"
text = read(path)
text = replace_once(
    text,
    "use pretty_assertions::assert_eq;\n",
    "use pretty_assertions::assert_eq;\nuse sqlx::migrate::Migrate;\n",
    "migration trait import",
)
text = replace_once(
    text,
    "const AGENT_IDS: [&str; 5] = [",
    "static AUTOMATION_MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!(\"./migrations\");\n\nconst AGENT_IDS: [&str; 5] = [",
    "test migrator",
)
function_start = """#[tokio::test]
async fn v1_store_migrates_atomically_to_dispatch_outcome_schema() {
"""
function_end = """
#[tokio::test]
async fn legacy_unknown_without_frozen_revision_requires_absence_proof_before_new_claim() {
"""
start_index = text.find(function_start)
end_index = text.find(function_end, start_index)
if start_index < 0 or end_index < 0:
    raise RuntimeError("v1 migration test boundaries missing")
old_function = text[start_index:end_index]
tail_marker = "    let migrated = AutomationStore::open(layout)"
tail_index = old_function.find(tail_marker)
if tail_index < 0:
    raise RuntimeError("v1 migration assertion tail missing")
tail = old_function[tail_index:]
new_function = """#[tokio::test]
async fn v1_store_migrates_atomically_to_dispatch_outcome_schema() {
    let fixture = FleetFixture::new(1);
    let layout = &fixture.layouts[0];
    std::fs::create_dir_all(layout.automation_root()).expect(\"automation root\");
    let database_path = layout.automation_root().join(\"automation_1.sqlite3\");
    let sqlite_home = AbsolutePathBuf::from_absolute_path(layout.automation_root())
        .expect(\"absolute sqlite home\");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&database_path)
        .await
        .expect(\"open historical v1 pool\");
    let mut connection = pool.acquire().await.expect(\"historical owner connection\");
    connection
        .ensure_migrations_table(\"_sqlx_migrations\")
        .await
        .expect(\"historical migration journal\");
    let migration = AUTOMATION_MIGRATOR
        .iter()
        .find(|migration| migration.version == 1)
        .expect(\"v1 migration\");
    connection
        .apply(\"_sqlx_migrations\", migration)
        .await
        .expect(\"apply real v1 schema\");

    let task = draft(
        \"019153a4-3088-7000-a56a-9b1964f7500e\",
        AutomationSchedule::Once,
        100,
    );
    sqlx::query(
        \"INSERT INTO automation_meta (singleton, schema_version, owner_agent_id)
         VALUES (1, 1, ?)\",
    )
    .bind(layout.agent_id().as_str())
    .execute(&mut *connection)
    .await
    .expect(\"historical owner metadata\");
    sqlx::query(
        \"INSERT INTO automation_tasks (
             task_id, owner_agent_id, thread_id, prompt, schedule_kind, interval_ms,
             state, next_run_at_ms, next_occurrence, created_at_ms, updated_at_ms
         ) VALUES (?, ?, ?, ?, 'once', NULL, 'enabled', ?, 1, ?, ?)\",
    )
    .bind(task.task_id.to_string())
    .bind(layout.agent_id().as_str())
    .bind(&task.thread_id)
    .bind(&task.prompt)
    .bind(i64::try_from(task.first_run_at_ms).expect(\"first run fits sqlite\"))
    .bind(i64::try_from(task.created_at_ms).expect(\"created time fits sqlite\"))
    .bind(i64::try_from(task.created_at_ms).expect(\"created time fits sqlite\"))
    .execute(&mut *connection)
    .await
    .expect(\"insert real v1 task\");
    drop(connection);
    pool.close().await;

""" + tail
text = text[:start_index] + new_function + text[end_index:]
write(path, text)

# Regression: two non-terminal occurrences are visited in bounded successive
# recovery selections even when the first remains non-terminal.
path = "codex-rs/hepta-automation/tests/durable_causal_chain.rs"
text = read(path)
if "durable_recovery_cursor_rotates_past_a_long_running_occurrence" in text:
    raise RuntimeError("fair recovery regression already exists")
text += """

#[tokio::test]
async fn durable_recovery_cursor_rotates_past_a_long_running_occurrence() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect(\"store\");
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(SuccessQueue),
        1,
        Duration::from_secs(30),
        Duration::from_secs(2),
    )
    .expect(\"scheduler\");
    let first = draft(
        \"019153a4-3088-7000-a56a-9b1964f75a01\",
        AutomationSchedule::Once,
        100,
    );
    let second = draft(
        \"019153a4-3088-7000-a56a-9b1964f75a02\",
        AutomationSchedule::Once,
        200,
    );
    store.create_task(&first).await.expect(\"first task\");
    store.create_task(&second).await.expect(\"second task\");
    assert!(matches!(
        scheduler.tick(100).await.expect(\"first tick\"),
        AutomationTick::Submitted { .. }
    ));
    assert!(matches!(
        scheduler.tick(200).await.expect(\"second tick\"),
        AutomationTick::Submitted { .. }
    ));

    let selected_first = store
        .next_pending_occurrence_work()
        .await
        .expect(\"first recovery selection\")
        .expect(\"first pending occurrence\");
    let selected_second = store
        .next_pending_occurrence_work()
        .await
        .expect(\"second recovery selection\")
        .expect(\"second pending occurrence\");
    assert_ne!(
        selected_first.occurrence.task_id,
        selected_second.occurrence.task_id,
        \"one long-running occurrence must not monopolize every recovery pass\"
    );
    assert_eq!(
        [
            selected_first.occurrence.task_id,
            selected_second.occurrence.task_id,
        ]
        .into_iter()
        .collect::<std::collections::BTreeSet<_>>(),
        [first.task_id, second.task_id]
            .into_iter()
            .collect::<std::collections::BTreeSet<_>>()
    );
}
"""
write(path, text)

# Reject an exhausted version space rather than accepting a same-version
# successor through saturating arithmetic.
path = "codex-rs/hepta-automation/src/neural_circuit.rs"
text = read(path)
text = replace_once(
    text,
    """    if successor.version != current.version.saturating_add(1) {
        return Err(invalid(\"circuit successor version is not monotone by one\"));
    }
""",
    """    let expected_version = current
        .version
        .checked_add(1)
        .ok_or_else(|| invalid(\"circuit version space is exhausted\"))?;
    if successor.version != expected_version {
        return Err(invalid(\"circuit successor version is not monotone by one\"));
    }
""",
    "Circuit version successor",
)
insert_marker = """    #[test]
    fn circuit_reuses_taskflow_cycle_and_terminal_rejection() {
"""
regression = """    #[test]
    fn exhausted_version_space_rejects_same_version_successor() {
        let current = NeuralCircuitCandidateV1::new(
            \"circuit-max-version\",
            u32::MAX,
            Some(digest(\"prior-version\")),
            \"observe\",
            vec![
                CircuitNodeV1::new(\"observe\", CircuitNodeRoleV1::Observe),
                CircuitNodeV1::new(\"success\", CircuitNodeRoleV1::ExitSuccess),
                CircuitNodeV1::new(\"failure\", CircuitNodeRoleV1::ExitFailure),
            ],
            vec![
                CircuitEdgeV1::new(\"observe\", \"success\"),
                CircuitEdgeV1::new(\"observe\", \"failure\"),
            ],
            Vec::new(),
            digest(\"route-max\"),
            digest(\"parameters-max\"),
            digest(\"resources-max\"),
        )
        .expect(\"current max-version circuit\");
        let successor = NeuralCircuitCandidateV1::new(
            \"circuit-max-version\",
            u32::MAX,
            Some(current.circuit_digest.clone()),
            \"observe\",
            current.nodes.clone(),
            current.edges.clone(),
            Vec::new(),
            digest(\"route-max-next\"),
            digest(\"parameters-max-next\"),
            digest(\"resources-max-next\"),
        )
        .expect(\"same-version candidate remains structurally valid\");
        assert!(matches!(
            validate_circuit_successor_v1(&current, &successor),
            Err(TaskFlowError::Invalid(message)) if message.contains(\"exhausted\")
        ));
    }

"""
text = replace_once(text, insert_marker, regression + insert_marker, "Circuit overflow regression")
write(path, text)

print("materialized automation.taskflow migration/fairness/exact-lookup/Circuit-boundary slice")
