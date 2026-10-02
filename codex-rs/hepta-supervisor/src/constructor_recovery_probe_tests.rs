use anyhow::Result;
use pretty_assertions::assert_eq;

use super::release_required;
use super::restart_required;

#[test]
fn only_absent_evidence_below_a_physical_parent_skips_recovery() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let run = temp.path().join("run");
    assert_eq!(
        (restart_required(&run), release_required(&run)),
        (true, true)
    );
    std::fs::create_dir(&run)?;
    assert_eq!(
        (restart_required(&run), release_required(&run)),
        (false, false)
    );
    std::fs::remove_dir(&run)?;
    std::fs::write(&run, b"not a directory")?;
    assert_eq!(
        (restart_required(&run), release_required(&run)),
        (true, true)
    );
    Ok(())
}

#[test]
fn each_restart_witness_and_any_release_file_preserves_validation() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let run = temp.path();
    for name in [
        crate::control_intent::CONTROL_INTENT_FILE,
        crate::restart_journal::RESTART_JOURNAL_FILE,
        crate::restart_lineage::RESTART_LINEAGE_FILE,
    ] {
        let path = run.join(name);
        // Damage must reach the original codec rather than being treated as no
        // pending restart. Exercise each independent durable trigger.
        std::fs::write(&path, b"damaged")?;
        assert_eq!(
            (restart_required(run), release_required(run)),
            (true, false)
        );
        std::fs::remove_file(&path)?;
    }
    let release = run.join(crate::release_transaction::RELEASE_TRANSACTION_FILE);
    std::fs::create_dir(&release)?;
    assert_eq!(
        (restart_required(run), release_required(run)),
        (false, true)
    );
    Ok(())
}

#[cfg(unix)]
#[test]
fn dangling_symlink_fifo_and_symlink_parent_are_never_absence() -> Result<()> {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;

    let temp = tempfile::tempdir()?;
    let run = temp.path().join("run");
    std::fs::create_dir(&run)?;
    let release = run.join(crate::release_transaction::RELEASE_TRANSACTION_FILE);
    std::os::unix::fs::symlink(temp.path().join("absent"), &release)?;
    assert!(release_required(&run));
    std::fs::remove_file(&release)?;
    let restart = run.join(crate::restart_journal::RESTART_JOURNAL_FILE);
    let fifo = CString::new(restart.as_os_str().as_bytes())?;
    // SAFETY: fifo is a live NUL-terminated pathname for this synchronous call.
    assert_eq!(
        unsafe {
            libc::mkfifo(fifo.as_ptr(), /*mode*/ 0o600)
        },
        0
    );
    assert!(restart_required(&run));
    std::fs::remove_file(restart)?;
    let alias = temp.path().join("alias");
    std::os::unix::fs::symlink(&run, &alias)?;
    assert_eq!(
        (restart_required(&alias), release_required(&alias)),
        (true, true)
    );
    Ok(())
}
