#[cfg(windows)]
use std::path::Path;

use codex_hepta_contracts::AgentId;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;

use super::super::AUTOMATION_DB_FILENAME;
use super::super::AutomationStore;
use crate::AutomationError;
use crate::AutomationSchedule;
use crate::AutomationTaskDraft;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[tokio::test]
async fn ordinary_and_os_canonical_roots_reopen_the_same_durable_tasks() -> TestResult {
    let temp = tempfile::tempdir()?;
    let native = AbsolutePathBuf::from_absolute_path(temp.path())?
        .canonicalize()?
        .join("automation")
        .into_path_buf();
    std::fs::create_dir(&native)?;
    let canonical = native.canonicalize()?;
    #[cfg(windows)]
    assert_ne!(
        native, canonical,
        "exercise ordinary and verbatim namespace spellings"
    );
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let first = AutomationStore::open_root(native, owner.clone()).await?;
    let draft = AutomationTaskDraft::new(
        "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c14",
        "retain this task across a path spelling change",
        AutomationSchedule::Once,
        /*first_run_at_ms*/ 1_000,
        /*created_at_ms*/ 100,
    );
    let expected = first.create_task(&draft).await?;
    let first_path = first.path().to_path_buf();
    first.close().await;
    drop(first);

    let reopened = AutomationStore::open_root(canonical.clone(), owner).await?;
    assert_eq!(reopened.path(), canonical.join(AUTOMATION_DB_FILENAME));
    assert_eq!(reopened.path(), first_path);
    assert_eq!(reopened.task(draft.task_id).await?, Some(expected));
    reopened.close().await;
    drop(reopened);

    let other_owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13")?;
    assert!(matches!(
        AutomationStore::open_root(canonical, other_owner).await,
        Err(AutomationError::AccessDenied)
    ));
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn symlinked_automation_root_is_rejected_before_database_creation() -> TestResult {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let real = root.join("real");
    let alias = root.join("alias");
    std::fs::create_dir(&real)?;
    std::fs::write(real.join("retained"), b"unchanged")?;
    std::os::unix::fs::symlink(&real, &alias)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    assert!(matches!(
        AutomationStore::open_root(alias, owner).await,
        Err(AutomationError::Invalid)
    ));
    assert!(!real.join(AUTOMATION_DB_FILENAME).exists());
    assert_eq!(std::fs::read(real.join("retained"))?, b"unchanged");
    Ok(())
}

#[cfg(windows)]
#[test]
fn namespace_equivalence_preserves_every_location_component() {
    use super::same_components;

    for (canonical, requested) in [
        (r"\\?\C:\private\owner", r"C:\private\owner"),
        (r"\\?\UNC\server\share\owner", r"\\server\share\owner"),
    ] {
        assert!(same_components(Path::new(canonical), Path::new(requested)));
    }
    for (canonical, requested) in [
        (r"\\?\C:\private\owner", r"D:\private\owner"),
        (r"\\?\C:\private\owner", r"C:\private\other"),
        (r"\\?\UNC\server\share\owner", r"\\other\share\owner"),
        (r"\\?\UNC\server\share\owner", r"\\server\other\owner"),
    ] {
        assert!(!same_components(Path::new(canonical), Path::new(requested)));
    }
}

#[cfg(windows)]
#[tokio::test]
async fn junction_and_its_descendants_cannot_create_an_automation_database() -> TestResult {
    let temp = tempfile::tempdir()?;
    let real = temp.path().join("real");
    let alias = temp.path().join("alias");
    std::fs::create_dir_all(real.join("nested"))?;
    std::fs::write(real.join("retained"), b"unchanged")?;
    let output = std::process::Command::new("cmd.exe")
        .args(["/d", "/c", "mklink", "/J"])
        .arg(&alias)
        .arg(&real)
        .output()?;
    assert!(
        output.status.success(),
        "junction creation failed: {output:?}"
    );
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    for path in [&alias, &alias.join("nested")] {
        assert!(matches!(
            AutomationStore::open_root(path.to_path_buf(), owner.clone()).await,
            Err(AutomationError::Invalid)
        ));
        assert!(!path.join(AUTOMATION_DB_FILENAME).exists());
    }
    assert_eq!(std::fs::read(real.join("retained"))?, b"unchanged");
    std::fs::remove_dir(alias)?;
    Ok(())
}
