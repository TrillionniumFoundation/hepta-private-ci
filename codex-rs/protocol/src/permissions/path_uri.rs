//! Lexical permission checks for paths belonging to another executor's OS.

use super::FileSystemAccessMode;
use super::FileSystemPath;
use super::FileSystemSandboxEntry;
use super::FileSystemSandboxPolicy;
use super::FileSystemSpecialPath;
use super::PROJECT_ROOTS_GLOB_PATTERN_PREFIX;
use super::PROTECTED_METADATA_PATH_NAMES;
use codex_utils_path_uri::PathConvention;
use codex_utils_path_uri::PathUri;
use codex_utils_path_uri::PathUriParseError;

impl FileSystemSandboxPolicy {
    /// Materializes every selected workspace root without dropping foreign paths.
    /// Native-only roots retain the existing native materialization behavior.
    pub fn materialize_project_roots_with_workspace_root_uris(
        mut self,
        workspace_roots: &[PathUri],
    ) -> Result<Self, PathUriParseError> {
        if let Ok(native_roots) = workspace_roots
            .iter()
            .map(PathUri::to_abs_path)
            .collect::<Result<Vec<_>, _>>()
        {
            return Ok(self.materialize_project_roots_with_workspace_roots(&native_roots));
        }

        let mut entries = Vec::with_capacity(self.entries.len());
        for entry in self.entries {
            let subpath = match &entry.path {
                FileSystemPath::Special {
                    value: FileSystemSpecialPath::ProjectRoots { subpath },
                } => Some((subpath.as_deref().unwrap_or(""), false)),
                FileSystemPath::GlobPattern { pattern } => pattern
                    .strip_prefix(PROJECT_ROOTS_GLOB_PATTERN_PREFIX)
                    .map(|subpath| (subpath, true)),
                _ => None,
            };
            if let Some((subpath, glob)) = subpath {
                for root in workspace_roots {
                    let path = root.join(subpath)?;
                    entries.push(FileSystemSandboxEntry {
                        path: if glob {
                            FileSystemPath::GlobPattern {
                                pattern: path.inferred_native_path_string(),
                            }
                        } else {
                            path.into()
                        },
                        access: entry.access,
                        missing_path_behavior: entry.missing_path_behavior,
                    });
                }
            } else {
                entries.push(entry);
            }
        }
        self.entries = entries;
        Ok(self)
    }

    /// Checks lexical write authority without interpreting foreign paths on the host.
    ///
    /// This only permits the usual sandboxed attempt; the executor must still enforce
    /// filesystem aliases, links, and its actual sandbox. Target-specific restrictions
    /// that cannot be resolved here prevent automatic approval.
    pub fn can_write_path_uri_with_cwd(&self, path: &PathUri, cwd: &PathUri) -> bool {
        if let (Ok(path), Ok(cwd)) = (path.to_abs_path(), cwd.to_abs_path()) {
            return self.can_write_path_with_cwd(path.as_path(), cwd.as_path());
        }
        can_write_uri_path(self, path, cwd)
    }
}

fn has_lexical_path(path: &PathUri) -> bool {
    // A non-empty join rejects opaque fallbacks, and containment rejects encoded
    // native separators even when an entry exactly equals the candidate URI.
    path.join(".").is_ok()
        && path
            .ancestors()
            .last()
            .is_some_and(|root| path.starts_with(&root))
}

fn can_write_uri_path(policy: &FileSystemSandboxPolicy, path: &PathUri, cwd: &PathUri) -> bool {
    if policy.has_full_disk_write_access() {
        return true;
    }
    if !has_lexical_path(path)
        || !has_lexical_path(cwd)
        || path.infer_path_convention() != cwd.infer_path_convention()
    {
        return false;
    }
    let Some(entries) = resolved_uri_entries(policy, cwd) else {
        return false;
    };
    let access = entries
        .iter()
        .filter(|(root, _)| path.starts_with(root))
        .max_by_key(|(root, access)| (root.ancestors().count(), *access))
        .map(|(_, access)| *access);
    if access != Some(FileSystemAccessMode::Write) {
        return false;
    }

    // Preserve implicit metadata protection for every writable root, including
    // explicit additional roots. Only a write rule within that metadata subtree
    // can override it; a broader workspace grant cannot do so.
    for (root, access) in &entries {
        if !access.can_write() {
            continue;
        }
        for name in PROTECTED_METADATA_PATH_NAMES {
            let Ok(metadata) = root.join(name) else {
                return false;
            };
            if path.starts_with(&metadata)
                && !entries.iter().any(|(explicit, access)| {
                    access.can_write()
                        && explicit.starts_with(&metadata)
                        && path.starts_with(explicit)
                })
            {
                return false;
            }
        }
    }
    true
}

fn resolved_uri_entries(
    policy: &FileSystemSandboxPolicy,
    cwd: &PathUri,
) -> Option<Vec<(PathUri, FileSystemAccessMode)>> {
    let mut resolved = Vec::with_capacity(policy.entries.len());
    for entry in &policy.entries {
        let path = match &entry.path {
            FileSystemPath::Path { path } => {
                if !has_lexical_path(path) {
                    return None;
                }
                path.clone()
            }
            // Glob matching and TMPDIR resolution require the target's context.
            // An unresolved restriction must never disappear from this decision.
            FileSystemPath::GlobPattern { .. } => return None,
            FileSystemPath::Special { value } => match value {
                FileSystemSpecialPath::Root => cwd.ancestors().last()?,
                FileSystemSpecialPath::ProjectRoots { subpath } => {
                    cwd.join(subpath.as_deref().unwrap_or("")).ok()?
                }
                FileSystemSpecialPath::SlashTmp
                    if cwd.infer_path_convention() == Some(PathConvention::Posix) =>
                {
                    PathUri::parse("file:///tmp").ok()?
                }
                FileSystemSpecialPath::Tmpdir if !entry.access.can_write() => return None,
                FileSystemSpecialPath::Tmpdir
                | FileSystemSpecialPath::SlashTmp
                | FileSystemSpecialPath::Minimal
                | FileSystemSpecialPath::Unknown { .. } => continue,
            },
        };
        resolved.push((path, entry.access));
    }
    Some(resolved)
}

#[cfg(test)]
#[path = "path_uri_tests.rs"]
mod tests;
