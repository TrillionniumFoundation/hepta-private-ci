use crate::acl::add_deny_write_ace_to_file;
use crate::acl_target;
use crate::acl_target::Disposition;
use crate::cap::workspace_write_cap_sids_for_path;
use crate::setup_error::SetupErrorCode;
use crate::setup_error::failure;
use crate::token::LocalSid;
use anyhow::Context;
use anyhow::Result;
use std::collections::HashSet;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;

pub(crate) struct CallerDenyAdmission {
    // Data/list access participates in sharing checks and excludes renaming
    // these objects until the helper returns. Sharing does not exclude every
    // reparse mutation: each later ACL open also atomically rejects reparses.
    _entries: Vec<File>,
}

/// Installs required carveouts under the effective caller before starting a helper.
///
/// CreateProcess does not inherit a thread impersonation token. The elevated
/// helper must therefore not be the first process to decide whether the caller
/// can establish a required deny. The helper repeats the same idempotent denials
/// after its write-root work, so neither elevation nor a successful earlier
/// admission replaces the final setup check.
pub(crate) fn apply_as_caller(
    codex_home: &Path,
    command_cwd: &Path,
    write_roots: &[PathBuf],
    deny_write_paths: &[PathBuf],
) -> Result<CallerDenyAdmission> {
    let mut entries = Vec::new();
    let mut seen = HashSet::new();
    let mut errors = Vec::new();
    for path in deny_write_paths {
        if !seen.insert(path) {
            continue;
        }
        anyhow::ensure!(
            path.is_absolute(),
            "deny-write path must be absolute: {}",
            path.display()
        );
        // Pin from the volume root down, rejecting a final reparse point at
        // every step. Never follow an unchecked ancestor to create a carveout.
        let ancestors: Vec<_> = path.ancestors().collect();
        for ancestor in ancestors
            .into_iter()
            .rev()
            .filter(|part| part.is_absolute())
        {
            let open = |disposition| {
                acl_target::open(
                    ancestor,
                    // FILE_READ_DATA is FILE_LIST_DIRECTORY for a directory.
                    READ_CONTROL | FILE_READ_ATTRIBUTES | FILE_READ_DATA,
                    FILE_SHARE_READ,
                    disposition,
                )
            };
            let file = match open(Disposition::Existing) {
                Ok(file) => file,
                Err(error)
                    if error
                        .downcast_ref::<std::io::Error>()
                        .is_some_and(|error| error.kind() == std::io::ErrorKind::NotFound) =>
                {
                    open(Disposition::DirectoryIfMissing)?
                }
                Err(error) => {
                    return Err(error)
                        .with_context(|| format!("retain deny-write path {}", ancestor.display()));
                }
            };
            let metadata = file.metadata()?;
            anyhow::ensure!(
                ancestor == path || metadata.is_dir(),
                "deny-write ancestor is not a directory: {}",
                ancestor.display()
            );
            entries.push(file);
        }
        let file = entries
            .last()
            .context("deny-write admission retained no target")?;
        for sid in workspace_write_cap_sids_for_path(codex_home, command_cwd, write_roots, path)? {
            let sid = LocalSid::from_string(&sid)?;
            // SAFETY: LocalSid owns a validated SID throughout the native call;
            // the validated target remains pinned through helper completion.
            if let Err(error) = unsafe { add_deny_write_ace_to_file(path, file, sid.as_ptr()) } {
                errors.push(format!("deny ACE failed on {}: {error}", path.display()));
            }
        }
    }
    if !errors.is_empty() {
        return Err(failure(
            SetupErrorCode::HelperUnknownError,
            format!(
                "sandbox filesystem ACL setup failed:\n{}",
                errors.join("\n")
            ),
        ));
    }
    Ok(CallerDenyAdmission { _entries: entries })
}

#[cfg(test)]
#[path = "setup_deny_write_tests.rs"]
mod tests;
