use super::sync_directory;
use pretty_assertions::assert_eq;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[test]
fn existing_directory_barrier_preserves_contents() -> TestResult {
    let temp = tempfile::tempdir()?;
    let file = temp.path().join("retained");
    std::fs::write(&file, b"durable candidate")?;
    sync_directory(temp.path())?;
    assert_eq!(std::fs::read(file)?, b"durable candidate");
    Ok(())
}

#[test]
fn directory_barrier_rejects_files_and_does_not_create_missing_paths() -> TestResult {
    let temp = tempfile::tempdir()?;
    let file = temp.path().join("file");
    let missing = temp.path().join("missing");
    std::fs::write(&file, b"retained")?;
    assert!(sync_directory(&file).is_err());
    assert!(sync_directory(&missing).is_err());
    assert!(!missing.exists());
    assert_eq!(std::fs::read(file)?, b"retained");
    Ok(())
}

#[cfg(unix)]
#[test]
fn directory_barrier_does_not_follow_a_symlink() -> TestResult {
    let temp = tempfile::tempdir()?;
    let real = temp.path().join("real");
    let alias = temp.path().join("alias");
    std::fs::create_dir(&real)?;
    std::os::unix::fs::symlink(&real, &alias)?;
    assert!(sync_directory(&alias).is_err());
    Ok(())
}

#[cfg(windows)]
#[test]
fn directory_barrier_does_not_follow_a_junction() -> TestResult {
    let temp = tempfile::tempdir()?;
    let real = temp.path().join("real");
    let alias = temp.path().join("alias");
    std::fs::create_dir(&real)?;
    let output = std::process::Command::new("cmd.exe")
        .args(["/d", "/c", "mklink", "/J"])
        .arg(&alias)
        .arg(&real)
        .output()?;
    assert!(
        output.status.success(),
        "junction creation failed: {output:?}"
    );
    assert!(sync_directory(&alias).is_err());
    std::fs::remove_dir(alias)?;
    Ok(())
}
