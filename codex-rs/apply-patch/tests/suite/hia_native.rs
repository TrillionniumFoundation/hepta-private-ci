use codex_apply_patch::ApplyPatchFileUpdateMode;
use codex_apply_patch::ApplyPatchOptions;
use codex_apply_patch::apply_patch_with_options;
use codex_exec_server::LOCAL_FS;
use codex_utils_path_uri::PathUri;
use pretty_assertions::assert_eq;
use std::fs;
use tempfile::tempdir;

#[tokio::test]
async fn native_matching_updates_large_files_in_both_line_ending_modes() -> anyhow::Result<()> {
    let prefix = "a".repeat(2 * 1024 * 1024);
    for (mode, ending) in [
        (ApplyPatchFileUpdateMode::NormalizeToLf, "\n"),
        (ApplyPatchFileUpdateMode::PreserveLineEndings, "\r\n"),
    ] {
        let dir = tempdir()?;
        let path = dir.path().join("large.txt");
        fs::write(&path, format!("{prefix}{ending}before{ending}"))?;
        let cwd = PathUri::from_host_native_path(dir.path())?;
        let mut stdout = Vec::new();
        let mut stderr = Vec::new();
        let delta = apply_patch_with_options(
            "*** Begin Patch\n*** Update File: large.txt\n@@\n-before\n+after\n*** End Patch",
            ApplyPatchOptions {
                update_file_mode: mode,
                ..ApplyPatchOptions::default()
            },
            &cwd,
            &mut stdout,
            &mut stderr,
            LOCAL_FS.as_ref(),
            /*sandbox*/ None,
        )
        .await?;
        assert!(!delta.is_empty());
        assert_eq!(
            fs::read_to_string(path)?,
            format!("{prefix}{ending}after{ending}")
        );
        assert_eq!(
            (stdout, stderr),
            (
                b"Success. Updated the following files:\nM large.txt\n".to_vec(),
                Vec::new()
            )
        );
    }
    Ok(())
}

#[tokio::test]
async fn native_matching_preserves_global_exact_match_precedence() -> anyhow::Result<()> {
    let dir = tempdir()?;
    let path = dir.path().join("quotes.txt");
    fs::write(&path, "“token”\n\"token\"\n")?;
    let cwd = PathUri::from_host_native_path(dir.path())?;
    let mut stdout = Vec::new();
    let mut stderr = Vec::new();
    apply_patch_with_options(
        "*** Begin Patch\n*** Update File: quotes.txt\n@@\n-\"token\"\n+changed\n*** End Patch",
        ApplyPatchOptions::default(),
        &cwd,
        &mut stdout,
        &mut stderr,
        LOCAL_FS.as_ref(),
        /*sandbox*/ None,
    )
    .await?;
    assert_eq!(fs::read_to_string(path)?, "“token”\nchanged\n");
    assert_eq!(stderr, Vec::<u8>::new());
    Ok(())
}
