use std::fs;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_utils_path::windows_private_fs::PrivateDirectory;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::COGNITIVE_ACTIVE_DB_POINTER;
use super::CognitiveStoreOpenGuard;
use super::cleanup_candidate;
use super::create_private_directory;
use super::protect_database_file;
use super::publish_active_database;
use super::resolve_active_database_path;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn fixture() -> TestResult<(TempDir, PathBuf)> {
    let temporary = TempDir::new()?;
    let root = create_private_directory(&temporary.path().join("private").join("cognitive"))?;
    Ok((temporary, root))
}

fn write_new(root: &Path, name: &str, bytes: &[u8]) -> TestResult {
    let directory = PrivateDirectory::open_existing(root)?;
    let mut file = directory.create_new(name)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

#[test]
fn shared_and_exclusive_store_fences_survive_private_handle_opening() -> TestResult {
    let (_temporary, root) = fixture()?;
    let first = CognitiveStoreOpenGuard::acquire_shared(&root)?;
    let second = CognitiveStoreOpenGuard::acquire_shared(&root)?;
    assert!(CognitiveStoreOpenGuard::acquire_exclusive(&root).is_err());
    drop(first);
    assert!(CognitiveStoreOpenGuard::acquire_exclusive(&root).is_err());
    drop(second);
    let exclusive = CognitiveStoreOpenGuard::acquire_exclusive(&root)?;
    assert!(CognitiveStoreOpenGuard::acquire_shared(&root).is_err());
    drop(exclusive);
    let _reopened = CognitiveStoreOpenGuard::acquire_shared(&root)?;
    Ok(())
}

#[test]
fn active_generation_round_trip_rejects_later_hardlinks() -> TestResult {
    let (_temporary, root) = fixture()?;
    let generation = format!("cognitive_recovered_v1_{}.sqlite3", "a".repeat(64));
    let database = root.join(&generation);
    write_new(&root, &generation, b"controlled candidate")?;
    protect_database_file(&database)?;
    publish_active_database(&root, &database)?;
    assert_eq!(resolve_active_database_path(&root)?, database);
    let before = fs::read(root.join(COGNITIVE_ACTIVE_DB_POINTER))?;
    fs::hard_link(&database, root.join("candidate-link"))?;
    assert!(resolve_active_database_path(&root).is_err());
    assert!(protect_database_file(&database).is_err());
    assert_eq!(fs::read(root.join(COGNITIVE_ACTIVE_DB_POINTER))?, before);
    assert_eq!(fs::read(&database)?, b"controlled candidate");
    Ok(())
}

#[test]
fn publication_collision_preserves_existing_temporary_file() -> TestResult {
    let (_temporary, root) = fixture()?;
    let generation = format!("cognitive_recovered_v1_{}.sqlite3", "b".repeat(64));
    write_new(&root, &generation, b"new candidate")?;
    let temporary = format!(
        "{COGNITIVE_ACTIVE_DB_POINTER}.tmp-{}-{}",
        std::process::id(),
        "b".repeat(16)
    );
    write_new(&root, &temporary, b"existing temporary")?;
    assert!(publish_active_database(&root, &root.join(generation)).is_err());
    assert_eq!(fs::read(root.join(temporary))?, b"existing temporary");
    assert!(!root.join(COGNITIVE_ACTIVE_DB_POINTER).exists());
    Ok(())
}

#[test]
fn candidate_cleanup_preserves_unrelated_private_files() -> TestResult {
    let (_temporary, root) = fixture()?;
    let candidate = "candidate.sqlite3";
    for suffix in ["", "-wal", "-shm", "-journal"] {
        write_new(&root, &format!("{candidate}{suffix}"), b"candidate bytes")?;
    }
    write_new(&root, "unrelated", b"unrelated bytes")?;
    cleanup_candidate(&root.join(candidate), /*include_database*/ false)?;
    assert_eq!(fs::read(root.join(candidate))?, b"candidate bytes");
    for suffix in ["-wal", "-shm", "-journal"] {
        assert!(!root.join(format!("{candidate}{suffix}")).exists());
    }
    cleanup_candidate(&root.join(candidate), /*include_database*/ true)?;
    assert!(!root.join(candidate).exists());
    assert_eq!(fs::read(root.join("unrelated"))?, b"unrelated bytes");
    Ok(())
}
