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
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    fn uri(path: &str) -> PathUri {
        PathUri::parse(path).unwrap()
    }

    fn entry(path: &str, access: FileSystemAccessMode) -> FileSystemSandboxEntry {
        FileSystemSandboxEntry::new(uri(path).into(), access)
    }

    fn workspace(roots: &[PathUri]) -> FileSystemSandboxPolicy {
        FileSystemSandboxPolicy::workspace_write(&[], true, true)
            .materialize_project_roots_with_workspace_root_uris(roots)
            .unwrap()
    }

    #[test]
    fn foreign_workspace_roots_keep_every_drive_and_uri_authority() {
        let roots = [
            uri("file:///C:/workspace"),
            uri("file:///D:/other-workspace"),
            uri("file://server/share/workspace"),
        ];
        let policy = workspace(&roots);
        assert!(!policy.has_full_disk_write_access());
        for root in &roots {
            assert!(policy.entries.iter().any(|entry| {
                entry.access.can_write() && entry.path == FileSystemPath::from(root.clone())
            }));
            assert!(can_write_uri_path(
                &policy,
                &root.join("allowed.txt").unwrap(),
                &roots[0]
            ));
        }
        for denied in [
            "file:///C:/workspace-other/file",
            "file:///E:/workspace/file",
            "file://other-server/share/workspace/file",
            "file://server/other-share/workspace/file",
            "file:///C:/workspace%2Fother/file",
            "file:///C:/workspace/%5Coutside",
            "file:///C:/workspace/../outside",
        ] {
            assert!(
                !can_write_uri_path(&policy, &uri(denied), &roots[0]),
                "{denied}"
            );
        }
        assert!(can_write_uri_path(
            &policy,
            &uri("file:///c:/WORKSPACE/allowed.txt"),
            &roots[0]
        ));
    }

    #[test]
    fn uri_access_preserves_specificity_and_deny_ties() {
        let cwd = uri("file:///C:/workspace");
        let mut policy = workspace(std::slice::from_ref(&cwd));
        policy.entries.extend([
            entry("file:///C:/workspace/private", FileSystemAccessMode::Read),
            entry(
                "file:///C:/workspace/private/allowed",
                FileSystemAccessMode::Write,
            ),
            entry(
                "file:///C:/workspace/private/allowed/denied",
                FileSystemAccessMode::Write,
            ),
            entry(
                "file:///C:/workspace/private/allowed/denied",
                FileSystemAccessMode::Deny,
            ),
        ]);
        for (suffix, writable) in [
            ("public/file", true),
            ("private/file", false),
            ("private/allowed/file", true),
            ("private/allowed/denied/file", false),
        ] {
            assert_eq!(
                can_write_uri_path(&policy, &cwd.join(suffix).unwrap(), &cwd),
                writable
            );
        }
        policy.entries.reverse();
        assert!(!can_write_uri_path(
            &policy,
            &cwd.join("private/allowed/denied/file").unwrap(),
            &cwd
        ));
    }

    #[test]
    fn metadata_requires_a_specific_write_grant() {
        let cwd = uri("file:///C:/workspace");
        let mut policy = FileSystemSandboxPolicy::restricted(vec![entry(
            "file:///C:/workspace",
            FileSystemAccessMode::Write,
        )]);
        for name in [".git", ".agents", ".codex", ".GIT"] {
            assert!(!can_write_uri_path(
                &policy,
                &cwd.join(&format!("{name}/config")).unwrap(),
                &cwd
            ));
        }
        policy.entries.push(entry(
            "file:///C:/workspace/.git/config",
            FileSystemAccessMode::Write,
        ));
        assert!(can_write_uri_path(
            &policy,
            &cwd.join(".GIT/config").unwrap(),
            &cwd
        ));
        assert!(!can_write_uri_path(
            &policy,
            &cwd.join(".git/other").unwrap(),
            &cwd
        ));
    }

    #[test]
    fn read_only_and_unresolved_restrictions_do_not_grant_writes() {
        let cwd = uri("file:///C:/workspace");
        let path = cwd.join("file").unwrap();
        let read_only = FileSystemSandboxPolicy::restricted(vec![FileSystemSandboxEntry::new(
            FileSystemPath::Special {
                value: FileSystemSpecialPath::Root,
            },
            FileSystemAccessMode::Read,
        )]);
        assert!(!can_write_uri_path(&read_only, &path, &cwd));
        for restriction in [
            FileSystemPath::GlobPattern {
                pattern: "C:/workspace/private/**".to_string(),
            },
            FileSystemPath::Special {
                value: FileSystemSpecialPath::Tmpdir,
            },
        ] {
            let mut policy = workspace(std::slice::from_ref(&cwd));
            policy.entries.push(FileSystemSandboxEntry::new(
                restriction,
                FileSystemAccessMode::Deny,
            ));
            assert!(!can_write_uri_path(&policy, &path, &cwd));
        }
        assert!(can_write_uri_path(
            &FileSystemSandboxPolicy::unrestricted(),
            &path,
            &cwd
        ));
        assert!(can_write_uri_path(
            &FileSystemSandboxPolicy::external_sandbox(),
            &path,
            &cwd
        ));
    }

    #[test]
    fn encoded_separators_cannot_become_exact_write_grants() {
        let cwd = uri("file:///C:/workspace");
        for path in [
            "file:///C:/workspace/private%2Ffile",
            "file:///C:/workspace/private%5Cfile",
        ] {
            let policy =
                FileSystemSandboxPolicy::restricted(vec![entry(path, FileSystemAccessMode::Write)]);
            assert!(!can_write_uri_path(&policy, &uri(path), &cwd));
        }
    }

    #[test]
    fn posix_uri_checks_remain_case_sensitive() {
        let cwd = uri("file:///workspace");
        let policy = workspace(std::slice::from_ref(&cwd));
        assert!(can_write_uri_path(
            &policy,
            &uri("file:///workspace/file"),
            &cwd
        ));
        assert!(!can_write_uri_path(
            &policy,
            &uri("file:///WORKSPACE/file"),
            &cwd
        ));
        assert!(!can_write_uri_path(
            &policy,
            &uri("file:///workspace/.git/config"),
            &cwd
        ));
    }

    #[test]
    fn invalid_workspace_subpath_is_an_error_instead_of_a_dropped_restriction() {
        let policy = FileSystemSandboxPolicy::restricted(vec![FileSystemSandboxEntry::new(
            FileSystemPath::Special {
                value: FileSystemSpecialPath::ProjectRoots {
                    subpath: Some("invalid\0path".to_string()),
                },
            },
            FileSystemAccessMode::Deny,
        )]);
        // Mixed path conventions force target-native materialization on every host.
        assert!(
            policy
                .materialize_project_roots_with_workspace_root_uris(&[
                    uri("file:///C:/workspace"),
                    uri("file:///workspace"),
                ])
                .is_err()
        );
    }

    #[test]
    fn native_uri_checks_reuse_the_existing_native_policy() {
        let temp = tempfile::tempdir().unwrap();
        let cwd = PathUri::from_host_native_path(temp.path()).unwrap();
        let policy = workspace(std::slice::from_ref(&cwd));
        for suffix in [
            "file",
            "private/file",
            ".git/config",
            ".agents/plan",
            ".codex/config",
        ] {
            let path = cwd.join(suffix).unwrap();
            assert_eq!(
                policy.can_write_path_uri_with_cwd(&path, &cwd),
                policy.can_write_path_with_cwd(path.to_abs_path().unwrap().as_path(), temp.path()),
            );
        }
    }
}
