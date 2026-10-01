//! Preserve predecessor evidence while bounding admission of additional backups.
//! Recovery of an already admitted update never consults this ceiling.
use crate::error::ShellError;
use crate::update_storage::MAX_PACKAGE_BYTES;
use crate::update_storage::digest_file;
use std::path::Path;

const MAX_RETAINED_PREDECESSORS: usize = 4;
const MAX_BACKUP_SCAN_ENTRIES: usize = 16 * 1024;

pub(super) fn admit_predecessor_backup(
    target: &Path,
    backup: &Path,
    predecessor_digest: &str,
) -> Result<(), ShellError> {
    let parent = target
        .parent()
        .ok_or_else(|| ShellError::Update("update target lacks a parent".into()))?;
    let stem = target
        .file_stem()
        .and_then(std::ffi::OsStr::to_str)
        .ok_or_else(|| {
            ShellError::Update("update target lacks a portable backup identity".into())
        })?;
    let prefix = format!("{stem}.");
    let mut retained = 0_usize;
    let mut retained_bytes = 0_u64;
    let mut existing = false;
    for (index, entry) in std::fs::read_dir(parent)?.enumerate() {
        if index >= MAX_BACKUP_SCAN_ENTRIES {
            return Err(ShellError::Update(
                "predecessor backup directory exceeds its bounded inspection budget".into(),
            ));
        }
        let entry = entry?;
        let name = entry.file_name();
        let Some(digest) = name
            .to_str()
            .and_then(|name| name.strip_prefix(&prefix))
            .and_then(|name| name.strip_suffix(".predecessor"))
        else {
            continue;
        };
        if digest.len() != 64
            || !digest
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            continue; // An unrelated operator file is not retention authority.
        }
        let path = entry.path();
        let file = crate::file_input::open_regular_file(&path).map_err(|error| {
            ShellError::Security(format!(
                "retained predecessor backup is unavailable or redirected: {error}"
            ))
        })?;
        let bytes = file.metadata()?.len();
        if bytes == 0 || bytes > MAX_PACKAGE_BYTES {
            return Err(ShellError::Update(
                "retained predecessor backup exceeds its 512 MiB bound".into(),
            ));
        }
        retained += 1;
        retained_bytes += bytes;
        existing |= path == backup;
        if retained > MAX_RETAINED_PREDECESSORS
            || retained_bytes > MAX_PACKAGE_BYTES * MAX_RETAINED_PREDECESSORS as u64
        {
            return Err(ShellError::Update("predecessor backup retention ceiling is four files and 2 GiB; manage retained evidence before admitting another update".into()));
        }
    }
    if existing {
        if digest_file(backup)? != predecessor_digest {
            return Err(ShellError::Security(
                "existing predecessor backup does not match its admitted digest".into(),
            ));
        }
    } else if retained >= MAX_RETAINED_PREDECESSORS {
        return Err(ShellError::Update("predecessor backup retention ceiling is four files and 2 GiB; manage retained evidence before admitting another update".into()));
    }
    Ok(())
}

#[cfg(test)]
#[path = "update_backup_policy_tests.rs"]
mod tests;
