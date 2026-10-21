//! Durable owner-local progress for bounded persisted turn observation.

use sqlx::Sqlite;
use sqlx::Transaction;

use crate::InboxDispatchRecord;
use crate::InboxDispatchState;
use crate::MatrixDurableError;
use crate::MatrixDurableStore;

impl MatrixDurableStore {
    /// Read observation progress for this exact, current admitted dispatch.
    /// The cursor is App Server pagination state, never admission authority.
    pub async fn turn_recovery_cursor(
        &self,
        dispatch: &InboxDispatchRecord,
    ) -> Result<Option<String>, MatrixDurableError> {
        let mut tx = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        self.require_turn_recovery_dispatch(&mut tx, dispatch)
            .await?;
        let cursor = recovery_cursor(&mut tx, dispatch).await?;
        tx.commit()
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        Ok(cursor)
    }

    /// Compare-and-set progress without changing the exact dispatch identity.
    /// `next = None` restarts observation after an in-progress or exhausted
    /// scan; terminal projection uses the same reset before durable replay.
    pub async fn advance_turn_recovery_cursor(
        &self,
        dispatch: &InboxDispatchRecord,
        expected: Option<&str>,
        next: Option<&str>,
    ) -> Result<(), MatrixDurableError> {
        for cursor in [expected, next].into_iter().flatten() {
            if cursor.is_empty() || cursor.len() > 4096 || cursor.chars().any(char::is_control) {
                return Err(MatrixDurableError::Invalid);
            }
        }
        let mut tx = self
            .sqlite_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| MatrixDurableError::Unavailable)?;
        self.require_turn_recovery_dispatch(&mut tx, dispatch)
            .await?;
        if recovery_cursor(&mut tx, dispatch).await?.as_deref() != expected {
            return Err(MatrixDurableError::Conflict);
        }
        match next {
            Some(cursor) => {
                sqlx::query(
                    "INSERT INTO matrix_turn_recovery (event_id, thread_id, turn_id, cursor)
                     VALUES (?, ?, ?, ?) ON CONFLICT(event_id) DO UPDATE SET cursor = excluded.cursor",
                )
                .bind(dispatch.event_id.as_str())
                .bind(dispatch.thread_id.as_deref())
                .bind(dispatch.turn_id.as_deref())
                .bind(cursor)
                .execute(&mut *tx)
                .await
                .map_err(|_| MatrixDurableError::Unavailable)?;
            }
            None => {
                sqlx::query("DELETE FROM matrix_turn_recovery WHERE event_id = ?")
                    .bind(dispatch.event_id.as_str())
                    .execute(&mut *tx)
                    .await
                    .map_err(|_| MatrixDurableError::Unavailable)?;
            }
        }
        tx.commit()
            .await
            .map_err(|_| MatrixDurableError::Unavailable)
    }

    async fn require_turn_recovery_dispatch(
        &self,
        tx: &mut Transaction<'_, Sqlite>,
        dispatch: &InboxDispatchRecord,
    ) -> Result<(), MatrixDurableError> {
        if dispatch.state != InboxDispatchState::Admitted
            || dispatch.thread_id.as_deref().is_none_or(str::is_empty)
            || dispatch.turn_id.as_deref().is_none_or(str::is_empty)
        {
            return Err(MatrixDurableError::Invalid);
        }
        let exact: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM matrix_actionable_inbox_dispatches_v2 d
             JOIN room_bindings b ON b.room_id = d.room_id
             WHERE d.event_id = ? AND d.state = 'admitted'
               AND d.thread_id = ? AND d.turn_id = ? AND d.client_user_message_id = ? AND d.project_id = ?
               AND d.room_id = ? AND d.binding_revision = ? AND d.generation = ?
               AND b.owner_agent_id = ? AND b.revision = d.binding_revision
               AND b.generation = d.generation",
        )
        .bind(dispatch.event_id.as_str())
        .bind(dispatch.thread_id.as_deref())
        .bind(dispatch.turn_id.as_deref())
        .bind(&dispatch.client_user_message_id)
        .bind(&dispatch.project_id)
        .bind(dispatch.room_id.as_str())
        .bind(i64::try_from(dispatch.binding_revision).map_err(|_| MatrixDurableError::Invalid)?)
        .bind(i64::try_from(dispatch.generation).map_err(|_| MatrixDurableError::Invalid)?)
        .bind(self.owner_agent_id().as_str())
        .fetch_one(&mut **tx)
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        if exact != 1 {
            return Err(MatrixDurableError::AccessDenied);
        }
        Ok(())
    }
}

async fn recovery_cursor(
    tx: &mut Transaction<'_, Sqlite>,
    dispatch: &InboxDispatchRecord,
) -> Result<Option<String>, MatrixDurableError> {
    let row: Option<(String, String, String)> = sqlx::query_as(
        "SELECT thread_id, turn_id, cursor FROM matrix_turn_recovery WHERE event_id = ?",
    )
    .bind(dispatch.event_id.as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(|_| MatrixDurableError::Unavailable)?;
    match row {
        Some((thread_id, turn_id, cursor)) => {
            if Some(thread_id.as_str()) != dispatch.thread_id.as_deref()
                || Some(turn_id.as_str()) != dispatch.turn_id.as_deref()
                || cursor.is_empty()
                || cursor.len() > 4096
                || cursor.chars().any(char::is_control)
            {
                return Err(MatrixDurableError::Corrupt);
            }
            Ok(Some(cursor))
        }
        None => Ok(None),
    }
}
