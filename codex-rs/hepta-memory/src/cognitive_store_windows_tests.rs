//! Exercise the cognitive caller's retained-directory lifetime on Windows.

use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;

use pretty_assertions::assert_eq;

use super::super::COGNITIVE_ACTIVE_DB_POINTER;
use super::super::COGNITIVE_RECOVERED_DB_PREFIX;
use super::super::CognitiveStoreOpenGuard;
use super::super::publish_active_database;
use super::super::sync::open_cognitive_directory_for_sync;
use super::create_private_directory;

struct Fixture {
    temporary: tempfile::TempDir,
    parent: PathBuf,
    root: PathBuf,
}

impl Fixture {
    fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let temporary = tempfile::tempdir()?;
        let root = temporary.path().join("private").join("cognitive");
        create_private_directory(&root)?;
        let root = root.canonicalize()?;
        let parent = root.parent().expect("cognitive parent").to_path_buf();
        Ok(Self {
            temporary,
            parent,
            root,
        })
    }

    fn assert_rename_is_denied(&self) {
        assert!(fs::rename(&self.root, self.parent.join("moved-cognitive")).is_err());
        assert!(fs::rename(&self.parent, self.parent.with_file_name("moved-private")).is_err());
    }

    fn rename_after_release(&self) -> std::io::Result<()> {
        fs::rename(&self.root, self.parent.join("moved-cognitive"))?;
        fs::rename(&self.parent, self.parent.with_file_name("moved-private"))
    }
}

#[test]
fn shared_store_guard_pins_directory_until_last_clone_drops()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let guard = CognitiveStoreOpenGuard::acquire_shared(&fixture.root)?;
    let retained = Arc::clone(&guard);
    drop(guard);
    fixture.assert_rename_is_denied();
    drop(retained);
    fixture.rename_after_release()?;
    Ok(())
}

#[test]
fn exclusive_store_guard_pins_directory_until_recovery_releases_it()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let guard = CognitiveStoreOpenGuard::acquire_exclusive(&fixture.root)?;
    fixture.assert_rename_is_denied();
    drop(guard);
    fixture.rename_after_release()?;
    Ok(())
}

#[test]
fn publication_sync_handle_pins_root_and_ancestor_until_drop()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let directory = open_cognitive_directory_for_sync(&fixture.root)?;
    fixture.assert_rename_is_denied();
    drop(directory);
    fixture.rename_after_release()?;
    Ok(())
}

#[test]
fn publication_rejects_junction_ancestor_before_creating_pointer()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let file_name = format!("{COGNITIVE_RECOVERED_DB_PREFIX}{}.sqlite3", "a".repeat(64));
    let database = fixture.root.join(&file_name);
    fs::write(&database, b"candidate identity fixture")?;
    let pointer = fixture.root.join(COGNITIVE_ACTIVE_DB_POINTER);
    let before = fs::read(&database)?;
    let alias = fixture.temporary.path().join("alias-private");
    // Junction creation does not need symlink privilege. A failed fixture is an
    // error, not a skipped security check or a successful rejection.
    let output = Command::new("cmd")
        .args(["/C", "mklink", "/J"])
        .arg(&alias)
        .arg(fixture.temporary.path().join("private"))
        .output()?;
    assert!(
        output.status.success(),
        "mklink /J failed: stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let redirected_root = alias.join("cognitive");
    let result = publish_active_database(&redirected_root, &redirected_root.join(&file_name));
    let after = fs::read(&database)?;
    let mut entries = fs::read_dir(&fixture.root)?
        .map(|entry| entry.map(|entry| entry.file_name()))
        .collect::<std::io::Result<Vec<_>>>()?;
    entries.sort();
    let pointer_created = pointer.try_exists()?;
    fs::remove_dir(&alias)?;
    assert!(
        result.is_err(),
        "publication must reject redirected ancestry"
    );
    assert_eq!(after, before);
    assert_eq!(entries, vec![std::ffi::OsString::from(file_name)]);
    assert!(!pointer_created);
    Ok(())
}
