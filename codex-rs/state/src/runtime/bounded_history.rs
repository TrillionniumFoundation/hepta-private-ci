use std::path::PathBuf;

use codex_protocol::ThreadId;

use super::StateRuntime;

impl StateRuntime {
    /// Returns only the selected path of a paginated thread, capped before SQLite transfers it.
    /// Other metadata (including potentially large previews) is never loaded by recovery reads.
    pub async fn find_paginated_rollout_path_bounded(
        &self,
        id: ThreadId,
        include_archived: bool,
    ) -> anyhow::Result<Option<PathBuf>> {
        let path: Option<(Option<String>,)> = sqlx::query_as(
            "SELECT CASE WHEN octet_length(rollout_path) <= 4096 THEN rollout_path ELSE NULL END
             FROM threads WHERE id = ? AND history_mode = 'paginated'
             AND (? OR archived_at IS NULL)",
        )
        .bind(id.to_string())
        .bind(include_archived)
        .fetch_optional(self.pool.as_ref())
        .await?;
        Ok(path.and_then(|(path,)| path).map(PathBuf::from))
    }
}
