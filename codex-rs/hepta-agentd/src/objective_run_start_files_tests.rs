use std::fs;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::fs::symlink;
use std::path::PathBuf;

use super::RUN_START_DIRECTORY;
use super::RUN_START_FILE;
use super::open;

fn private_home() -> std::io::Result<(tempfile::TempDir, PathBuf)> {
    let temporary = tempfile::tempdir()?;
    let home = temporary.path().canonicalize()?.join("home");
    fs::create_dir(&home)?;
    fs::set_permissions(&home, fs::Permissions::from_mode(0o700))?;
    Ok((temporary, home))
}

#[test]
fn directory_symlink_is_rejected_before_target_chmod() -> anyhow::Result<()> {
    let (_temporary, home) = private_home()?;
    let outside = home
        .parent()
        .ok_or_else(|| anyhow::anyhow!("home parent"))?
        .join("outside");
    fs::create_dir(&outside)?;
    fs::set_permissions(&outside, fs::Permissions::from_mode(0o750))?;
    symlink(&outside, home.join(RUN_START_DIRECTORY))?;

    assert!(open(&home).is_err());
    assert_eq!(fs::metadata(&outside)?.permissions().mode() & 0o777, 0o750);
    assert!(!outside.join(RUN_START_FILE).exists());
    Ok(())
}

#[test]
fn regular_file_cannot_become_the_run_start_directory() -> anyhow::Result<()> {
    let (_temporary, home) = private_home()?;
    let root = home.join(RUN_START_DIRECTORY);
    fs::write(&root, b"preserved")?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o640))?;

    assert!(open(&home).is_err());
    assert_eq!(fs::read(&root)?, b"preserved");
    assert_eq!(fs::metadata(&root)?.permissions().mode() & 0o777, 0o640);
    Ok(())
}

#[test]
fn journal_symlinks_are_rejected_without_touching_targets() -> anyhow::Result<()> {
    for dangling in [false, true] {
        let (_temporary, home) = private_home()?;
        let root = home.join(RUN_START_DIRECTORY);
        fs::create_dir(&root)?;
        let outside = home
            .parent()
            .ok_or_else(|| anyhow::anyhow!("home parent"))?
            .join("outside.bin");
        if !dangling {
            fs::write(&outside, b"outside bytes")?;
            fs::set_permissions(&outside, fs::Permissions::from_mode(0o640))?;
        }
        symlink(&outside, root.join(RUN_START_FILE))?;

        assert!(open(&home).is_err());
        if dangling {
            assert!(!outside.exists());
        } else {
            assert_eq!(fs::read(&outside)?, b"outside bytes");
            assert_eq!(fs::metadata(&outside)?.permissions().mode() & 0o777, 0o640);
        }
    }
    Ok(())
}

#[test]
fn linked_regular_journal_is_rejected_without_modifying_its_alias() -> anyhow::Result<()> {
    let (_temporary, home) = private_home()?;
    let root = home.join(RUN_START_DIRECTORY);
    fs::create_dir(&root)?;
    let outside = home
        .parent()
        .ok_or_else(|| anyhow::anyhow!("home parent"))?
        .join("outside.bin");
    fs::write(&outside, b"outside bytes")?;
    fs::set_permissions(&outside, fs::Permissions::from_mode(0o640))?;
    fs::hard_link(&outside, root.join(RUN_START_FILE))?;

    assert!(open(&home).is_err());
    assert_eq!(fs::read(&outside)?, b"outside bytes");
    assert_eq!(fs::metadata(&outside)?.permissions().mode() & 0o777, 0o640);
    Ok(())
}

#[test]
fn new_files_have_private_modes_on_the_returned_descriptors() -> anyhow::Result<()> {
    let (_temporary, home) = private_home()?;
    let files = open(&home)?;

    assert_eq!(
        files.directory.metadata()?.permissions().mode() & 0o777,
        0o700
    );
    assert_eq!(
        files.journal.metadata()?.permissions().mode() & 0o777,
        0o600
    );
    assert_eq!(files.journal.metadata()?.len(), 0);
    assert_eq!(
        files.journal.metadata()?.ino(),
        fs::metadata(home.join(RUN_START_DIRECTORY).join(RUN_START_FILE))?.ino()
    );
    Ok(())
}

#[test]
fn existing_regular_journal_keeps_its_bytes_mode_and_identity() -> anyhow::Result<()> {
    let (_temporary, home) = private_home()?;
    let root = home.join(RUN_START_DIRECTORY);
    fs::create_dir(&root)?;
    let journal = root.join(RUN_START_FILE);
    fs::write(&journal, b"existing journal")?;
    fs::set_permissions(&journal, fs::Permissions::from_mode(0o640))?;
    let before = fs::metadata(&journal)?;

    let mut files = open(&home)?;
    let mut contents = Vec::new();
    files.journal.read_to_end(&mut contents)?;
    let after = files.journal.metadata()?;
    assert_eq!(contents, b"existing journal");
    assert_eq!(after.permissions().mode() & 0o777, 0o640);
    assert_eq!((after.dev(), after.ino()), (before.dev(), before.ino()));
    Ok(())
}

#[test]
fn held_journal_does_not_follow_a_replaced_root_path() -> anyhow::Result<()> {
    let (_temporary, home) = private_home()?;
    let root = home.join(RUN_START_DIRECTORY);
    let mut files = open(&home)?;
    let moved = home.join("held-run-start");
    fs::rename(&root, &moved)?;
    let outside = home
        .parent()
        .ok_or_else(|| anyhow::anyhow!("home parent"))?
        .join("outside");
    fs::create_dir(&outside)?;
    fs::write(outside.join(RUN_START_FILE), b"outside bytes")?;
    symlink(&outside, &root)?;

    files.journal.write_all(b"held bytes")?;
    files.journal.sync_all()?;
    files.directory.sync_all()?;
    assert_eq!(fs::read(moved.join(RUN_START_FILE))?, b"held bytes");
    assert_eq!(fs::read(outside.join(RUN_START_FILE))?, b"outside bytes");
    Ok(())
}
