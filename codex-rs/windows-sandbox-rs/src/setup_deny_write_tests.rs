use super::apply_as_caller;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::fs;

#[test]
fn caller_admission_retains_the_target_and_its_parent_until_helper_completion() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let home = fixture.path().join("codex-home");
    let workspace = fixture.path().join("workspace");
    fs::create_dir(&workspace)?;
    let protected = workspace.join("protected.txt");
    fs::write(&protected, "original")?;
    let admission = apply_as_caller(
        &home,
        &workspace,
        std::slice::from_ref(&workspace),
        std::slice::from_ref(&protected),
    )?;
    let file_rename = fs::rename(&protected, workspace.join("retired.txt")).err();
    let parent_rename = fs::rename(&workspace, fixture.path().join("retired-root")).err();
    for error in [file_rename, parent_rename] {
        let error = error
            .ok_or_else(|| anyhow::anyhow!("admitted pathname was replaced while retained"))?;
        assert!(
            matches!(error.raw_os_error(), Some(5 | 32)),
            "unexpected rename failure: {error}"
        );
    }
    assert_eq!(fs::read_to_string(&protected)?, "original");
    drop(admission);
    fs::rename(&protected, workspace.join("retired.txt"))?;
    fs::rename(&workspace, fixture.path().join("retired-root"))?;
    assert_eq!(
        fs::read_to_string(fixture.path().join("retired-root/retired.txt"))?,
        "original"
    );
    Ok(())
}

#[test]
fn caller_admission_rejects_an_unresolved_reparse_ancestor() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let home = fixture.path().join("codex-home");
    let target = fixture.path().join("target");
    let alias = fixture.path().join("alias");
    fs::create_dir(&target)?;
    let protected = target.join("protected.txt");
    fs::write(&protected, "unchanged")?;
    std::os::windows::fs::symlink_dir(&target, &alias)?;
    let result = apply_as_caller(
        &home,
        &target,
        std::slice::from_ref(&target),
        &[alias.join("protected.txt")],
    );
    let error = match result {
        Ok(_) => anyhow::bail!("unresolved reparse ancestor was admitted"),
        Err(error) => error,
    };
    assert!(
        format!("{error:#}").contains("contains a reparse point"),
        "unexpected error: {error:#}"
    );
    assert_eq!(fs::read_to_string(&protected)?, "unchanged");
    let missing = alias.join("not-admitted/child");
    assert!(apply_as_caller(&home, &target, std::slice::from_ref(&target), &[missing],).is_err());
    assert!(!target.join("not-admitted").exists());
    Ok(())
}

#[test]
fn caller_admission_creates_and_protects_a_missing_nested_carveout() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let home = fixture.path().join("codex-home");
    let workspace = fixture.path().join("workspace");
    fs::create_dir(&workspace)?;
    let protected = workspace.join("missing/readonly");
    let admission = apply_as_caller(
        &home,
        &workspace,
        std::slice::from_ref(&workspace),
        std::slice::from_ref(&protected),
    )?;
    assert!(protected.is_dir());
    for sid in crate::cap::workspace_write_cap_sids_for_path(
        &home,
        &workspace,
        std::slice::from_ref(&workspace),
        &protected,
    )? {
        let sid = crate::token::LocalSid::from_string(&sid)?;
        // A repeat setup check must find the complete directory deny in place.
        assert!(!unsafe { crate::acl::add_deny_write_ace(&protected, sid.as_ptr())? });
    }
    drop(admission);
    Ok(())
}
