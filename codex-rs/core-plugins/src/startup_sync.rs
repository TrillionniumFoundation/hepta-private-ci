use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Output;
use std::time::Duration;

use self::http_client::StartupSyncHttpClient;
use self::http_client::StartupSyncRequestBuilder;
use codex_login::default_client::default_headers;
use codex_otel::CURATED_PLUGINS_STARTUP_SYNC_FINAL_METRIC;
use codex_otel::CURATED_PLUGINS_STARTUP_SYNC_METRIC;
use http::Method;
use serde::Deserialize;
use tempfile::TempDir;
use tracing::warn;
use zip::ZipArchive;

mod http_client;

#[path = "startup_sync_execution.rs"]
mod execution;
#[path = "startup_sync_git.rs"]
mod git;
pub use execution::sync_openai_plugins_repo;
pub(crate) use execution::sync_openai_plugins_repo_with_cancellation;
#[cfg(test)]
use execution::sync_openai_plugins_repo_via_http;
#[cfg(test)]
use execution::sync_openai_plugins_repo_with_transport_overrides;
#[cfg(test)]
use git::sync_openai_plugins_repo_via_git;

const GITHUB_API_BASE_URL: &str = "https://api.github.com";
const GITHUB_API_ACCEPT_HEADER: &str = "application/vnd.github+json";
const GITHUB_API_VERSION_HEADER: &str = "2022-11-28";
const CURATED_PLUGINS_BACKUP_ARCHIVE_API_URL: &str =
    "https://chatgpt.com/backend-api/plugins/export/curated";
const OPENAI_PLUGINS_OWNER: &str = "openai";
const OPENAI_PLUGINS_REPO: &str = "plugins";
const OPENAI_PLUGINS_GIT_URL: &str = "https://github.com/openai/plugins.git";
const CURATED_PLUGINS_FETCH_REF: &str = "refs/codex/curated-sync";
const CURATED_PLUGINS_RELATIVE_DIR: &str = ".tmp/plugins";
const CURATED_PLUGINS_SHA_FILE: &str = ".tmp/plugins.sha";
const CURATED_PLUGINS_SYNC_LOCK_FILE: &str = ".tmp/plugins.sync.lock";
const CURATED_PLUGINS_BACKUP_ARCHIVE_FALLBACK_VERSION: &str = "export-backup";
const CURATED_PLUGINS_GIT_TIMEOUT: Duration = Duration::from_secs(30);
const CURATED_PLUGINS_HTTP_TIMEOUT: Duration = Duration::from_secs(30);
const CURATED_PLUGINS_BACKUP_ARCHIVE_TIMEOUT: Duration = Duration::from_secs(30);
// Keep this comfortably above a normal sync attempt so we do not race another Codex process.
const CURATED_PLUGINS_STALE_TEMP_DIR_MAX_AGE: Duration = Duration::from_secs(10 * 60);
#[derive(Debug, Deserialize)]
struct GitHubRepositorySummary {
    default_branch: String,
}

#[derive(Debug, Deserialize)]
struct GitHubGitRefSummary {
    object: GitHubGitRefObject,
}

#[derive(Debug, Deserialize)]
struct GitHubGitRefObject {
    sha: String,
}

#[derive(Debug, Deserialize)]
struct CuratedPluginsBackupArchiveResponse {
    download_url: String,
}

pub fn curated_plugins_repo_path(codex_home: &Path) -> PathBuf {
    codex_home.join(CURATED_PLUGINS_RELATIVE_DIR)
}

pub fn curated_plugins_api_marketplace_path(codex_home: &Path) -> PathBuf {
    curated_plugins_repo_path(codex_home).join(".agents/plugins/api_marketplace.json")
}

pub fn read_curated_plugins_sha(codex_home: &Path) -> Option<String> {
    read_sha_file(curated_plugins_sha_path(codex_home).as_path())
}

fn curated_plugins_sha_path(codex_home: &Path) -> PathBuf {
    codex_home.join(CURATED_PLUGINS_SHA_FILE)
}

pub fn has_local_curated_plugins_snapshot(codex_home: &Path) -> bool {
    curated_plugins_repo_path(codex_home)
        .join(".agents/plugins/marketplace.json")
        .is_file()
        && codex_home.join(CURATED_PLUGINS_SHA_FILE).is_file()
}

fn prepare_curated_repo_parent_and_temp_dir(repo_path: &Path) -> Result<TempDir, String> {
    let Some(parent) = repo_path.parent() else {
        return Err(format!(
            "failed to determine curated plugins parent directory for {}",
            repo_path.display()
        ));
    };
    std::fs::create_dir_all(parent).map_err(|err| {
        format!(
            "failed to create curated plugins parent directory {}: {err}",
            parent.display()
        )
    })?;
    remove_stale_curated_repo_temp_dirs(parent, CURATED_PLUGINS_STALE_TEMP_DIR_MAX_AGE);

    let clone_dir = tempfile::Builder::new()
        .prefix("plugins-clone-")
        .tempdir_in(parent)
        .map_err(|err| {
            format!(
                "failed to create temporary curated plugins directory in {}: {err}",
                parent.display()
            )
        })?;
    Ok(clone_dir)
}

fn remove_stale_curated_repo_temp_dirs(parent: &Path, max_age: Duration) {
    let entries = match std::fs::read_dir(parent) {
        Ok(entries) => entries,
        Err(err) => {
            warn!(
                error = %err,
                parent = %parent.display(),
                "failed to list curated plugins temp directory parent for stale cleanup"
            );
            return;
        }
    };

    for entry in entries.flatten() {
        let file_type = match entry.file_type() {
            Ok(file_type) => file_type,
            Err(err) => {
                warn!(
                    error = %err,
                    path = %entry.path().display(),
                    "failed to inspect curated plugins temp directory entry"
                );
                continue;
            }
        };
        if !file_type.is_dir() {
            continue;
        }

        let path = entry.path();
        let is_plugins_clone_dir = path
            .file_name()
            .and_then(|name| name.to_str())
            .is_some_and(|name| name.starts_with("plugins-clone-"));
        if !is_plugins_clone_dir {
            continue;
        }

        let metadata = match entry.metadata() {
            Ok(metadata) => metadata,
            Err(err) => {
                warn!(
                    error = %err,
                    path = %path.display(),
                    "failed to read curated plugins temp directory metadata"
                );
                continue;
            }
        };
        let modified = match metadata.modified() {
            Ok(modified) => modified,
            Err(err) => {
                warn!(
                    error = %err,
                    path = %path.display(),
                    "failed to read curated plugins temp directory modification time"
                );
                continue;
            }
        };
        let age = match modified.elapsed() {
            Ok(age) => age,
            Err(err) => {
                warn!(
                    error = %err,
                    path = %path.display(),
                    "failed to compute curated plugins temp directory age"
                );
                continue;
            }
        };
        if age < max_age {
            continue;
        }

        if let Err(err) = std::fs::remove_dir_all(&path) {
            warn!(
                error = %err,
                path = %path.display(),
                "failed to remove stale curated plugins temp directory"
            );
        }
    }
}

fn emit_curated_plugins_startup_sync_metric(transport: &'static str, status: &'static str) {
    emit_curated_plugins_startup_sync_counter(
        CURATED_PLUGINS_STARTUP_SYNC_METRIC,
        transport,
        status,
    );
}

fn emit_curated_plugins_startup_sync_final_metric(transport: &'static str, status: &'static str) {
    emit_curated_plugins_startup_sync_counter(
        CURATED_PLUGINS_STARTUP_SYNC_FINAL_METRIC,
        transport,
        status,
    );
}

fn emit_curated_plugins_startup_sync_counter(
    metric_name: &str,
    transport: &'static str,
    status: &'static str,
) {
    let Some(metrics) = codex_otel::global() else {
        return;
    };
    let tags = [("transport", transport), ("status", status)];
    let _ = metrics.counter(metric_name, /*inc*/ 1, &tags);
}

fn ensure_marketplace_manifest_exists(repo_path: &Path) -> Result<(), String> {
    if repo_path.join(".agents/plugins/marketplace.json").is_file() {
        return Ok(());
    }
    Err(format!(
        "curated plugins archive missing marketplace manifest at {}",
        repo_path.join(".agents/plugins/marketplace.json").display()
    ))
}

fn activate_curated_repo(repo_path: &Path, staged_repo_dir: TempDir) -> Result<(), String> {
    let staged_repo_path = staged_repo_dir.path();
    if repo_path.exists() {
        let parent = repo_path.parent().ok_or_else(|| {
            format!(
                "failed to determine curated plugins parent directory for {}",
                repo_path.display()
            )
        })?;
        let backup_dir = tempfile::Builder::new()
            .prefix("plugins-backup-")
            .tempdir_in(parent)
            .map_err(|err| {
                format!(
                    "failed to create curated plugins backup directory in {}: {err}",
                    parent.display()
                )
            })?;
        let backup_repo_path = backup_dir.path().join("repo");

        std::fs::rename(repo_path, &backup_repo_path).map_err(|err| {
            format!(
                "failed to move previous curated plugins repo out of the way at {}: {err}",
                repo_path.display()
            )
        })?;

        if let Err(err) = std::fs::rename(staged_repo_path, repo_path) {
            let rollback_result = std::fs::rename(&backup_repo_path, repo_path);
            return match rollback_result {
                Ok(()) => Err(format!(
                    "failed to activate new curated plugins repo at {}: {err}",
                    repo_path.display()
                )),
                Err(rollback_err) => {
                    let backup_path = backup_dir.keep().join("repo");
                    Err(format!(
                        "failed to activate new curated plugins repo at {}: {err}; failed to restore previous repo (left at {}): {rollback_err}",
                        repo_path.display(),
                        backup_path.display()
                    ))
                }
            };
        }
    } else {
        std::fs::rename(staged_repo_path, repo_path).map_err(|err| {
            format!(
                "failed to activate curated plugins repo at {}: {err}",
                repo_path.display()
            )
        })?;
    }

    Ok(())
}

fn write_curated_plugins_sha(sha_path: &Path, remote_sha: &str) -> Result<(), String> {
    if let Some(parent) = sha_path.parent() {
        std::fs::create_dir_all(parent).map_err(|err| {
            format!(
                "failed to create curated plugins sha directory {}: {err}",
                parent.display()
            )
        })?;
    }
    std::fs::write(sha_path, format!("{remote_sha}\n")).map_err(|err| {
        format!(
            "failed to write curated plugins sha file {}: {err}",
            sha_path.display()
        )
    })
}

fn git_command(git_binary: &Path) -> Command {
    crate::PluginGitMode::Automatic.command(git_binary)
}

#[cfg(any(target_os = "macos", test))]
fn macos_git_binary_from_path(
    git_path: PathBuf,
    apple_developer_tools_available: bool,
) -> Option<PathBuf> {
    if git_path == Path::new("/usr/bin/git") && !apple_developer_tools_available {
        None
    } else {
        Some(git_path)
    }
}

fn ensure_git_success(output: &Output, context: &str) -> Result<(), String> {
    if output.status.success() {
        return Ok(());
    }
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    if stderr.is_empty() {
        Err(format!("{context} failed with status {}", output.status))
    } else {
        Err(format!(
            "{context} failed with status {}: {stderr}",
            output.status
        ))
    }
}

async fn fetch_curated_repo_remote_sha(
    http_clients: &StartupSyncHttpClient,
    api_base_url: &str,
) -> Result<String, String> {
    let api_base_url = api_base_url.trim_end_matches('/');
    let repo_url = format!("{api_base_url}/repos/{OPENAI_PLUGINS_OWNER}/{OPENAI_PLUGINS_REPO}");
    let repo_body =
        fetch_github_text(http_clients, &repo_url, "get curated plugins repository").await?;
    let repo_summary: GitHubRepositorySummary =
        serde_json::from_str(&repo_body).map_err(|err| {
            format!("failed to parse curated plugins repository response from {repo_url}: {err}")
        })?;
    if repo_summary.default_branch.is_empty() {
        return Err(format!(
            "curated plugins repository response from {repo_url} did not include a default branch"
        ));
    }

    let git_ref_url = format!("{repo_url}/git/ref/heads/{}", repo_summary.default_branch);
    let git_ref_body =
        fetch_github_text(http_clients, &git_ref_url, "get curated plugins HEAD ref").await?;
    let git_ref: GitHubGitRefSummary = serde_json::from_str(&git_ref_body).map_err(|err| {
        format!("failed to parse curated plugins ref response from {git_ref_url}: {err}")
    })?;
    if git_ref.object.sha.is_empty() {
        return Err(format!(
            "curated plugins ref response from {git_ref_url} did not include a HEAD sha"
        ));
    }

    Ok(git_ref.object.sha)
}

async fn fetch_curated_repo_zipball(
    http_clients: &StartupSyncHttpClient,
    api_base_url: &str,
    remote_sha: &str,
) -> Result<Vec<u8>, String> {
    let api_base_url = api_base_url.trim_end_matches('/');
    let repo_url = format!("{api_base_url}/repos/{OPENAI_PLUGINS_OWNER}/{OPENAI_PLUGINS_REPO}");
    let zipball_url = format!("{repo_url}/zipball/{remote_sha}");
    fetch_github_bytes(
        http_clients,
        &zipball_url,
        "download curated plugins archive",
    )
    .await
}

async fn fetch_curated_repo_backup_archive_zip(
    http_clients: &StartupSyncHttpClient,
    backup_archive_api_url: &str,
) -> Result<Vec<u8>, String> {
    let export_body = fetch_public_text(
        http_clients,
        backup_archive_api_url,
        "get curated plugins export archive metadata",
    )
    .await?;
    let export_response: CuratedPluginsBackupArchiveResponse = serde_json::from_str(&export_body)
        .map_err(|err| {
            format!(
                "failed to parse curated plugins backup archive response from {backup_archive_api_url}: {err}"
            )
        })?;
    if export_response.download_url.is_empty() {
        return Err(format!(
            "curated plugins backup archive response from {backup_archive_api_url} did not include a download URL"
        ));
    }

    fetch_public_bytes(
        http_clients,
        &export_response.download_url,
        "download curated plugins export archive",
    )
    .await
}

fn read_extracted_backup_archive_git_sha(repo_path: &Path) -> Result<Option<String>, String> {
    let git_dir = repo_path.join(".git");
    if !git_dir.is_dir() {
        return Ok(None);
    }

    let head_path = git_dir.join("HEAD");
    let head = std::fs::read_to_string(&head_path).map_err(|err| {
        format!(
            "failed to read curated plugins backup archive git HEAD {}: {err}",
            head_path.display()
        )
    })?;
    let head = head.trim();
    if head.is_empty() {
        return Err(format!(
            "curated plugins backup archive git HEAD is empty at {}",
            head_path.display()
        ));
    }

    if let Some(reference) = head.strip_prefix("ref: ") {
        let reference = validate_backup_archive_git_ref(reference.trim())?;
        return read_git_ref_sha(&git_dir, reference).map(Some);
    }

    Ok(Some(head.to_string()))
}

fn validate_backup_archive_git_ref(reference: &str) -> Result<&str, String> {
    if !reference.starts_with("refs/") {
        return Err(format!(
            "curated plugins backup archive git ref must stay under refs/: {reference}"
        ));
    }

    let path = Path::new(reference);
    if path.is_absolute() {
        return Err(format!(
            "curated plugins backup archive git ref must be relative: {reference}"
        ));
    }

    for component in path.components() {
        match component {
            std::path::Component::Normal(_) => {}
            _ => {
                return Err(format!(
                    "curated plugins backup archive git ref contains invalid path components: {reference}"
                ));
            }
        }
    }

    Ok(reference)
}

fn read_git_ref_sha(git_dir: &Path, reference: &str) -> Result<String, String> {
    let ref_path = git_dir.join(reference);
    if let Ok(sha) = std::fs::read_to_string(&ref_path) {
        let sha = sha.trim();
        if sha.is_empty() {
            return Err(format!(
                "curated plugins backup archive git ref {reference} is empty at {}",
                ref_path.display()
            ));
        }
        return Ok(sha.to_string());
    }

    let packed_refs_path = git_dir.join("packed-refs");
    if let Ok(packed_refs) = std::fs::read_to_string(&packed_refs_path)
        && let Some(sha) = packed_refs.lines().find_map(|line| {
            let trimmed = line.trim();
            if trimmed.is_empty() || trimmed.starts_with('#') || trimmed.starts_with('^') {
                return None;
            }
            let (sha, candidate_ref) = trimmed.split_once(' ')?;
            (candidate_ref == reference).then_some(sha.to_string())
        })
    {
        return Ok(sha);
    }

    Err(format!(
        "failed to resolve curated plugins backup archive git ref {reference} from {}",
        git_dir.display()
    ))
}

async fn fetch_github_text(
    http_clients: &StartupSyncHttpClient,
    url: &str,
    context: &str,
) -> Result<String, String> {
    let response = github_request(http_clients, url)
        .send()
        .await
        .map_err(|err| format!("failed to {context} from {url}: {err}"))?;
    let status = response.status();
    let body = response.text().await.unwrap_or_default();
    if !status.is_success() {
        return Err(format!(
            "{context} from {url} failed with status {status}: {body}"
        ));
    }
    Ok(body)
}

async fn fetch_github_bytes(
    http_clients: &StartupSyncHttpClient,
    url: &str,
    context: &str,
) -> Result<Vec<u8>, String> {
    let response = github_request(http_clients, url)
        .send()
        .await
        .map_err(|err| format!("failed to {context} from {url}: {err}"))?;
    let status = response.status();
    let body = response
        .bytes()
        .await
        .map_err(|err| format!("failed to read {context} response from {url}: {err}"))?;
    if !status.is_success() {
        let body_text = String::from_utf8_lossy(&body);
        return Err(format!(
            "{context} from {url} failed with status {status}: {body_text}"
        ));
    }
    Ok(body.to_vec())
}

async fn fetch_public_text(
    http_clients: &StartupSyncHttpClient,
    url: &str,
    context: &str,
) -> Result<String, String> {
    let response = startup_sync_request(http_clients, url)
        .timeout(CURATED_PLUGINS_BACKUP_ARCHIVE_TIMEOUT)
        .send()
        .await
        .map_err(|err| format!("failed to {context} from {url}: {err}"))?;
    let status = response.status();
    let body = response.text().await.unwrap_or_default();
    if !status.is_success() {
        return Err(format!(
            "{context} from {url} failed with status {status}: {body}"
        ));
    }
    Ok(body)
}

async fn fetch_public_bytes(
    http_clients: &StartupSyncHttpClient,
    url: &str,
    context: &str,
) -> Result<Vec<u8>, String> {
    let response = startup_sync_request(http_clients, url)
        .timeout(CURATED_PLUGINS_BACKUP_ARCHIVE_TIMEOUT)
        .send()
        .await
        .map_err(|err| format!("failed to {context} from {url}: {err}"))?;
    let status = response.status();
    let body = response
        .bytes()
        .await
        .map_err(|err| format!("failed to read {context} response from {url}: {err}"))?;
    if !status.is_success() {
        let body_text = String::from_utf8_lossy(&body);
        return Err(format!(
            "{context} from {url} failed with status {status}: {body_text}"
        ));
    }
    Ok(body.to_vec())
}

fn github_request(http_clients: &StartupSyncHttpClient, url: &str) -> StartupSyncRequestBuilder {
    startup_sync_request(http_clients, url)
        .timeout(CURATED_PLUGINS_HTTP_TIMEOUT)
        .header("accept", GITHUB_API_ACCEPT_HEADER)
        .header("x-github-api-version", GITHUB_API_VERSION_HEADER)
}

fn startup_sync_request(
    http_clients: &StartupSyncHttpClient,
    url: &str,
) -> StartupSyncRequestBuilder {
    http_clients
        .request(Method::GET, url)
        .headers(default_headers())
}

fn read_sha_file(sha_path: &Path) -> Option<String> {
    std::fs::read_to_string(sha_path)
        .ok()
        .map(|sha| sha.trim().to_string())
        .filter(|sha| !sha.is_empty())
}

fn extract_zipball_to_dir(bytes: &[u8], destination: &Path) -> Result<(), String> {
    std::fs::create_dir_all(destination).map_err(|err| {
        format!(
            "failed to create curated plugins extraction directory {}: {err}",
            destination.display()
        )
    })?;

    let cursor = std::io::Cursor::new(bytes);
    let mut archive = ZipArchive::new(cursor)
        .map_err(|err| format!("failed to open curated plugins zip archive: {err}"))?;

    for index in 0..archive.len() {
        let mut entry = archive
            .by_index(index)
            .map_err(|err| format!("failed to read curated plugins zip entry: {err}"))?;
        let Some(relative_path) = entry.enclosed_name() else {
            return Err(format!(
                "curated plugins zip entry `{}` escapes extraction root",
                entry
                    .name()
                    .map(std::borrow::Cow::into_owned)
                    .unwrap_or_else(|_| "<invalid>".to_string())
            ));
        };
        if entry.is_symlink() {
            return Err(format!(
                "curated plugins zip entry `{}` is a symlink",
                entry
                    .name()
                    .map(std::borrow::Cow::into_owned)
                    .unwrap_or_else(|_| "<invalid>".to_string())
            ));
        }

        let mut components = relative_path.components();
        let Some(std::path::Component::Normal(_)) = components.next() else {
            continue;
        };

        let output_relative = components.fold(PathBuf::new(), |mut path, component| {
            if let std::path::Component::Normal(segment) = component {
                path.push(segment);
            }
            path
        });
        if output_relative.as_os_str().is_empty() {
            continue;
        }

        let output_path = destination.join(&output_relative);
        if entry.is_dir() {
            std::fs::create_dir_all(&output_path).map_err(|err| {
                format!(
                    "failed to create curated plugins directory {}: {err}",
                    output_path.display()
                )
            })?;
            continue;
        }

        if let Some(parent) = output_path.parent() {
            std::fs::create_dir_all(parent).map_err(|err| {
                format!(
                    "failed to create curated plugins directory {}: {err}",
                    parent.display()
                )
            })?;
        }
        let mut output = std::fs::File::create(&output_path).map_err(|err| {
            format!(
                "failed to create curated plugins file {}: {err}",
                output_path.display()
            )
        })?;
        std::io::copy(&mut entry, &mut output).map_err(|err| {
            format!(
                "failed to write curated plugins file {}: {err}",
                output_path.display()
            )
        })?;
        apply_zip_permissions(&entry, &output_path)?;
    }

    Ok(())
}

#[cfg(unix)]
fn apply_zip_permissions<R: std::io::Read + ?Sized>(
    entry: &zip::read::ZipFile<'_, R>,
    output_path: &Path,
) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;

    let Some(mode) = entry.unix_mode() else {
        return Ok(());
    };
    std::fs::set_permissions(output_path, std::fs::Permissions::from_mode(mode)).map_err(|err| {
        format!(
            "failed to set permissions on curated plugins file {}: {err}",
            output_path.display()
        )
    })
}

#[cfg(not(unix))]
fn apply_zip_permissions(
    _entry: &zip::read::ZipFile<'_, impl std::io::Read + ?Sized>,
    _output_path: &Path,
) -> Result<(), String> {
    Ok(())
}

#[cfg(test)]
#[path = "startup_sync_tests.rs"]
mod tests;
