use super::canonical_path_without_redirection;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::source;
use codex_hepta_paths::HeptaFleetRoot;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

#[tokio::test]
async fn native_and_os_canonical_roots_share_store_identity_and_source_replay() {
    let temp = TempDir::new().expect("temporary directory");
    let native = AbsolutePathBuf::from_absolute_path(temp.path())
        .expect("absolute temporary directory")
        .canonicalize()
        .expect("native canonical directory")
        .join("fleet")
        .into_path_buf();
    std::fs::create_dir(&native).expect("create fleet");
    let canonical = native.canonicalize().expect("OS canonical fleet");
    #[cfg(windows)]
    assert_ne!(native, canonical, "exercise ordinary and verbatim prefixes");
    let owner = agent_id(/*suffix*/ 230);
    let first = CognitiveStore::open(
        &HeptaFleetRoot::parse(&native)
            .expect("native root")
            .layout()
            .agent(&owner),
    )
    .await
    .expect("open native root");
    let second = CognitiveStore::open(
        &HeptaFleetRoot::parse(&canonical)
            .expect("OS root")
            .layout()
            .agent(&owner),
    )
    .await
    .expect("open OS canonical root");
    assert_eq!(first.path(), second.path());
    assert!(first.is_same_local_store(&second));
    assert_eq!(
        first.path(),
        first.path().canonicalize().expect("canonical database")
    );
    let access = CognitiveAccess::agent_private(owner);
    let draft = source(CognitiveScope::AgentPrivate, "namespace-replay", "one fact");
    let receipt = first
        .append_source(&access, &draft)
        .await
        .expect("append source");
    assert_eq!(
        second
            .append_source(&access, &draft)
            .await
            .expect("replay source"),
        receipt
    );
}

#[cfg(unix)]
#[tokio::test]
async fn symlinked_fleet_and_database_are_rejected() {
    let temp = TempDir::new().expect("temporary directory");
    let root = temp.path().canonicalize().expect("canonical root");
    let real = root.join("real");
    let alias = root.join("alias");
    std::fs::create_dir(&real).expect("real fleet");
    std::os::unix::fs::symlink(&real, &alias).expect("fleet symlink");
    assert_eq!(
        canonical_path_without_redirection(&alias).expect("inspect alias"),
        None
    );
    let layout = HeptaFleetRoot::parse(&alias)
        .expect("absolute alias")
        .layout()
        .agent(&agent_id(/*suffix*/ 231));
    assert!(matches!(
        CognitiveStore::open(&layout).await,
        Err(crate::CognitiveStoreError::Invalid(_))
    ));
    assert!(!layout.cognitive_root().join("cognitive_1.sqlite3").exists());

    let database = real.join("data.sqlite3");
    let database_alias = real.join("alias.sqlite3");
    std::fs::write(&database, b"unchanged").expect("seed file");
    std::os::unix::fs::symlink(&database, &database_alias).expect("file symlink");
    assert_eq!(
        canonical_path_without_redirection(&database_alias).expect("inspect file alias"),
        None
    );
    assert_eq!(std::fs::read(database).expect("read source"), b"unchanged");
}

#[cfg(windows)]
#[tokio::test]
async fn junction_and_its_descendants_are_rejected() {
    let temp = TempDir::new().expect("temporary directory");
    let real = temp.path().join("real");
    let alias = temp.path().join("alias");
    std::fs::create_dir(&real).expect("real fleet");
    std::fs::write(real.join("retained"), b"unchanged").expect("seed file");
    // Directory junctions exercise reparse rejection without requiring the
    // optional Windows symbolic-link privilege or Developer Mode.
    let output = std::process::Command::new("cmd.exe")
        .args(["/d", "/c", "mklink", "/J"])
        .arg(&alias)
        .arg(&real)
        .output()
        .expect("create junction");
    assert!(
        output.status.success(),
        "junction creation failed: {output:?}"
    );
    for path in [&alias, &alias.join("retained")] {
        assert_eq!(
            canonical_path_without_redirection(path).expect("inspect junction"),
            None
        );
    }
    let layout = HeptaFleetRoot::parse(&alias)
        .expect("absolute alias")
        .layout()
        .agent(&agent_id(/*suffix*/ 231));
    assert!(matches!(
        CognitiveStore::open(&layout).await,
        Err(crate::CognitiveStoreError::Invalid(_))
    ));
    assert!(!layout.cognitive_root().join("cognitive_1.sqlite3").exists());
    assert_eq!(
        std::fs::read(real.join("retained")).expect("read source"),
        b"unchanged"
    );
    std::fs::remove_dir(alias).expect("remove junction");
}
