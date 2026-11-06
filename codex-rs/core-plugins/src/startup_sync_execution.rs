//! Transport fallbacks and the file lock belong to one cancellable sync owner.

use super::CURATED_PLUGINS_BACKUP_ARCHIVE_API_URL;
use super::CURATED_PLUGINS_BACKUP_ARCHIVE_FALLBACK_VERSION;
use super::CURATED_PLUGINS_SHA_FILE;
use super::CURATED_PLUGINS_SYNC_LOCK_FILE;
use super::GITHUB_API_BASE_URL;
use super::StartupSyncHttpClient;
use super::activate_curated_repo;
use super::curated_plugins_repo_path;
use super::curated_plugins_sha_path;
use super::emit_curated_plugins_startup_sync_final_metric;
use super::emit_curated_plugins_startup_sync_metric;
use super::ensure_marketplace_manifest_exists;
use super::extract_zipball_to_dir;
use super::fetch_curated_repo_backup_archive_zip;
use super::fetch_curated_repo_remote_sha;
use super::fetch_curated_repo_zipball;
use super::has_local_curated_plugins_snapshot;
use super::prepare_curated_repo_parent_and_temp_dir;
use super::read_extracted_backup_archive_git_sha;
use super::read_sha_file;
use super::write_curated_plugins_sha;
use codex_git_utils::GitCommandCancellation;
use codex_http_client::HttpClientFactory;
use std::fs::File;
use std::path::Path;
#[cfg(not(target_os = "macos"))]
use std::path::PathBuf;
use std::time::Duration;
use tracing::warn;

pub fn sync_openai_plugins_repo(codex_home: &Path, http_client_factory: HttpClientFactory) -> Result<String, String> {
    sync_openai_plugins_repo_with_cancellation(codex_home, http_client_factory, &GitCommandCancellation::default())
}

pub(crate) fn sync_openai_plugins_repo_with_cancellation(
    codex_home: &Path,
    http_client_factory: HttpClientFactory,
    cancellation: &GitCommandCancellation,
) -> Result<String, String> {
    cancellation.check()?;
    #[cfg(target_os = "macos")]
    let git_binary = match which::which("git") {
        Ok(git_path) => super::macos_git_binary_from_path(git_path, super::git::apple_developer_tools_available(cancellation)?),
        Err(_) => None,
    };
    #[cfg(not(target_os = "macos"))]
    let git_binary = Some(PathBuf::from("git"));
    sync_with_transport(codex_home, git_binary.as_deref(), GITHUB_API_BASE_URL,
        CURATED_PLUGINS_BACKUP_ARCHIVE_API_URL, &http_client_factory, cancellation)
}

fn sync_with_transport(
    codex_home: &Path,
    git_binary: Option<&Path>,
    api_base_url: &str,
    backup_archive_api_url: &str,
    http_client_factory: &HttpClientFactory,
    cancellation: &GitCommandCancellation,
) -> Result<String, String> {
    let _file_guard = lock_curated_plugins_startup_sync(codex_home, cancellation)?;

    let git_sync_result = match git_binary {
        Some(git_binary) => super::git::sync_with_cancellation(codex_home, git_binary, cancellation),
        None => Err("git executable is unavailable".to_string()),
    };

    match git_sync_result {
        Ok(remote_sha) => {
            emit_curated_plugins_startup_sync_metric("git", "success");
            emit_curated_plugins_startup_sync_final_metric("git", "success");
            Ok(remote_sha)
        }
        Err(err) => {
            cancellation.check()?;
            emit_curated_plugins_startup_sync_metric("git", "failure");
            warn!(
                error = %err,
                "git sync failed for curated plugin sync; falling back to GitHub HTTP"
            );
            match sync_via_http(codex_home, api_base_url, http_client_factory, cancellation) {
                Ok(remote_sha) => {
                    emit_curated_plugins_startup_sync_metric("http", "success");
                    emit_curated_plugins_startup_sync_final_metric("http", "success");
                    Ok(remote_sha)
                }
                Err(http_err) => {
                    cancellation.check()?;
                    emit_curated_plugins_startup_sync_metric("http", "failure");
                    if has_local_curated_plugins_snapshot(codex_home) {
                        emit_curated_plugins_startup_sync_final_metric("http", "failure");
                        warn!(
                            error = %http_err,
                            "GitHub HTTP sync failed for curated plugin sync; skipping export archive fallback because a local curated plugins snapshot already exists"
                        );
                        Err(format!(
                            "git sync failed for curated plugin sync: {err}; GitHub HTTP sync failed for curated plugin sync: {http_err}; export archive fallback skipped because a local curated plugins snapshot already exists"
                        ))
                    } else {
                        // The export archive is a lagging backup path. Only use it to bootstrap a
                        // missing local curated snapshot, never to refresh an existing one.
                        warn!(
                            error = %http_err,
                            backup_archive_api_url,
                            "GitHub HTTP sync failed for curated plugin sync; falling back to export archive"
                        );
                        let result = sync_openai_plugins_repo_via_backup_archive(
                            codex_home,
                            backup_archive_api_url,
                            http_client_factory,
                            cancellation,
                        );
                        let status = if result.is_ok() { "success" } else { "failure" };
                        emit_curated_plugins_startup_sync_metric("export_archive", status);
                        emit_curated_plugins_startup_sync_final_metric("export_archive", status);
                        result.map_err(|export_err| {
                            format!(
                                "git sync failed for curated plugin sync: {err}; GitHub HTTP sync failed for curated plugin sync: {http_err}; export archive sync failed for curated plugin sync: {export_err}"
                            )
                        })
                    }
                }
            }
        }
    }
}

fn lock_curated_plugins_startup_sync(codex_home: &Path, cancellation: &GitCommandCancellation) -> Result<File, String> {
    cancellation.check()?;
    let lock_path = codex_home.join(CURATED_PLUGINS_SYNC_LOCK_FILE);
    std::fs::create_dir_all(codex_home.join(".tmp"))
        .map_err(|err| format!("failed to create curated plugins sync directory: {err}"))?;
    let lock_file = File::options()
        .write(true)
        .create(true)
        .truncate(false)
        .open(&lock_path)
        .map_err(|err| format!("failed to open curated plugins sync lock: {err}"))?;
    loop {
        cancellation.check()?;
        match lock_file.try_lock() {
            Ok(()) => break,
            Err(std::fs::TryLockError::WouldBlock) => std::thread::sleep(Duration::from_millis(100)),
            Err(std::fs::TryLockError::Error(err)) => return Err(format!("failed to lock curated plugins sync: {err}")),
        }
    }
    cancellation.check()?;
    Ok(lock_file)
}

fn sync_via_http(
    codex_home: &Path,
    api_base_url: &str,
    http_client_factory: &HttpClientFactory,
    cancellation: &GitCommandCancellation,
) -> Result<String, String> {
    cancellation.check()?;
    let repo_path = curated_plugins_repo_path(codex_home);
    let sha_path = codex_home.join(CURATED_PLUGINS_SHA_FILE);
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|err| format!("failed to create curated plugins sync runtime: {err}"))?;
    let http_clients = StartupSyncHttpClient::new(http_client_factory);
    let remote_sha =
        runtime.block_on(cancellation.run(fetch_curated_repo_remote_sha(&http_clients, api_base_url)))?;
    let local_sha = read_sha_file(&sha_path);

    if local_sha.as_deref() == Some(remote_sha.as_str()) && repo_path.is_dir() {
        return Ok(remote_sha);
    }

    let staged_repo_dir = prepare_curated_repo_parent_and_temp_dir(&repo_path)?;
    let zipball_bytes = runtime.block_on(cancellation.run(fetch_curated_repo_zipball(
        &http_clients,
        api_base_url,
        &remote_sha,
    )))?;
    cancellation.check()?;
    extract_zipball_to_dir(&zipball_bytes, staged_repo_dir.path())?;
    ensure_marketplace_manifest_exists(staged_repo_dir.path())?;
    cancellation.check()?;
    activate_curated_repo(&repo_path, staged_repo_dir)?;
    write_curated_plugins_sha(&sha_path, &remote_sha)?;
    Ok(remote_sha)
}

fn sync_openai_plugins_repo_via_backup_archive(
    codex_home: &Path,
    backup_archive_api_url: &str,
    http_client_factory: &HttpClientFactory,
    cancellation: &GitCommandCancellation,
) -> Result<String, String> {
    cancellation.check()?;
    let repo_path = curated_plugins_repo_path(codex_home);
    let sha_path = curated_plugins_sha_path(codex_home);
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|err| format!("failed to create curated plugins sync runtime: {err}"))?;
    let staged_repo_dir = prepare_curated_repo_parent_and_temp_dir(&repo_path)?;
    let http_clients = StartupSyncHttpClient::new(http_client_factory);
    let zipball_bytes = runtime.block_on(cancellation.run(fetch_curated_repo_backup_archive_zip(
        &http_clients,
        backup_archive_api_url,
    )))?;
    cancellation.check()?;
    extract_zipball_to_dir(&zipball_bytes, staged_repo_dir.path())?;
    ensure_marketplace_manifest_exists(staged_repo_dir.path())?;
    let export_version = read_extracted_backup_archive_git_sha(staged_repo_dir.path())?
        .unwrap_or_else(|| CURATED_PLUGINS_BACKUP_ARCHIVE_FALLBACK_VERSION.to_string());
    cancellation.check()?;
    activate_curated_repo(&repo_path, staged_repo_dir)?;
    write_curated_plugins_sha(&sha_path, &export_version)?;
    Ok(export_version)
}

#[cfg(test)]
pub(super) fn sync_openai_plugins_repo_with_transport_overrides(
    codex_home: &Path,
    git_binary: Option<&Path>,
    api_base_url: &str,
    backup_archive_api_url: &str,
    http_client_factory: &HttpClientFactory,
) -> Result<String, String> {
    sync_with_transport(codex_home, git_binary, api_base_url, backup_archive_api_url,
        http_client_factory, &GitCommandCancellation::default())
}

#[cfg(test)]
pub(super) fn sync_openai_plugins_repo_via_http(
    codex_home: &Path,
    api_base_url: &str,
    http_client_factory: &HttpClientFactory,
) -> Result<String, String> {
    sync_via_http(codex_home, api_base_url, http_client_factory, &GitCommandCancellation::default())
}

#[cfg(test)]
#[path = "startup_sync_execution_tests.rs"]
mod tests;
