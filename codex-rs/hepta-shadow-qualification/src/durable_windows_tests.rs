use std::fs::OpenOptions;
use std::io;
use std::os::windows::fs::OpenOptionsExt;
use std::process::Command;

use super::open_directory_for_sync;
use super::sync_directory;

#[test]
fn writable_directory_handle_flushes_and_read_only_handle_reports_denial() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    std::fs::write(temporary.path().join("artifact"), b"durable bytes")?;
    let read_only = OpenOptions::new()
        .read(true)
        .custom_flags(0x0200_0000)
        .open(temporary.path())?;
    assert_eq!(read_only.sync_all().unwrap_err().raw_os_error(), Some(5));
    sync_directory(temporary.path())?;
    Ok(())
}

#[test]
fn directory_flush_rejects_regular_files_and_junctions() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let artifact = temporary.path().join("artifact");
    std::fs::write(&artifact, b"unchanged")?;
    assert_eq!(
        sync_directory(&artifact).unwrap_err().kind(),
        io::ErrorKind::InvalidInput
    );
    assert_eq!(std::fs::read(&artifact)?, b"unchanged");

    let target = temporary.path().join("target");
    let link = temporary.path().join("junction");
    std::fs::create_dir(&target)?;
    let status = Command::new("cmd.exe")
        .args(["/C", "mklink", "/J"])
        .arg(&link)
        .arg(&target)
        .status()?;
    assert!(status.success(), "create owned test junction");
    assert_eq!(
        sync_directory(&link).unwrap_err().kind(),
        io::ErrorKind::InvalidInput
    );
    sync_directory(&target)?;
    std::fs::remove_dir(&link)?;
    Ok(())
}

#[test]
fn directory_flush_preserves_the_native_missing_path_error() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let missing = temporary.path().join("missing");
    let expected = open_directory_for_sync(&missing).unwrap_err();
    let actual = sync_directory(&missing).unwrap_err();
    assert_eq!(actual.kind(), expected.kind());
    assert_eq!(actual.raw_os_error(), expected.raw_os_error());
    assert_eq!(actual.kind(), io::ErrorKind::NotFound);
    Ok(())
}
