//! Input validation only; no authority is initialized or process launched.
use super::*;
use std::os::unix::fs::PermissionsExt;

#[test]
fn native_resources_and_private_draft_paths_are_required_without_loader_overrides()
-> Result<(), Box<dyn std::error::Error>> {
    let resources = tempfile::tempdir()?;
    let state = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()?;
    let mut environment = BTreeMap::from([
        (
            "TRILL_UI_MAKEPAD_RESOURCES".into(),
            resources
                .path()
                .to_str()
                .ok_or("non-UTF8 resources")?
                .into(),
        ),
        (
            "XDG_STATE_HOME".into(),
            state.path().to_str().ok_or("non-UTF8 state")?.into(),
        ),
    ]);
    // SAFETY: geteuid only observes the fixture process UID.
    let uid = unsafe { libc::geteuid() };
    validate_environment(&environment, uid)?;
    environment.insert("XMODIFIERS".into(), "@im=ibus".into());
    validate_environment(&environment, uid)?;
    environment.insert("XMODIFIERS".into(), "@im=unregistered-selector".into());
    assert!(validate_environment(&environment, uid).is_err());
    environment.remove("XMODIFIERS");
    std::fs::set_permissions(state.path(), std::fs::Permissions::from_mode(0o770))?;
    assert!(validate_environment(&environment, uid).is_err());
    std::fs::set_permissions(state.path(), std::fs::Permissions::from_mode(0o700))?;
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
    Ok(())
}
