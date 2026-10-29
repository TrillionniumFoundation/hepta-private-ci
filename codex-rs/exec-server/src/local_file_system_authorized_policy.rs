//! Compare kernel-resolved read paths against trusted Darwin system aliases.
//!
//! Only fixed aliases in the root-owned system namespace are folded. Mutable
//! descendants and their symlinks retain their policy spelling. The original
//! deny matcher sees every equivalent system spelling before any allow check.

use codex_protocol::permissions::FileSystemPath;
use codex_protocol::permissions::FileSystemSandboxPolicy;
use codex_protocol::permissions::FileSystemSpecialPath;
use codex_protocol::permissions::ReadDenyMatcher;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::io;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

pub(super) fn authorize(
    final_path: &Path,
    policy: &FileSystemSandboxPolicy,
    cwd: &Path,
) -> io::Result<()> {
    // The parents control the alias entries themselves. /private/tmp may be
    // writable, but /private controls its name; no child path is canonicalized.
    let protected_parents = ["/", "/private"].into_iter().all(|path| {
        std::fs::symlink_metadata(path).is_ok_and(|metadata| {
            metadata.is_dir() && metadata.uid() == 0 && metadata.mode() & 0o022 == 0
        })
    });
    let aliases: Vec<_> = [
        ("/var", "/private/var"),
        ("/tmp", "/private/tmp"),
        ("/etc", "/private/etc"),
    ]
    .into_iter()
    .filter(|(logical, physical)| {
        protected_parents
            && std::fs::symlink_metadata(logical)
                .is_ok_and(|metadata| metadata.file_type().is_symlink() && metadata.uid() == 0)
            && std::fs::read_link(logical).is_ok_and(|target| {
                target == Path::new(physical)
                    || target == Path::new(physical.trim_start_matches('/'))
            })
            && std::fs::symlink_metadata(physical)
                .is_ok_and(|metadata| metadata.is_dir() && metadata.uid() == 0)
    })
    .collect();
    authorize_with_aliases(final_path, policy, cwd, &aliases)
}

fn authorize_with_aliases(
    final_path: &Path,
    policy: &FileSystemSandboxPolicy,
    cwd: &Path,
    aliases: &[(&str, &str)],
) -> io::Result<()> {
    if let Some(matcher) = ReadDenyMatcher::new(policy, cwd) {
        let denied = matcher.is_read_denied(final_path)
            || aliases.iter().any(|(logical, physical)| {
                final_path
                    .strip_prefix(physical)
                    .is_ok_and(|suffix| matcher.is_read_denied(&Path::new(logical).join(suffix)))
            });
        if denied {
            return Err(super::authorized_read_error(
                io::ErrorKind::PermissionDenied,
            ));
        }
    }

    // Fold explicit policy paths, including nonexistent deny descendants, using
    // just the verified top-level substitution. Do not resolve nested symlinks.
    let mut effective_policy = policy.clone();
    for entry in &mut effective_policy.entries {
        let path = match &entry.path {
            FileSystemPath::Path { path } => Some(
                path.to_abs_path()
                    .map_err(|_| super::authorized_read_error(io::ErrorKind::InvalidInput))?,
            ),
            FileSystemPath::Special {
                value: FileSystemSpecialPath::Tmpdir,
            } => std::env::var_os("TMPDIR")
                .filter(|value| !value.is_empty())
                .and_then(|value| AbsolutePathBuf::from_absolute_path(value).ok()),
            FileSystemPath::Special {
                value: FileSystemSpecialPath::SlashTmp,
            } if Path::new("/tmp").is_dir() => Some(
                AbsolutePathBuf::from_absolute_path("/tmp")
                    .map_err(|_| super::authorized_read_error(io::ErrorKind::InvalidInput))?,
            ),
            FileSystemPath::Special { .. } | FileSystemPath::GlobPattern { .. } => None,
        };
        if let Some(path) = path {
            entry.path = normalize_system_alias(path.as_path(), aliases)?.into();
        }
    }
    let cwd = normalize_system_alias(cwd, aliases)?;
    if !effective_policy.can_read_path_with_cwd(final_path, cwd.as_path()) {
        return Err(super::authorized_read_error(
            io::ErrorKind::PermissionDenied,
        ));
    }
    Ok(())
}

fn normalize_system_alias(path: &Path, aliases: &[(&str, &str)]) -> io::Result<AbsolutePathBuf> {
    let path = aliases
        .iter()
        .find_map(|(logical, physical)| {
            path.strip_prefix(logical)
                .ok()
                .map(|suffix| Path::new(physical).join(suffix))
        })
        .unwrap_or_else(|| path.to_path_buf());
    AbsolutePathBuf::from_absolute_path(path)
        .map_err(|_| super::authorized_read_error(io::ErrorKind::InvalidInput))
}

#[cfg(test)]
#[path = "local_file_system_authorized_policy_tests.rs"]
mod tests;
