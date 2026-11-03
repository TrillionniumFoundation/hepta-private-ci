#![cfg(unix)]

use std::error::Error;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::fs::symlink;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

type TestResult = Result<(), Box<dyn Error>>;

fn layout(temp: &TempDir) -> Result<HeptaAgentLayout, Box<dyn Error>> {
    Ok(HeptaFleetRoot::parse(temp.path().canonicalize()?)?
        .layout()
        .agent(&AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?))
}

#[tokio::test]
async fn linked_matrix_root_is_rejected_before_creating_external_children() -> TestResult {
    let temp = TempDir::new()?;
    let outside = TempDir::new()?;
    let layout = layout(&temp)?;
    let parent = layout
        .matrix_root()
        .parent()
        .ok_or("matrix parent missing")?;
    fs::create_dir_all(parent.parent().ok_or("agent parent missing")?)?;
    symlink(outside.path(), parent)?;
    let mode = outside.path().metadata()?.permissions().mode();
    assert!(matches!(
        MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await,
        Err(MatrixDurableError::AccessDenied)
    ));
    assert_eq!(fs::read_dir(outside.path())?.count(), 0);
    assert_eq!(outside.path().metadata()?.permissions().mode(), mode);
    Ok(())
}

#[tokio::test]
async fn linked_database_and_journals_are_rejected_before_sqlite_or_chmod() -> TestResult {
    for suffix in ["", "-wal", "-shm", "-journal"] {
        for hard_link in [false, true] {
            let temp = TempDir::new()?;
            let outside = TempDir::new()?;
            let layout = layout(&temp)?;
            fs::create_dir_all(layout.matrix_root())?;
            let target = outside.path().join("private-evidence");
            fs::write(&target, b"unrelated private evidence")?;
            fs::set_permissions(&target, fs::Permissions::from_mode(0o640))?;
            let link = layout
                .matrix_root()
                .join(format!("matrix_1.sqlite3{suffix}"));
            if hard_link {
                fs::hard_link(&target, &link)?;
            } else {
                symlink(&target, &link)?;
            }
            assert!(matches!(
                MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await,
                Err(MatrixDurableError::AccessDenied)
            ));
            assert_eq!(fs::read(&target)?, b"unrelated private evidence");
            assert_eq!(target.metadata()?.permissions().mode() & 0o777, 0o640);
            assert_eq!(fs::read_dir(outside.path())?.count(), 1);
        }
    }
    Ok(())
}
