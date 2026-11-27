use super::Payload;
use super::SetupMode;
use super::log_line;
use super::run_setup_acl_work;
use anyhow::Result;
use codex_windows_sandbox::SetupErrorCode;
use codex_windows_sandbox::SetupFailure;
use codex_windows_sandbox::extract_setup_failure;
use codex_windows_sandbox::log_note;
use std::io::Write;
use std::path::Path;

pub(super) fn run_with_marker(
    payload: &Payload,
    prepare: impl FnOnce() -> Result<()>,
    work: impl FnOnce() -> Result<()>,
    commit: impl FnOnce() -> Result<()>,
) -> Result<()> {
    let writes_setup_marker = !payload.refresh_only && payload.mode != SetupMode::ReadAclsOnly;
    if writes_setup_marker {
        prepare()?;
    }
    work()?;
    if writes_setup_marker {
        commit()?;
    }
    Ok(())
}

pub(super) fn run_setup_full(payload: &Payload, log: &mut dyn Write, sbx_dir: &Path) -> Result<()> {
    // Keep collected ACL failures when a later setup step returns early.
    let mut acl_errors = Vec::new();
    let outcome = run_setup_acl_work(payload, log, sbx_dir, &mut acl_errors);
    finish_acl_setup(payload, &acl_errors, outcome, log)?;
    log_note("setup binary completed", Some(sbx_dir));
    Ok(())
}

fn finish_acl_setup(
    payload: &Payload,
    acl_errors: &[String],
    outcome: Result<()>,
    log: &mut dyn Write,
) -> Result<()> {
    if acl_errors.is_empty() {
        return outcome;
    }

    let phase = if payload.refresh_only {
        "setup refresh"
    } else {
        "setup"
    };
    let mut message = format!("{phase} completed with errors: {acl_errors:?}");
    let mut code = outcome
        .as_ref()
        .err()
        .and_then(extract_setup_failure)
        .map(|failure| failure.code);
    if let Err(error) = outcome {
        message.push_str(&format!("; setup also failed: {error:#}"));
    }
    if let Err(error) = log_line(log, &message) {
        if code.is_none() {
            code = extract_setup_failure(&error).map(|failure| failure.code);
        }
        message.push_str(&format!("; error log also failed: {error:#}"));
    }
    Err(anyhow::Error::new(SetupFailure::new(
        code.unwrap_or(SetupErrorCode::HelperUnknownError),
        message,
    ))
    .context(format!("{phase} had errors")))
}

#[cfg(test)]
#[path = "setup_completion_tests.rs"]
mod tests;
