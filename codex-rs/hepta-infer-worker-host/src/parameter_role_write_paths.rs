//! Strict namespace write exceptions derived from complete original pinned configs.
//! Callers cannot supply an extra writable path or turn a read-only role into a writer.
use super::*;
use std::path::PathBuf;

pub(super) fn derive(
    request: &ParameterRoleExecutionV1,
    configuration: &[u8],
) -> HostResult<Vec<PathBuf>> {
    use ParameterRoleExecutionPurposeV1 as Purpose;
    let mut paths = match request.purpose {
        Purpose::ArtifactPreRegistrationPublication => {
            crate::initial_cpu_anchor::original_publication_write_paths(configuration)?
        }
        Purpose::ObserverPairedExecution => {
            codex_hepta_agent_components::intelligence_eval::fixed_paired_execution_write_paths_v1(
                configuration,
            )?
        }
        Purpose::ObserverPairedFinish => {
            codex_hepta_agent_components::intelligence_eval::fixed_paired_finish_write_paths_v1(
                configuration,
            )?
        }
        _ => Vec::new(),
    };
    paths.sort();
    paths.dedup();
    for path in &paths {
        validate(path, &request.inaccessible_paths)?;
        if request.uid != 0 || request.gid != 0 {
            return Err("original writable owner purpose requires actual Root custody".into());
        }
    }
    Ok(paths)
}

fn validate(path: &std::path::Path, denied: &[PathBuf]) -> HostResult<()> {
    if !path.is_absolute()
        || path.parent().is_none()
        || path.canonicalize()? != path
        || path
            .to_string_lossy()
            .bytes()
            .any(|v| v.is_ascii_whitespace() || v.is_ascii_control())
        || denied
            .iter()
            .any(|deny| path.starts_with(deny) || deny.starts_with(path))
    {
        return Err(
            "original writable path must be canonical and disjoint from role denials".into(),
        );
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if (!metadata.is_dir() && !metadata.is_file())
        || metadata.uid() != 0
        || metadata.mode() & 0o022 != 0
        || (metadata.is_file() && metadata.nlink() != 1)
    {
        return Err("original writable owner path must remain protected".into());
    }
    for ancestor in path.parent().ok_or("original writable parent")?.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
            return Err("original writable owner ancestors must remain Root protected".into());
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "parameter_role_write_paths_tests.rs"]
mod tests;
