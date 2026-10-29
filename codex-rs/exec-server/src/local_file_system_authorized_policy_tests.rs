#![allow(clippy::expect_used)]

use super::*;
use codex_protocol::permissions::FileSystemAccessMode;
use codex_protocol::permissions::FileSystemSandboxEntry;
use pretty_assertions::assert_eq;

const ALIASES: &[(&str, &str)] = &[("/var", "/private/var")];

fn root_entry(path: &str, access: FileSystemAccessMode) -> FileSystemSandboxEntry {
    FileSystemSandboxEntry::new(
        AbsolutePathBuf::from_absolute_path(path)
            .expect("absolute test policy path")
            .into(),
        access,
    )
}

#[test]
fn kernel_path_uses_only_verified_system_alias_for_readable_root() {
    let policy = FileSystemSandboxPolicy::restricted(vec![root_entry(
        "/var/allowed",
        FileSystemAccessMode::Read,
    )]);
    let path = Path::new("/private/var/allowed/data");
    let cwd = Path::new("/var/allowed");
    let without_alias = authorize_with_aliases(path, &policy, cwd, &[])
        .expect_err("an unverified alias must not grant access");
    assert_eq!(without_alias.kind(), io::ErrorKind::PermissionDenied);
    authorize_with_aliases(path, &policy, cwd, ALIASES)
        .expect("verified system alias must preserve the readable root");
    let outside = authorize_with_aliases(
        Path::new("/private/var/outside/data"),
        &policy,
        cwd,
        ALIASES,
    )
    .expect_err("system alias folding must not grant a sibling root");
    assert_eq!(outside.kind(), io::ErrorKind::PermissionDenied);
}

#[test]
fn system_alias_keeps_missing_exact_and_glob_denies_in_both_spellings() {
    let paths = [
        FileSystemPath::from(
            AbsolutePathBuf::from_absolute_path("/var/allowed/future-secret")
                .expect("absolute deny path"),
        ),
        FileSystemPath::from(
            AbsolutePathBuf::from_absolute_path("/private/var/allowed/future-secret")
                .expect("absolute deny path"),
        ),
        FileSystemPath::GlobPattern {
            pattern: "/v?r/allowed/future-*".to_string(),
        },
        FileSystemPath::GlobPattern {
            pattern: "/private/var/allowed/future-*".to_string(),
        },
        FileSystemPath::GlobPattern {
            pattern: "future-*".to_string(),
        },
    ];
    for denied_path in paths {
        let policy = FileSystemSandboxPolicy::restricted(vec![
            root_entry("/var/allowed", FileSystemAccessMode::Read),
            FileSystemSandboxEntry::new(denied_path, FileSystemAccessMode::Deny),
        ]);
        let error = authorize_with_aliases(
            Path::new("/private/var/allowed/future-secret"),
            &policy,
            Path::new("/var/allowed"),
            ALIASES,
        )
        .expect_err("missing denies must survive alias normalization");
        assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
    }
}

#[test]
fn system_alias_preserves_mutable_descendant_policy_spelling() {
    let policy = FileSystemSandboxPolicy::restricted(vec![root_entry(
        "/var/allowed/mutable-link",
        FileSystemAccessMode::Read,
    )]);
    let error = authorize_with_aliases(
        Path::new("/private/var/allowed/link-target/data"),
        &policy,
        Path::new("/var/allowed"),
        ALIASES,
    )
    .expect_err("a nested mutable link must not become a new readable target");
    assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
}
