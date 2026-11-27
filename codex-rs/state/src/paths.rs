use std::path::Path;

pub(crate) async fn file_modified_time_utc(path: &Path) -> Option<codex_utils_time::Timestamp> {
    let modified = tokio::fs::metadata(path).await.ok()?.modified().ok()?;
    let updated_at: codex_utils_time::Timestamp = modified.into();
    Some(updated_at)
}
