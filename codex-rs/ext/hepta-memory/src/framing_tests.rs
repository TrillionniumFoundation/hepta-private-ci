use codex_utils_path_uri::PathUri;

use super::registered_workspace_path;
use super::workspace_digest;

#[test]
fn transported_workspace_retains_its_registered_grant_identity() -> std::io::Result<()> {
    let root = tempfile::tempdir()?;
    let registered = root.path().canonicalize()?;
    let transported = PathUri::from_host_native_path(&registered)?.to_path_buf();
    let recovered = registered_workspace_path(&transported);
    assert_eq!(recovered, Some(registered.clone()));
    assert_eq!(
        recovered.as_deref().map(workspace_digest),
        Some(workspace_digest(&registered))
    );
    Ok(())
}

#[test]
fn unregistered_path_shapes_do_not_produce_a_workspace_identity() -> std::io::Result<()> {
    let root = tempfile::tempdir()?;
    let canonical = root.path().canonicalize()?;
    let file = canonical.join("ordinary-file");
    std::fs::write(&file, b"not a workspace")?;
    // PathBuf::join normalizes `..` on Windows verbatim paths. Preserve the
    // unregistered input spelling so the guard actually receives a parent step.
    let mut parent_step = canonical.as_os_str().to_os_string();
    parent_step.push(std::path::MAIN_SEPARATOR_STR);
    parent_step.push("..");
    for path in [
        std::path::PathBuf::from("relative-workspace"),
        canonical.join("missing"),
        std::path::PathBuf::from(parent_step),
        file,
    ] {
        assert_eq!(registered_workspace_path(&path), None);
    }
    Ok(())
}

#[cfg(unix)]
#[test]
fn symlink_alias_does_not_inherit_the_registered_workspace_grant() -> std::io::Result<()> {
    let root = tempfile::tempdir()?;
    let workspace = root.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    let workspace = workspace.canonicalize()?;
    let alias = root.path().join("alias");
    std::os::unix::fs::symlink(&workspace, &alias)?;
    assert_eq!(registered_workspace_path(&alias), None);
    assert_eq!(registered_workspace_path(&workspace), Some(workspace));
    Ok(())
}
