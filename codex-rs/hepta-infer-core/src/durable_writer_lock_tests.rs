use super::super::DurableInferenceControl;
use super::*;

use std::process::Command;

type TestResult = Result<(), Box<dyn std::error::Error>>;
const CHILD_PATH: &str = "HEPTA_TEST_CONTROL_WRITER_LOCK_PATH";

#[test]
fn lifecycle_lock_survives_journal_replacement_until_original_owner_drops() -> TestResult {
    let temporary =
        std::env::temp_dir().join(format!("hepta-writer-{:032x}", rand::random::<u128>()));
    fs::create_dir(&temporary)?;
    let path = temporary.join("control.journal");
    let owner = DurableInferenceControl::open(&path, 8)?;
    let stale_open = File::open(&path)?;
    fs::rename(&path, temporary.join("prior.journal"))?;
    fs::write(&path, [])?;
    assert!(matches!(
        DurableInferenceControl::open(&path, 8),
        Err(Error::WriterUnavailable)
    ));
    drop(owner);
    // The retained old journal descriptor is history; it must not own the new journal.
    let replacement = DurableInferenceControl::open(&path, 8)?;
    assert!(matches!(
        DurableInferenceControl::open(&path, 8),
        Err(Error::WriterUnavailable)
    ));
    drop(stale_open);
    drop(replacement);
    fs::remove_dir_all(temporary)?;
    Ok(())
}

#[cfg(unix)]
#[test]
fn canonical_directory_and_leaf_aliases_share_original_lifecycle_lock() -> TestResult {
    let temporary =
        std::env::temp_dir().join(format!("hepta-writer-{:032x}", rand::random::<u128>()));
    fs::create_dir(&temporary)?;
    let directory = temporary.join("actual");
    fs::create_dir(&directory)?;
    let path = directory.join("control.journal");
    let owner = DurableInferenceControl::open(&path, 8)?;
    let alias = temporary.join("directory-alias");
    std::os::unix::fs::symlink(&directory, &alias)?;
    let leaf = temporary.join("journal-alias");
    std::os::unix::fs::symlink(&path, &leaf)?;
    for selected in [alias.join("control.journal"), leaf] {
        assert!(matches!(
            DurableInferenceControl::open(&selected, 8),
            Err(Error::WriterUnavailable)
        ));
    }
    drop(owner);
    fs::remove_dir_all(temporary)?;
    Ok(())
}

#[cfg(unix)]
#[test]
fn dangling_journal_alias_and_nonregular_lifecycle_file_fail_before_replay() -> TestResult {
    let temporary =
        std::env::temp_dir().join(format!("hepta-writer-{:032x}", rand::random::<u128>()));
    fs::create_dir(&temporary)?;
    let target = temporary.join("missing.journal");
    let dangling = temporary.join("dangling");
    std::os::unix::fs::symlink(&target, &dangling)?;
    assert!(matches!(
        DurableInferenceControl::open(&dangling, 8),
        Err(Error::InvalidIdentity("native dangling journal symlink"))
    ));
    assert!(!target.exists());
    let path = temporary.join("control.journal");
    let (canonical, guard) = acquire(&path)?;
    let name = canonical
        .file_name()
        .ok_or("canonical journal name missing")?;
    let digest = Digest32::of_bytes(name.as_encoded_bytes());
    let lock_path = canonical.with_file_name(format!(".hepta-inference-{digest}.lock"));
    drop(guard);
    fs::remove_file(&lock_path)?;
    fs::create_dir(&lock_path)?;
    assert!(matches!(
        DurableInferenceControl::open(&path, 8),
        Err(Error::InvalidIdentity("native writer lock file"))
    ));
    assert!(!path.exists());
    fs::remove_dir_all(temporary)?;
    Ok(())
}

#[test]
fn independent_process_cannot_open_replaced_journal_while_original_owner_is_live() -> TestResult {
    let temporary =
        std::env::temp_dir().join(format!("hepta-writer-{:032x}", rand::random::<u128>()));
    fs::create_dir(&temporary)?;
    let path = temporary.join("control.journal");
    let owner = DurableInferenceControl::open(&path, 8)?;
    fs::rename(&path, temporary.join("prior.journal"))?;
    fs::write(&path, [])?;
    let child = Command::new(std::env::current_exe()?)
        .arg("--exact")
        .arg("durable_control::writer_lock::tests::locked_journal_child")
        .arg("--ignored")
        .env(CHILD_PATH, &path)
        .output()?;
    assert!(
        child.status.success(),
        "independent owner rejection failed: {}",
        String::from_utf8_lossy(&child.stderr)
    );
    assert!(
        String::from_utf8_lossy(&child.stdout).contains("1 passed;"),
        "independent owner check did not execute: {}",
        String::from_utf8_lossy(&child.stdout)
    );
    drop(owner);
    fs::remove_dir_all(temporary)?;
    Ok(())
}

/// Executed by the parent case in a separate native process with its original path.
#[test]
#[ignore = "only the parent process supplies the original locked owner path"]
fn locked_journal_child() -> TestResult {
    let path = std::env::var_os(CHILD_PATH).ok_or("missing original owner path")?;
    assert!(matches!(
        DurableInferenceControl::open(PathBuf::from(path), 8),
        Err(Error::WriterUnavailable)
    ));
    Ok(())
}
