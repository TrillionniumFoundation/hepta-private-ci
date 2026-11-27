use crate::memory_extensions_root;
use std::path::Path;
use tracing::warn;

pub async fn prune_old_extension_resources(memory_root: &Path) {
    prune_old_extension_resources_with_now(memory_root, codex_utils_time::Timestamp::now()).await
}

async fn prune_old_extension_resources_with_now(
    memory_root: &Path,
    now: codex_utils_time::Timestamp,
) {
    let cutoff =
        now - codex_utils_time::SignedDuration::days(crate::extension_resources::RETENTION_DAYS);
    let extensions_root = memory_extensions_root(memory_root);
    let mut extensions = match tokio::fs::read_dir(&extensions_root).await {
        Ok(extensions) => extensions,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return,
        Err(err) => {
            warn!(
                "failed reading memory extensions root {}: {err}",
                extensions_root.display()
            );
            return;
        }
    };

    while let Ok(Some(extension_entry)) = extensions.next_entry().await {
        let extension_path = extension_entry.path();
        let Ok(file_type) = extension_entry.file_type().await else {
            continue;
        };
        if !file_type.is_dir()
            || !tokio::fs::try_exists(extension_path.join("instructions.md"))
                .await
                .unwrap_or(false)
        {
            continue;
        }

        let resources_path = extension_path.join("resources");
        let mut resources = match tokio::fs::read_dir(&resources_path).await {
            Ok(resources) => resources,
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => continue,
            Err(err) => {
                warn!(
                    "failed reading memory extension resources {}: {err}",
                    resources_path.display()
                );
                continue;
            }
        };

        while let Ok(Some(resource_entry)) = resources.next_entry().await {
            let resource_file_path = resource_entry.path();
            let Ok(file_type) = resource_entry.file_type().await else {
                continue;
            };
            if !file_type.is_file() {
                continue;
            }
            let Some(file_name) = resource_file_path
                .file_name()
                .and_then(|name| name.to_str())
            else {
                continue;
            };
            if !file_name.ends_with(".md") {
                continue;
            }
            let Some(resource_timestamp) = resource_timestamp(file_name) else {
                continue;
            };
            if resource_timestamp > cutoff {
                continue;
            }

            if let Err(err) = tokio::fs::remove_file(&resource_file_path).await
                && err.kind() != std::io::ErrorKind::NotFound
            {
                warn!(
                    "failed pruning old memory extension resource {}: {err}",
                    resource_file_path.display()
                );
            }
        }
    }
}

fn resource_timestamp(file_name: &str) -> Option<codex_utils_time::Timestamp> {
    let timestamp = file_name.get(..19)?;
    let naive =
        codex_utils_time::parse_utc(timestamp, crate::extension_resources::FILENAME_TS_FORMAT)
            .ok()?;
    Some(naive)
}

#[cfg(test)]
#[path = "prune_tests.rs"]
mod tests;
