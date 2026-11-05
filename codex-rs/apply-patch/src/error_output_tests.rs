use super::AppliedPatchDelta;
use super::ApplyPatchError;
use super::apply_patch;
use codex_exec_server::LOCAL_FS;
use codex_utils_path_uri::PathUri;
use pretty_assertions::assert_eq;
use std::fs;

#[tokio::test]
async fn write_failure_stderr_preserves_the_actual_io_cause() -> anyhow::Result<()> {
    let temp = tempfile::tempdir()?;
    let target = temp.path().join("existing-directory");
    fs::create_dir(&target)?;
    let marker = target.join("marker.txt");
    fs::write(&marker, "unchanged\n")?;
    let cwd = PathUri::from_host_native_path(temp.path())?;
    let target_uri = PathUri::from_host_native_path(&target)?;
    let mut stdout = Vec::new();
    let mut stderr = Vec::new();

    let failure = apply_patch(
        "*** Begin Patch\n*** Add File: existing-directory\n+cannot replace a directory\n*** End Patch",
        &cwd,
        &mut stdout,
        &mut stderr,
        LOCAL_FS.as_ref(),
        /*sandbox*/ None,
    )
    .await
    .expect_err("writing a file over the existing directory must fail");
    let (error, delta) = failure.into_parts();
    let ApplyPatchError::IoError(error) = error else {
        panic!("the physical write failure must retain its I/O error: {error:?}");
    };

    assert_eq!(stdout, Vec::<u8>::new());
    assert_eq!(delta, AppliedPatchDelta::new(Vec::new(), /*exact*/ false));
    assert_eq!(error.context, "I/O error");
    assert!(fs::metadata(&target)?.is_dir());
    assert_eq!(fs::read_to_string(&marker)?, "unchanged\n");
    assert_eq!(
        String::from_utf8(stderr)?,
        format!(
            "Failed to write file {}: {}\n",
            target_uri.inferred_native_path_string(),
            error.source
        )
    );
    Ok(())
}
