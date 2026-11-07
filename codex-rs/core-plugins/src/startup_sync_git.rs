//! Git steps for one cancellable curated sync run.

use super::CURATED_PLUGINS_FETCH_REF;
use super::CURATED_PLUGINS_GIT_TIMEOUT;
use super::CURATED_PLUGINS_SHA_FILE;
use super::OPENAI_PLUGINS_GIT_URL;
use super::activate_curated_repo;
use super::curated_plugins_repo_path;
use super::ensure_git_success;
use super::ensure_marketplace_manifest_exists;
use super::git_command;
use super::prepare_curated_repo_parent_and_temp_dir;
use super::read_sha_file;
use super::write_curated_plugins_sha;
use codex_git_utils::GitCommandCancellation;
use codex_git_utils::run_git_command_with_custody;
use std::path::Path;

pub(super) fn sync_with_cancellation(
    codex_home: &Path,
    git_binary: &Path,
    cancellation: &GitCommandCancellation,
) -> Result<String, String> {
    cancellation.check()?;
    let repo_path = curated_plugins_repo_path(codex_home);
    let sha_path = codex_home.join(CURATED_PLUGINS_SHA_FILE);
    let remote_sha = git_ls_remote_head_sha(codex_home, git_binary, cancellation)?;
    let local_sha = read_local_git_or_sha_file(&repo_path, &sha_path, git_binary, cancellation);
    cancellation.check()?;

    if local_sha.as_deref() == Some(remote_sha.as_str()) && repo_path.join(".git").is_dir() {
        return Ok(remote_sha);
    }

    let staged_repo_dir = prepare_curated_repo_parent_and_temp_dir(&repo_path)?;
    run_git_in_repo(
        staged_repo_dir.path(),
        git_binary,
        cancellation,
        &["init"],
        "git init curated plugins repo",
    )?;

    if repo_path.join(".git").is_dir() {
        fetch_curated_plugins_commit(&repo_path, &remote_sha, git_binary, cancellation)?;
        fetch_curated_plugins_commit_from_source(
            staged_repo_dir.path(),
            &repo_path,
            CURATED_PLUGINS_FETCH_REF,
            git_binary,
            cancellation,
        )?;
    } else {
        fetch_curated_plugins_commit(
            staged_repo_dir.path(),
            &remote_sha,
            git_binary,
            cancellation,
        )?;
    }

    reset_curated_plugins_checkout(staged_repo_dir.path(), git_binary, cancellation)?;
    let fetched_sha = git_head_sha(staged_repo_dir.path(), git_binary, cancellation)?;
    if fetched_sha != remote_sha {
        return Err(format!(
            "curated plugins fetch HEAD mismatch: expected {remote_sha}, got {fetched_sha}"
        ));
    }

    ensure_marketplace_manifest_exists(staged_repo_dir.path())?;
    cancellation.check()?;
    activate_curated_repo(&repo_path, staged_repo_dir)?;
    write_curated_plugins_sha(&sha_path, &remote_sha)?;
    Ok(remote_sha)
}

fn fetch_curated_plugins_commit(
    repo_path: &Path,
    remote_sha: &str,
    git_binary: &Path,
    cancellation: &GitCommandCancellation,
) -> Result<(), String> {
    fetch_curated_plugins_commit_from(
        repo_path,
        OPENAI_PLUGINS_GIT_URL.as_ref(),
        remote_sha,
        git_binary,
        cancellation,
        "git fetch curated plugins repo",
    )
}

fn fetch_curated_plugins_commit_from_source(
    repo_path: &Path,
    source_repo_path: &Path,
    remote_sha: &str,
    git_binary: &Path,
    cancellation: &GitCommandCancellation,
) -> Result<(), String> {
    fetch_curated_plugins_commit_from(
        repo_path,
        source_repo_path,
        remote_sha,
        git_binary,
        cancellation,
        "git copy fetched curated plugins commit",
    )
}

fn fetch_curated_plugins_commit_from(
    repo_path: &Path,
    source: &Path,
    source_revision: &str,
    git_binary: &Path,
    cancellation: &GitCommandCancellation,
    context: &str,
) -> Result<(), String> {
    let fetch_refspec = format!("+{source_revision}:{CURATED_PLUGINS_FETCH_REF}");
    let mut command = git_command(git_binary);
    command
        .arg("-C")
        .arg(repo_path)
        .args(["fetch", "--depth", "1", "--no-tags"])
        .arg(source)
        .arg(fetch_refspec);
    let output = run_git_command_with_custody(
        &mut command,
        context,
        CURATED_PLUGINS_GIT_TIMEOUT,
        cancellation,
    )?;
    ensure_git_success(&output, context)
}

fn reset_curated_plugins_checkout(
    repo_path: &Path,
    git_binary: &Path,
    cancellation: &GitCommandCancellation,
) -> Result<(), String> {
    run_git_in_repo(
        repo_path,
        git_binary,
        cancellation,
        &["reset", "--hard", CURATED_PLUGINS_FETCH_REF],
        "git reset curated plugins repo",
    )?;
    run_git_in_repo(
        repo_path,
        git_binary,
        cancellation,
        &["clean", "-fdx"],
        "git clean curated plugins repo",
    )
}

fn run_git_in_repo(
    repo_path: &Path,
    git_binary: &Path,
    cancellation: &GitCommandCancellation,
    args: &[&str],
    context: &str,
) -> Result<(), String> {
    let mut command = git_command(git_binary);
    command.arg("-C").arg(repo_path).args(args);
    let output = run_git_command_with_custody(
        &mut command,
        context,
        CURATED_PLUGINS_GIT_TIMEOUT,
        cancellation,
    )?;
    ensure_git_success(&output, context)
}

fn read_local_git_or_sha_file(
    repo_path: &Path,
    sha_path: &Path,
    git_binary: &Path,
    cancellation: &GitCommandCancellation,
) -> Option<String> {
    if repo_path.join(".git").is_dir()
        && let Ok(sha) = git_head_sha(repo_path, git_binary, cancellation)
    {
        return Some(sha);
    }

    read_sha_file(sha_path)
}

fn git_ls_remote_head_sha(
    codex_home: &Path,
    git_binary: &Path,
    cancellation: &GitCommandCancellation,
) -> Result<String, String> {
    let mut command = git_command(git_binary);
    let _trusted_repository = crate::configure_trusted_git_repository(&mut command, codex_home)?;
    command
        .arg("ls-remote")
        .arg(OPENAI_PLUGINS_GIT_URL)
        .arg("HEAD");
    let output = run_git_command_with_custody(
        &mut command,
        "git ls-remote curated plugins repo",
        CURATED_PLUGINS_GIT_TIMEOUT,
        cancellation,
    )?;
    ensure_git_success(&output, "git ls-remote curated plugins repo")?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    let Some(first_line) = stdout.lines().next() else {
        return Err("git ls-remote returned empty output for curated plugins repo".to_string());
    };
    let Some((sha, _)) = first_line.split_once('\t') else {
        return Err(format!(
            "unexpected git ls-remote output for curated plugins repo: {first_line}"
        ));
    };
    if sha.is_empty() {
        return Err("git ls-remote returned empty sha for curated plugins repo".to_string());
    }
    Ok(sha.to_string())
}

fn git_head_sha(
    repo_path: &Path,
    git_binary: &Path,
    cancellation: &GitCommandCancellation,
) -> Result<String, String> {
    let mut command = git_command(git_binary);
    command
        .arg("-C")
        .arg(repo_path)
        .arg("rev-parse")
        .arg("HEAD");
    let output = run_git_command_with_custody(
        &mut command,
        "git rev-parse HEAD",
        CURATED_PLUGINS_GIT_TIMEOUT,
        cancellation,
    )?;
    ensure_git_success(&output, "git rev-parse HEAD")?;

    let sha = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if sha.is_empty() {
        return Err(format!(
            "git rev-parse HEAD returned empty output in {}",
            repo_path.display()
        ));
    }
    Ok(sha)
}

#[cfg(target_os = "macos")]
pub(super) fn apple_developer_tools_available(
    cancellation: &GitCommandCancellation,
) -> Result<bool, String> {
    let mut command = std::process::Command::new("/usr/bin/xcode-select");
    command.arg("-p");
    let result = run_git_command_with_custody(
        &mut command,
        "xcode-select developer tools probe",
        CURATED_PLUGINS_GIT_TIMEOUT,
        cancellation,
    );
    cancellation.check()?;
    Ok(result.is_ok_and(|output| output.status.success()))
}

#[cfg(test)]
pub(super) fn sync_openai_plugins_repo_via_git(
    codex_home: &Path,
    git_binary: &Path,
) -> Result<String, String> {
    sync_with_cancellation(codex_home, git_binary, &GitCommandCancellation::default())
}
