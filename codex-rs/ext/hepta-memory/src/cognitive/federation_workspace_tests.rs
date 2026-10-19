use super::same_windows_namespace_identity;

#[test]
fn namespace_prefixes_preserve_exact_identity() {
    for path in [r"C:\workspace", r"\\server\share\workspace"] {
        assert!(same_windows_namespace_identity(path, path));
    }
    for alias in [r"\\?\C:\workspace", r"\\.\C:\workspace"] {
        assert!(same_windows_namespace_identity(r"C:\workspace", alias));
        assert!(same_windows_namespace_identity(alias, r"C:\workspace"));
    }
    for alias in [
        r"\\?\UNC\server\share\workspace",
        r"\\.\UNC\server\share\workspace",
    ] {
        assert!(same_windows_namespace_identity(
            r"\\server\share\workspace",
            alias
        ));
    }
}

#[test]
fn namespace_conversion_does_not_accept_other_identity_changes() {
    for other in [
        r"\\?\c:\workspace",
        r"\\?\C:\Workspace",
        r"\\?\C:\other",
        r"\\?\C:\workspace\..\workspace",
        r"\\?\Volume{unknown}\workspace",
    ] {
        assert!(!same_windows_namespace_identity(r"C:\workspace", other));
    }
}

#[cfg(windows)]
#[test]
fn canonical_workspace_survives_uri_roundtrip() -> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let canonical = std::fs::canonicalize(temp.path())?;
    let plain = codex_utils_path_uri::PathUri::from_host_native_path(&canonical)?.to_path_buf();
    assert_eq!(
        super::restore_workspace_identity(&canonical),
        Some(canonical.clone())
    );
    assert_eq!(
        super::restore_workspace_identity(&plain),
        Some(canonical.clone())
    );
    let restored = super::restore_workspace_identity(&plain)
        .ok_or_else(|| std::io::Error::other("workspace identity"))?;
    assert_eq!(
        crate::framing::workspace_digest(&restored),
        crate::framing::workspace_digest(&canonical)
    );
    use std::os::windows::ffi::OsStringExt;
    let invalid = canonical.join(std::ffi::OsString::from_wide(&[0xd800]));
    std::fs::create_dir(&invalid)?;
    assert!(std::fs::canonicalize(&invalid)?.is_dir());
    assert!(super::restore_workspace_identity(&invalid).is_none());
    assert!(super::restore_workspace_identity(std::path::Path::new("relative")).is_none());
    assert!(super::restore_workspace_identity(&temp.path().join("missing")).is_none());
    let file = temp.path().join("file");
    std::fs::write(&file, b"fixture")?;
    assert!(super::restore_workspace_identity(&file).is_none());
    Ok(())
}
