//! File-backed control publication failures must not accumulate staging files
//! or turn a missing durability acknowledgement into a successful control.

use super::*;
use crate::durability::with_qualification_fault;
use anyhow::Result;
use pretty_assertions::assert_eq;

fn intent() -> Result<DurableControlIntent> {
    Ok(DurableControlIntent::new(
        AgentId::parse("00000000-0000-4000-8000-000000000001")?,
        DurableControlKind::Kill,
        /*target_spawn_generation*/ 7,
        ProcessIdentity::new(/*system_id*/ 41, "exact-control-owner")?,
        /*expected_lifecycle_generation*/ 8,
        /*requested_unix_ms*/ 1,
        /*stop_deadline_unix_ms*/ None,
    )?)
}

fn directory_entries(root: &Path) -> Result<Vec<std::ffi::OsString>> {
    let mut names = std::fs::read_dir(root)?
        .map(|entry| entry.map(|entry| entry.file_name()))
        .collect::<std::io::Result<Vec<_>>>()?;
    names.sort();
    Ok(names)
}

#[test]
fn repeated_real_control_rename_failures_leave_no_new_staging_files() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let destination = temp.path().join(CONTROL_INTENT_FILE);
    std::fs::create_dir(&destination)?;
    // A directory in the final file slot is a real rename rejection on every
    // supported filesystem; no injected writer or alternate codec is used.
    let foreign = temp.path().join(".foreign-staging.tmp");
    std::fs::write(&foreign, b"independently owned sentinel")?;
    let before = directory_entries(temp.path())?;
    let intent = intent()?;
    for _ in 0..32 {
        assert!(write_control_intent(temp.path(), &intent).is_err());
        assert_eq!(directory_entries(temp.path())?, before);
        assert!(destination.is_dir());
        assert_eq!(std::fs::read(&foreign)?, b"independently owned sentinel");
    }
    // Repair only the obstructing final path. The same logical intent can be
    // durably published without deleting another writer's unrelated staging.
    std::fs::remove_dir(&destination)?;
    write_control_intent(temp.path(), &intent)?;
    assert_eq!(read_control_intent(temp.path())?, Some(intent));
    assert_eq!(directory_entries(temp.path())?, before);
    Ok(())
}

#[test]
fn control_publication_fault_cuts_clean_staging_and_preserve_acknowledgement_errors() -> Result<()>
{
    for operation in ["file_write", "file_sync", "rename", "directory_sync"] {
        let temp = tempfile::tempdir()?;
        let prepared = intent()?;
        write_control_intent(temp.path(), &prepared)?;
        let path = temp.path().join(CONTROL_INTENT_FILE);
        let before = std::fs::read(&path)?;
        let requested = prepared.with_phase(DurableControlPhase::KillRequested, None)?;
        let fault = format!("control_intent.{operation}");
        let result = with_qualification_fault(&fault, std::io::ErrorKind::Other, || {
            write_control_intent(temp.path(), &requested)
        });
        assert!(
            result.is_err(),
            "missing durability acknowledgement: {operation}"
        );
        assert_eq!(
            directory_entries(temp.path())?,
            vec![std::ffi::OsString::from(CONTROL_INTENT_FILE)],
        );
        if operation == "directory_sync" {
            // Rename may already be visible. Visibility is still not a
            // successful persistence receipt or terminal process completion.
            assert_eq!(read_control_intent(temp.path())?, Some(requested.clone()));
        } else {
            assert_eq!(std::fs::read(&path)?, before);
            assert_eq!(read_control_intent(temp.path())?, Some(prepared));
        }
        assert!(has_unresolved(temp.path())?);
        write_control_intent(temp.path(), &requested)?;
        assert_eq!(read_control_intent(temp.path())?, Some(requested));
        assert!(has_unresolved(temp.path())?);
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            let metadata = std::fs::metadata(&path)?;
            assert_eq!(metadata.mode() & 0o077, 0);
            assert_eq!(metadata.nlink(), 1);
        }
    }
    Ok(())
}
