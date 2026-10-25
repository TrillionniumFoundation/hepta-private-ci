//! Input validation only; no authority is initialized or process launched.
use super::*;

#[test]
fn native_resources_and_private_draft_paths_are_required_without_loader_overrides() {
    let resources = tempfile::tempdir().unwrap();
    let state = tempfile::tempdir().unwrap();
    let mut environment = BTreeMap::from([
        (
            "TRILL_UI_MAKEPAD_RESOURCES".into(),
            resources.path().to_str().unwrap().into(),
        ),
        (
            "XDG_STATE_HOME".into(),
            state.path().to_str().unwrap().into(),
        ),
    ]);
    // SAFETY: geteuid only observes the fixture process UID.
    let uid = unsafe { libc::geteuid() };
    validate_environment(&environment, uid).unwrap();
    environment.insert("LD_PRELOAD".into(), "/tmp/not-permitted.so".into());
    assert!(validate_environment(&environment, uid).is_err());
    environment.remove("LD_PRELOAD");
    environment.insert(
        "TRILL_UI_MAKEPAD_RESOURCES".into(),
        "relative/resources".into(),
    );
    assert!(validate_environment(&environment, uid).is_err());
    environment.remove("TRILL_UI_MAKEPAD_RESOURCES");
    assert!(validate_environment(&environment, uid).is_err());
}
