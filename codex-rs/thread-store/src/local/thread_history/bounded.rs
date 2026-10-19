//! Opt-in recovery reads. Never fall back to rollout replay or unbounded hydration.
use codex_protocol::ThreadId;
use codex_protocol::protocol::ThreadHistoryMode;
use futures::TryStreamExt;
use sqlx::QueryBuilder;
use sqlx::Row;
use sqlx::Sqlite;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;

use super::super::LocalThreadStore;
use super::read::CursorScope;
use super::read::parse_cursor;
use super::read::stored_thread_item_row;
use super::read::stored_turn_row;
use super::segment_paging::finish_page;
use super::thread_history_error;
use crate::FullTurnPage;
use crate::ListTurnsParams;
use crate::SortDirection;
use crate::StoredTurn;
use crate::StoredTurnItemsView;
use crate::ThreadStoreError;
use crate::ThreadStoreResult;

const ROW_BYTES: usize = 256 * 1024;
const TOTAL_BYTES: usize = 4 * 1024 * 1024;
const TOTAL_ROWS: usize = 1024;
const HEADER_BYTES: u64 = 64 * 1024;

#[derive(Default)]
struct Budget {
    rows: usize,
    bytes: usize,
}

impl Budget {
    fn charge(&mut self, bytes: i64) -> ThreadStoreResult<()> {
        let bytes = usize::try_from(bytes).map_err(thread_history_error)?;
        if bytes > ROW_BYTES || self.rows >= TOTAL_ROWS || bytes > TOTAL_BYTES - self.bytes {
            return Err(ThreadStoreError::HistoryReadUnavailable {
                reason: "budgetExceeded",
            });
        }
        self.rows += 1;
        self.bytes += bytes;
        Ok(())
    }
}

pub(in crate::local) async fn list_full_turns_bounded(
    store: &LocalThreadStore,
    params: ListTurnsParams,
) -> ThreadStoreResult<FullTurnPage> {
    if params.page_size == 0
        || params.page_size > 100
        || params.cursor.as_ref().is_some_and(|c| c.len() > 1024)
    {
        return Err(ThreadStoreError::InvalidRequest {
            message: "bounded history requires 1..=100 turns and a cursor of at most 1024 bytes"
                .into(),
        });
    }
    let _writer_guard = store.live_writer_locks.lock(params.thread_id).await;
    let cursor = parse_cursor(
        params.cursor.as_deref(),
        params.thread_id,
        CursorScope::Turns,
    )?;
    let rollout_id = indexed_rollout(store, params.thread_id, params.include_archived).await?;
    let pool = store.thread_history_db().await?;
    let mut tx = pool.begin().await.map_err(thread_history_error)?;
    let mut budget = Budget::default();
    let mut query = guarded_select(
        "thread_turns",
        &[
            "turn_id",
            "status",
            "error_json",
            "first_user_item_id",
            "final_agent_item_id",
        ],
        "rollout_ordinal, started_at, completed_at, duration_ms",
    );
    query.push(" WHERE thread_id = ").push_bind(&rollout_id);
    if let Some(cursor) = cursor {
        let op = match (params.sort_direction, cursor.include_anchor) {
            (SortDirection::Asc, false) => " > ",
            (SortDirection::Asc, true) => " >= ",
            (SortDirection::Desc, false) => " < ",
            (SortDirection::Desc, true) => " <= ",
        };
        let ordinal = i64::try_from(cursor.rollout_ordinal).map_err(thread_history_error)?;
        query
            .push(" AND rollout_ordinal")
            .push(op)
            .push_bind(ordinal);
    }
    query
        .push(" ORDER BY rollout_ordinal ")
        .push(match params.sort_direction {
            SortDirection::Asc => "ASC",
            SortDirection::Desc => "DESC",
        });
    query
        .push(" LIMIT ")
        .push_bind((params.page_size + 1) as i64);
    let mut rows = Vec::new();
    {
        let mut stream = query.build().fetch(&mut *tx);
        while let Some(row) = stream.try_next().await.map_err(thread_history_error)? {
            budget.charge(row.try_get("row_bytes")?)?;
            rows.push(stored_turn_row(row)?);
        }
    }
    let page = finish_page(params.thread_id, CursorScope::Turns, rows, params.page_size)?;
    let mut turns = Vec::with_capacity(page.rows.len());
    for row in page.rows {
        let mut query = guarded_select(
            "thread_items",
            &["turn_id", "item_id", "item_json"],
            "rollout_ordinal, updated_at_ordinal, created_at_ms",
        );
        query
            .push(" WHERE thread_id = ")
            .push_bind(&rollout_id)
            .push(" AND turn_id = ")
            .push_bind(&row.turn_id)
            .push(" ORDER BY rollout_ordinal ASC LIMIT ")
            .push_bind((TOTAL_ROWS - budget.rows + 1) as i64);
        let mut items = Vec::new();
        {
            let mut stream = query.build().fetch(&mut *tx);
            while let Some(item) = stream.try_next().await.map_err(thread_history_error)? {
                budget.charge(item.try_get("row_bytes")?)?;
                items.push(stored_thread_item_row(item)?.item);
            }
        }
        turns.push((
            StoredTurn {
                turn_id: row.turn_id,
                items: Vec::new(),
                items_view: StoredTurnItemsView::NotLoaded,
                status: row.status,
                error: row.error,
                started_at: row.started_at,
                completed_at: row.completed_at,
                duration_ms: row.duration_ms,
            },
            items,
        ));
    }
    tx.commit().await.map_err(thread_history_error)?;
    Ok(FullTurnPage {
        turns,
        next_cursor: page.next_cursor,
        backwards_cursor: page.backwards_cursor,
    })
}

// Oversized rows remain visible as sentinels. SQLite never transfers their payloads to Rust.
fn guarded_select(table: &str, fields: &[&str], fixed: &str) -> QueryBuilder<Sqlite> {
    let size = fields
        .iter()
        .map(|field| format!("coalesce(octet_length({field}), 0)"))
        .collect::<Vec<_>>()
        .join(" + ");
    let mut query = QueryBuilder::new(format!("SELECT {fixed}, ({size}) AS row_bytes"));
    for field in fields {
        query.push(format!(
            ", CASE WHEN ({size}) <= {ROW_BYTES} THEN {field} ELSE NULL END AS {field}"
        ));
    }
    query.push(format!(" FROM {table}"));
    query
}

async fn indexed_rollout(
    store: &LocalThreadStore,
    thread_id: ThreadId,
    include_archived: bool,
) -> ThreadStoreResult<String> {
    let unavailable = || ThreadStoreError::HistoryReadUnavailable {
        reason: "unsupportedHistory",
    };
    let state = store.state_db().await.ok_or_else(unavailable)?;
    let path = state
        .find_paginated_rollout_path_bounded(thread_id, include_archived)
        .await
        .map_err(thread_history_error)?
        .ok_or_else(unavailable)?;
    if path.extension().is_none_or(|ext| ext != "jsonl") {
        return Err(unavailable());
    }
    if !tokio::fs::try_exists(&path)
        .await
        .map_err(thread_history_error)?
    {
        let compressed = path.with_extension("jsonl.zst");
        if tokio::fs::try_exists(&compressed)
            .await
            .map_err(thread_history_error)?
        {
            let compressed = super::super::helpers::scoped_rollout_path(
                store.config.codex_home.clone(),
                &compressed,
                "Codex home",
            )?;
            if tokio::fs::metadata(compressed)
                .await
                .map_err(thread_history_error)?
                .is_file()
            {
                return Err(unavailable());
            }
        }
    }
    let path = super::super::helpers::scoped_rollout_path(
        store.config.codex_home.clone(),
        &path,
        "Codex home",
    )?;
    let rollout_id = codex_rollout::rollout_id_from_path(&path).ok_or_else(unavailable)?;
    if !tokio::fs::metadata(&path)
        .await
        .map_err(thread_history_error)?
        .is_file()
    {
        return Err(unavailable());
    }
    let file = tokio::fs::File::open(path)
        .await
        .map_err(thread_history_error)?;
    let mut reader = tokio::io::BufReader::new(file.take(HEADER_BYTES + 1));
    let mut header = Vec::new();
    reader
        .read_until(b'\n', &mut header)
        .await
        .map_err(thread_history_error)?;
    if header.len() as u64 > HEADER_BYTES || header.last() != Some(&b'\n') {
        return Err(ThreadStoreError::HistoryReadUnavailable {
            reason: "budgetExceeded",
        });
    }
    let line: codex_rollout::RolloutLine =
        serde_json::from_slice(&header).map_err(thread_history_error)?;
    let codex_rollout::RolloutItem::SessionMeta(meta) = line.item else {
        return Err(ThreadStoreError::Internal {
            message: "indexed rollout has no leading session metadata".into(),
        });
    };
    if meta.meta.id != thread_id || meta.meta.history_mode != ThreadHistoryMode::Paginated {
        return Err(ThreadStoreError::Internal {
            message: "indexed rollout identity or history mode mismatch".into(),
        });
    }
    if meta.meta.history_base.is_some() {
        return Err(unavailable());
    }
    Ok(rollout_id.to_string())
}
