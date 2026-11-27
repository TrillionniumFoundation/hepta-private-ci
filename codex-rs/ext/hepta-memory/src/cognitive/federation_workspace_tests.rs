use super::registered_workspace_path;
use codex_utils_path_uri::PathUri;
use std::path::Path;

#[test]
fn uri_workspace_recovers_registered_canonical_identity() {
    let directory = tempfile::tempdir().expect("workspace");
    let registered = directory
        .path()
        .canonicalize()
        .expect("canonical workspace");
    let decoded = PathUri::from_host_native_path(&registered)
        .expect("workspace uri")
        .to_path_buf();
    assert_ne!(decoded, registered, "exercise the removed verbatim prefix");
    assert_eq!(registered_workspace_path(&decoded), Some(registered));
}

#[test]
fn missing_and_relative_workspace_paths_are_rejected() {
    let directory = tempfile::tempdir().expect("workspace");
    let missing = directory.path().join("missing");
    assert_eq!(registered_workspace_path(&missing), None);
    assert_eq!(registered_workspace_path(Path::new("relative")), None);
}
