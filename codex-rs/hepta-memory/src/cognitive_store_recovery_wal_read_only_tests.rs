use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::process::ExitStatusExt;
use std::time::Duration;
use std::time::Instant;

struct ChildOwner(std::process::Child);

impl Drop for ChildOwner {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[tokio::test]
async fn sigkill_wal_history_uses_precrash_current_without_changing_source() {
    const CHILD_ROOT: &str = "HEPTA_HISTORY_WAL_CHILD";
    const READY: &str = "HEPTA_HISTORY_WAL_CURRENT";
    if let Some(root) = std::env::var_os(CHILD_ROOT) {
        let owner = agent_id(93);
        let layout = codex_hepta_paths::HeptaFleetRoot::parse(PathBuf::from(root))
            .expect("child fleet")
            .layout()
            .agent(&owner);
        let store = CognitiveStore::open(&layout)
            .await
            .expect("original active owner");
        store
            .append_source(
                &CognitiveAccess::agent_private(owner),
                &source(
                    CognitiveScope::AgentPrivate,
                    "precrash-source",
                    "acknowledged WAL content",
                ),
            )
            .await
            .expect("original durable commit in WAL");
        let current = store
            .recovery_anchor()
            .await
            .expect("cut while original owner is alive");
        // An independent test channel, outside suspect source storage, hands the
        // pre-crash witness to the parent. The observer never derives expected
        // Current from reopened SQLite. This is not a deployed Root fixture.
        let ready = PathBuf::from(std::env::var_os(READY).expect("ready destination"));
        let temporary = ready.with_extension("pending");
        std::fs::write(&temporary, serde_json::to_vec(&current).expect("cut bytes"))
            .expect("ready write");
        std::fs::rename(temporary, ready).expect("publish complete precrash witness");
        loop {
            std::thread::park();
        }
    }
    let fixture = HistoricalFixture::new().await;
    let ready = fixture
        .temp
        .path()
        .join("independent-precrash-current.json");
    let mut child = ChildOwner(std::process::Command::new(std::env::current_exe().expect("test binary"))
        .args(["--exact", "cognitive_store::recovery::tests::active_read_only::wal::sigkill_wal_history_uses_precrash_current_without_changing_source", "--nocapture"])
        .env(CHILD_ROOT, fixture.temp.path().join("fleet"))
        .env(READY, &ready).spawn().expect("original owner child"));
    let deadline = Instant::now() + Duration::from_secs(10);
    while !ready.exists() {
        if Instant::now() >= deadline {
            let _ = child.0.kill();
            let _ = child.0.wait();
            panic!("original owner did not publish its precrash cut");
        }
        assert!(
            child.0.try_wait().expect("child status").is_none(),
            "child exited before ready"
        );
        std::thread::sleep(Duration::from_millis(20));
    }
    let current: CognitiveRecoveryAnchor =
        serde_json::from_slice(&std::fs::read(&ready).expect("independent ready channel"))
            .expect("precrash cut");
    assert_ne!(current, fixture.current);
    child.0.kill().expect("actual SIGKILL");
    assert_eq!(
        child.0.wait().expect("reap child").signal(),
        Some(libc::SIGKILL)
    );
    let root = fixture.path.parent().expect("source root");
    let wal = PathBuf::from(format!("{}-wal", fixture.path.display()));
    assert!(
        std::fs::metadata(&wal)
            .expect("uncheckpointed source WAL")
            .len()
            > 32
    );
    let before = capture_recovery_tree(root);
    assert!(
        CognitiveStore::open_active_read_only_recovery(
            &fixture.layout(),
            CognitiveRecoveryRequirement::ExactCurrentCut(&current),
        )
        .await
        .is_err()
    );
    for _ in 0..2 {
        let history = CognitiveStore::open_active_wal_read_only_recovery(
            &fixture.layout(),
            CognitiveRecoveryRequirement::ExactCurrentCut(&current),
        )
        .await
        .expect("private WAL replay into authenticated readonly memory");
        assert_eq!(history.anchor(), &current);
        let retained = history
            .retained_operation(LEASE, OPERATION)
            .await
            .expect("original projection")
            .expect("old operation");
        assert_eq!(
            (
                retained.operation,
                retained.topic,
                retained.payload_json,
                retained.state
            ),
            (
                fixture.operation.clone(),
                HOS2_INSTALL_TOPIC_V1.to_owned(),
                fixture.request.to_json().expect("unchanged old D"),
                LocalOutcomeState::Indeterminate
            ),
        );
        history.close().await;
        assert_eq!(capture_recovery_tree(root), before);
    }
    assert!(matches!(
        CognitiveStore::open_active_wal_read_only_recovery(
            &fixture.layout(),
            CognitiveRecoveryRequirement::ExactCurrentCut(&fixture.current),
        )
        .await,
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));
    assert_eq!(capture_recovery_tree(root), before);
    assert!(matches!(
        CognitiveStore::open_active_wal_read_only_recovery(
            &fixture.layout(),
            CognitiveRecoveryRequirement::Revoked,
        )
        .await,
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));
    assert_eq!(capture_recovery_tree(root), before);
    // WAL cannot be ignored to authenticate the older database. Destroying the
    // copied source WAL content must reject the independently retained cut.
    let bytes = std::fs::read(&wal).expect("WAL bytes");
    std::fs::write(&wal, vec![0; bytes.len()]).expect("corrupt fixture WAL");
    let damaged = capture_recovery_tree(root);
    assert!(
        CognitiveStore::open_active_wal_read_only_recovery(
            &fixture.layout(),
            CognitiveRecoveryRequirement::ExactCurrentCut(&current),
        )
        .await
        .is_err()
    );
    assert_eq!(capture_recovery_tree(root), damaged);
}
