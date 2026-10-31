use std::path::Path;

use codex_utils_path_uri::PathUri;

use super::canonical_workspace_path;
use super::workspace_digest;

#[test]
fn workspace_transport_round_trip_preserves_registered_digest() {
    let temp = tempfile::tempdir().expect("workspace");
    let canonical = temp.path().canonicalize().expect("canonical workspace");
    let transported = PathUri::from_host_native_path(&canonical)
        .expect("workspace URI")
        .to_path_buf();
    let restored = canonical_workspace_path(&transported).expect("transported canonical workspace");
    assert_eq!(restored, canonical);
    assert_eq!(workspace_digest(&restored), workspace_digest(&canonical));
    assert_eq!(canonical_workspace_path(&canonical), Some(canonical));
}

#[test]
fn workspace_normalization_rejects_relative_and_parent_aliases() {
    let temp = tempfile::tempdir().expect("workspace");
    let canonical = temp.path().canonicalize().expect("canonical workspace");
    let child = canonical.join("child");
    std::fs::create_dir(&child).expect("child");
    // PathBuf::push normalizes parent components for Windows verbatim paths.
    // Preserve the actual alias spelling so this exercises the rejection.
    let mut parent_alias = child.into_os_string();
    parent_alias.push(std::path::MAIN_SEPARATOR_STR);
    parent_alias.push("..");
    assert_eq!(canonical_workspace_path(Path::new("relative")), None);
    assert_eq!(canonical_workspace_path(Path::new(&parent_alias)), None);
    assert_eq!(canonical_workspace_path(&canonical.join("missing")), None);
}

#[cfg(unix)]
#[test]
fn workspace_normalization_rejects_symlink_aliases() {
    let temp = tempfile::tempdir().expect("workspace");
    let canonical = temp.path().canonicalize().expect("canonical workspace");
    let actual = canonical.join("actual");
    let alias = canonical.join("alias");
    std::fs::create_dir(&actual).expect("actual workspace");
    std::os::unix::fs::symlink(&actual, &alias).expect("symlink alias");
    assert_eq!(canonical_workspace_path(&alias), None);
    assert_eq!(canonical_workspace_path(&actual), Some(actual));
}
