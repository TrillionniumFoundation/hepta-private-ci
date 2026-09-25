use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::ffi::OsString;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Condvar;
use std::sync::Mutex;
use tempfile::TempDir;

#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
#[cfg(unix)]
use std::os::unix::fs::symlink;

use super::*;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::ForgetMemoryDraft;
use crate::KgFactSetDraft;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryRevisionRecord;
use crate::MemoryVerification;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;

#[cfg(unix)]
#[path = "cognitive_store_recovery_read_only_tests.rs"]
mod cold_read_only;

struct RecoveryVerifier;

impl crate::ProductionAuthorityVerifier for RecoveryVerifier {
    fn verify(
        &self,
        authority: &crate::ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String> {
        if &authority.agent_id == expected_agent {
            Ok(())
        } else {
            Err("recovery authority owner mismatch".to_string())
        }
    }

    fn enter_use(
        &self,
        authority: &crate::ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<crate::ProductionAuthorityUseGuard, String> {
        self.verify(authority, expected_agent)?;
        Ok(crate::ProductionAuthorityUseGuard::from_verified_use(()))
    }
}

fn recovery_authority(owner: &AgentId) -> crate::ProductionAuthorityLease {
    crate::ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"recovery-grant"),
        7,
        11,
        u64::MAX,
        crate::ProductionAuthorityToken::from_verified_bytes(b"recovery-fence".to_vec())
            .expect("valid recovery token"),
    )
    .expect("valid recovery authority")
}

#[derive(Default)]
struct LinearizedRecoveryState {
    revoked: bool,
    active_uses: usize,
    revocation_requested: bool,
}

#[derive(Clone, Default)]
struct LinearizedRecoveryVerifier {
    state: Arc<(Mutex<LinearizedRecoveryState>, Condvar)>,
}

struct LinearizedRecoveryUse {
    state: Arc<(Mutex<LinearizedRecoveryState>, Condvar)>,
}

impl Drop for LinearizedRecoveryUse {
    fn drop(&mut self) {
        let (lock, changed) = &*self.state;
        let mut state = lock.lock().expect("linearized recovery state");
        state.active_uses = state
            .active_uses
            .checked_sub(1)
            .expect("recovery use count is positive");
        changed.notify_all();
    }
}

impl LinearizedRecoveryVerifier {
    fn wait_for_revocation_request(&self) {
        let (lock, changed) = &*self.state;
        let mut state = lock.lock().expect("linearized recovery state");
        while !state.revocation_requested {
            state = changed
                .wait(state)
                .expect("linearized recovery state after wait");
        }
    }

    fn revoke_and_wait(&self) {
        let (lock, changed) = &*self.state;
        let mut state = lock.lock().expect("linearized recovery state");
        state.revoked = true;
        state.revocation_requested = true;
        changed.notify_all();
        while state.active_uses != 0 {
            state = changed
                .wait(state)
                .expect("linearized recovery state after wait");
        }
    }
}

impl crate::ProductionAuthorityVerifier for LinearizedRecoveryVerifier {
    fn verify(
        &self,
        authority: &crate::ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String> {
        let state = self
            .state
            .0
            .lock()
            .map_err(|_| "linearized recovery state poisoned".to_string())?;
        if state.revoked {
            return Err("recovery authority revoked".to_string());
        }
        if &authority.agent_id != expected_agent {
            return Err("recovery authority owner mismatch".to_string());
        }
        Ok(())
    }

    fn enter_use(
        &self,
        authority: &crate::ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<crate::ProductionAuthorityUseGuard, String> {
        let mut state = self
            .state
            .0
            .lock()
            .map_err(|_| "linearized recovery state poisoned".to_string())?;
        if state.revoked {
            return Err("recovery authority revoked".to_string());
        }
        if &authority.agent_id != expected_agent {
            return Err("recovery authority owner mismatch".to_string());
        }
        state.active_uses = state.active_uses.saturating_add(1);
        drop(state);
        Ok(crate::ProductionAuthorityUseGuard::from_verified_use(
            LinearizedRecoveryUse {
                state: Arc::clone(&self.state),
            },
        ))
    }
}

struct RecoveryPhaseGate {
    target: CognitiveRecoveryPhase,
    state: Mutex<(bool, bool)>,
    changed: Condvar,
}

impl RecoveryPhaseGate {
    fn new(target: CognitiveRecoveryPhase) -> Self {
        Self {
            target,
            state: Mutex::new((false, false)),
            changed: Condvar::new(),
        }
    }

    fn observe(&self, phase: CognitiveRecoveryPhase) {
        if phase != self.target {
            return;
        }
        let mut state = self.state.lock().expect("recovery phase gate");
        state.0 = true;
        self.changed.notify_all();
        while !state.1 {
            state = self
                .changed
                .wait(state)
                .expect("recovery phase gate after wait");
        }
    }

    fn wait_until_reached(&self) {
        let mut state = self.state.lock().expect("recovery phase gate");
        while !state.0 {
            state = self
                .changed
                .wait(state)
                .expect("recovery phase gate after wait");
        }
    }

    fn release(&self) {
        let mut state = self.state.lock().expect("recovery phase gate");
        state.1 = true;
        self.changed.notify_all();
    }
}

async fn seeded(
    temp: &TempDir,
    owner: &AgentId,
) -> (CognitiveStore, CognitiveAccess, MemoryRevisionRecord) {
    let store = CognitiveStore::open(&layout(temp, owner))
        .await
        .expect("store");
    let access = CognitiveAccess::agent_private(owner.clone());
    let receipt = store
        .remember_with_kg(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "recovery-source",
                "remembered fact",
            ),
            &MemoryDraft {
                stable_key: "recovery-memory".to_string(),
                revision: MemoryRevisionDraft {
                    scope: CognitiveScope::AgentPrivate,
                    content: "remembered fact".to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: Vec::new(),
                },
            },
            &KgFactSetDraft::default(),
        )
        .await
        .expect("seed memory");
    (store, access, receipt.memory)
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct RecoveryTreeImage {
    directory: MetadataImage,
    entries: BTreeMap<OsString, EntryImage>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct MetadataImage {
    length: u64,
    readonly: bool,
    modified: Option<std::time::SystemTime>,
    #[cfg(unix)]
    device: u64,
    #[cfg(unix)]
    inode: u64,
    #[cfg(unix)]
    mode: u32,
    #[cfg(unix)]
    links: u64,
    #[cfg(unix)]
    modified_seconds: i64,
    #[cfg(unix)]
    modified_nanoseconds: i64,
    #[cfg(unix)]
    changed_seconds: i64,
    #[cfg(unix)]
    changed_nanoseconds: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct EntryImage {
    metadata: MetadataImage,
    payload: EntryPayload,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum EntryPayload {
    Bytes(Vec<u8>),
    Symlink(PathBuf),
}

async fn assert_revocation_is_linearized_at_recovery_phase(phase: CognitiveRecoveryPhase) {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(111);
    let (store, _, _) = seeded(&temp, &owner).await;
    let expected = store.recovery_anchor().await.expect("current cut");
    let owner_layout = layout(&temp, &owner);
    store.pool.close().await;
    drop(store);

    let verifier = Arc::new(LinearizedRecoveryVerifier::default());
    let verifier_for_recovery = Arc::clone(&verifier);
    let authority = recovery_authority(&owner);
    let gate = Arc::new(RecoveryPhaseGate::new(phase));
    let gate_for_recovery = Arc::clone(&gate);
    let recovery = tokio::spawn(async move {
        let observer = move |observed| gate_for_recovery.observe(observed);
        CognitiveStore::open_with_recovery_observed(
            &owner_layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&expected),
            &authority,
            verifier_for_recovery.as_ref(),
            &observer,
        )
        .await
    });

    gate.wait_until_reached();
    let verifier_for_revocation = Arc::clone(&verifier);
    let revocation = std::thread::spawn(move || verifier_for_revocation.revoke_and_wait());
    verifier.wait_for_revocation_request();
    assert!(
        !revocation.is_finished(),
        "revocation acknowledgement must wait for the recovery publication guard at {phase:?}"
    );
    gate.release();
    let recovered = recovery
        .await
        .expect("recovery task")
        .expect("guarded recovery");
    recovered.pool.close().await;
    drop(recovered);
    revocation.join().expect("revocation thread");
    assert!(
        verifier
            .verify(&recovery_authority(&owner), &owner)
            .is_err(),
        "authority must remain revoked after the guarded recovery completes"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn recovery_copy_checkpoint_and_publication_are_linearized_against_revocation() {
    for phase in [
        CognitiveRecoveryPhase::PrivateCopyMaterialized,
        CognitiveRecoveryPhase::BeforeCheckpoint,
        CognitiveRecoveryPhase::AfterCheckpoint,
        CognitiveRecoveryPhase::BeforePublication,
        CognitiveRecoveryPhase::AfterPublication,
    ] {
        assert_revocation_is_linearized_at_recovery_phase(phase).await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn revocation_after_preflight_before_recovery_use_prevents_publication() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(112);
    let (store, _, _) = seeded(&temp, &owner).await;
    let expected = store.recovery_anchor().await.expect("current cut");
    let root = store.path().parent().expect("cognitive root").to_path_buf();
    store.pool.close().await;
    drop(store);
    // Model an older owner layout: rejected authority must not even create
    // its new generation marker before entering the trusted use boundary.
    std::fs::remove_file(root.join(".cognitive-generation.lock"))
        .expect("legacy owner without generation marker");
    let tree_before = capture_recovery_tree(&root);
    let owner_layout = layout(&temp, &owner);
    let authority = recovery_authority(&owner);
    let verifier = Arc::new(LinearizedRecoveryVerifier::default());
    let verifier_for_recovery = Arc::clone(&verifier);
    let gate = Arc::new(RecoveryPhaseGate::new(
        CognitiveRecoveryPhase::BeforeAuthorityUse,
    ));
    let gate_for_recovery = Arc::clone(&gate);
    let recovery = tokio::spawn(async move {
        let observer = move |observed| gate_for_recovery.observe(observed);
        CognitiveStore::open_with_recovery_observed(
            &owner_layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&expected),
            &authority,
            verifier_for_recovery.as_ref(),
            &observer,
        )
        .await
    });
    gate.wait_until_reached();
    verifier.revoke_and_wait();
    gate.release();
    let failure = recovery
        .await
        .expect("recovery task")
        .err()
        .expect("revoked recovery must not publish");
    assert!(matches!(failure, CognitiveRecoveryError::AccessDenied(_)));
    assert_eq!(
        capture_recovery_tree(&root),
        tree_before,
        "revocation before guarded recovery use must not create or publish a candidate"
    );
}

#[tokio::test]
async fn exact_current_cut_recovers_writable_generation_and_persists_activation() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(91);
    let (store, access, _) = seeded(&temp, &owner).await;
    let anchor = store
        .recovery_anchor()
        .await
        .expect("trusted current witness");
    let serialized = serde_json::to_vec(&anchor).expect("host serializable witness");
    let retained: CognitiveRecoveryAnchor =
        serde_json::from_slice(&serialized).expect("retained witness");
    assert_eq!(retained, anchor);
    let original = store.path().to_path_buf();
    store.pool.close().await;
    drop(store);

    let authority = recovery_authority(&owner);
    let recovered = CognitiveStore::open_with_recovery(
        &layout(&temp, &owner),
        CognitiveRecoveryRequirement::ExactCurrentCut(&retained),
        &authority,
        &RecoveryVerifier,
    )
    .await
    .expect("descriptor-bound writable recovery");
    assert_ne!(recovered.path(), original.as_path());
    assert_eq!(
        recovered.recovery_anchor().await.expect("recovered anchor"),
        retained
    );

    recovered
        .append_source(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "post-recovery-source",
                "post recovery write",
            ),
        )
        .await
        .expect("recovered store is writable");
    let advanced = recovered
        .recovery_anchor()
        .await
        .expect("advanced current witness");
    assert_ne!(advanced, retained);
    let recovered_path = recovered.path().to_path_buf();
    recovered.pool.close().await;
    drop(recovered);

    let reopened = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("ordinary reopen follows activated generation");
    assert_eq!(reopened.path(), recovered_path.as_path());
    assert_eq!(
        reopened.recovery_anchor().await.expect("reopen anchor"),
        advanced
    );
}

#[tokio::test]
async fn post_rename_publication_failure_is_indeterminate_and_retains_candidate() {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(78);
    let (store, _, _) = seeded(&temp, &owner).await;
    let anchor = store.recovery_anchor().await.expect("current cut");
    let authority = recovery_authority(&owner);
    let fence = authority
        .fencing_token_digest()
        .expect("recovery fence digest");
    let root = store.path().parent().expect("cognitive root").to_path_buf();
    let candidate = root.join(recovered_database_filename(&anchor, &fence));
    std::fs::copy(store.path(), &candidate).expect("candidate file");
    protect_database_file(&candidate).expect("private candidate");
    publish_active_database(&root, &candidate).expect("pointer rename");

    let error = reconcile_failed_recovery_candidate(
        &root,
        &candidate,
        CognitiveRecoveryError::Unavailable(
            "injected directory fsync failure after pointer rename".to_string(),
        ),
    );
    assert!(
        matches!(
            error,
            CognitiveRecoveryError::Indeterminate(ref message)
                if message.contains("pointer rename")
        ),
        "post-rename publication uncertainty must remain indeterminate: {error:?}"
    );
    assert_eq!(
        resolve_active_database_path(&root).expect("active pointer"),
        candidate
    );
    assert!(
        candidate.exists(),
        "a possibly active recovered generation must not be cleaned up"
    );
}

#[tokio::test]
async fn writable_recovery_requires_exclusive_store_fence() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(90);
    let (store, _, _) = seeded(&temp, &owner).await;
    let anchor = store.recovery_anchor().await.expect("current witness");
    let authority = recovery_authority(&owner);
    assert!(matches!(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
            &authority,
            &RecoveryVerifier,
        )
        .await,
        Err(CognitiveRecoveryError::Unavailable(_))
    ));
}

#[tokio::test]
async fn predecessor_witness_is_rejected_and_current_witness_recovers() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(92);
    let (store, access, memory) = seeded(&temp, &owner).await;
    let predecessor = store.recovery_anchor().await.expect("predecessor witness");
    store
        .forget_with_kg(
            &access,
            &memory.id.memory_id,
            memory.id.revision,
            &source(
                CognitiveScope::AgentPrivate,
                "forget-source",
                "explicit forget",
            ),
            &ForgetMemoryDraft {
                scope: CognitiveScope::AgentPrivate,
                reason: "explicit forget".to_string(),
                valid_from_unix_seconds: 200,
                citations: Vec::new(),
            },
        )
        .await
        .expect("acknowledged forget");
    let current = store.recovery_anchor().await.expect("current witness");
    assert_ne!(current, predecessor);
    store.pool.close().await;
    drop(store);
    let authority = recovery_authority(&owner);

    assert!(matches!(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&predecessor),
            &authority,
            &RecoveryVerifier,
        )
        .await,
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));

    let recovered = CognitiveStore::open_with_recovery(
        &layout(&temp, &owner),
        CognitiveRecoveryRequirement::ExactCurrentCut(&current),
        &authority,
        &RecoveryVerifier,
    )
    .await
    .expect("current witness recovers");
    assert_eq!(
        recovered.recovery_anchor().await.expect("recovered anchor"),
        current
    );
}

#[tokio::test]
async fn revoked_owner_profile_and_witness_checks_precede_recovery_admission() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(93);
    let (store, _, _) = seeded(&temp, &owner).await;
    let anchor = store.recovery_anchor().await.expect("current witness");
    let authority = recovery_authority(&owner);

    assert!(matches!(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::Revoked,
            &authority,
            &RecoveryVerifier,
        )
        .await,
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));

    let wrong_layout = layout(&temp, &agent_id(94));
    assert!(matches!(
        CognitiveStore::open_with_recovery(
            &wrong_layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
            &authority,
            &RecoveryVerifier,
        )
        .await,
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));
    assert!(!wrong_layout.cognitive_root().exists());

    let mut unsupported = anchor.clone();
    unsupported.profile = "unsupported".to_string();
    assert!(matches!(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&unsupported),
            &authority,
            &RecoveryVerifier,
        )
        .await,
        Err(CognitiveRecoveryError::Invalid(_))
    ));

    store.pool.close().await;
    drop(store);
    let mut tampered = anchor;
    tampered.state_digest = Sha256Digest::for_bytes(b"altered witness");
    assert!(matches!(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&tampered),
            &authority,
            &RecoveryVerifier,
        )
        .await,
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));
}

#[cfg(unix)]
#[derive(Clone, Copy, Debug)]
enum IdentityAttack {
    Missing,
    Symlink,
    Hardlink,
    Mode,
}

#[cfg(unix)]
#[tokio::test]
async fn hostile_file_identities_fail_closed_without_additional_mutation() {
    let attacks = [
        IdentityAttack::Missing,
        IdentityAttack::Symlink,
        IdentityAttack::Hardlink,
        IdentityAttack::Mode,
    ];
    for attack in attacks {
        let temp = TempDir::new().expect("temp dir");
        let owner = agent_id(95);
        let (store, _, _) = seeded(&temp, &owner).await;
        let anchor = store.recovery_anchor().await.expect("current witness");
        let database = store.path().to_path_buf();
        let root = database.parent().expect("cognitive root").to_path_buf();
        store.pool.close().await;
        drop(store);
        install_identity_attack(&database, attack);
        let attacked = capture_recovery_tree(&root);
        let authority = recovery_authority(&owner);

        let failure = recovery_failure(
            CognitiveStore::open_with_recovery(
                &layout(&temp, &owner),
                CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
                &authority,
                &RecoveryVerifier,
            )
            .await,
        );
        assert!(matches!(failure, CognitiveRecoveryError::Indeterminate(_)));
        assert_eq!(capture_recovery_tree(&root), attacked);
    }
}

#[cfg(unix)]
#[tokio::test]
async fn byte_identical_rename_replacement_can_recover_only_with_current_witness() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(195);
    let (store, _, _) = seeded(&temp, &owner).await;
    let anchor = store.recovery_anchor().await.expect("current witness");
    let database = store.path().to_path_buf();
    store.pool.close().await;
    drop(store);

    let retained = database.with_extension("retained");
    std::fs::rename(&database, &retained).expect("retain original database");
    std::fs::copy(&retained, &database).expect("install byte-identical replacement");
    std::fs::set_permissions(&database, std::fs::Permissions::from_mode(0o600))
        .expect("protect replacement");

    let authority = recovery_authority(&owner);
    let recovered = CognitiveStore::open_with_recovery(
        &layout(&temp, &owner),
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        &authority,
        &RecoveryVerifier,
    )
    .await
    .expect("content-authenticated descriptor recovery");
    assert_eq!(
        recovered.recovery_anchor().await.expect("recovered anchor"),
        anchor
    );
}

#[tokio::test]
async fn recovery_bounds_large_rows_before_loading_payloads_and_rejects_unknown_tables() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(96);
    let (store, _, _) = seeded(&temp, &owner).await;
    let oversized_text = "x".repeat((MAX_ROW_BYTES + 1) as usize);
    sqlx::query("UPDATE _sqlx_migrations SET description = ? WHERE version = 1")
        .bind(oversized_text)
        .execute(&store.pool)
        .await
        .expect("oversized metadata fault");
    let oversized = store.recovery_anchor().await;
    assert!(
        matches!(
            &oversized,
            Err(CognitiveStoreError::Invalid(message)) if message.contains("exceeds bounds")
        ),
        "unexpected oversized-row result: {oversized:?}"
    );

    let clean_temp = TempDir::new().expect("clean temp dir");
    let (clean, _, _) = seeded(&clean_temp, &agent_id(97)).await;
    sqlx::query("CREATE TABLE unregistered_owner_state (value TEXT)")
        .execute(&clean.pool)
        .await
        .expect("unknown table fault");
    assert!(matches!(
        clean.recovery_anchor().await,
        Err(CognitiveStoreError::Corrupt(message)) if message.contains("unregistered")
    ));
}

#[tokio::test]
async fn corrupt_physical_fts_cannot_obtain_a_witness_or_trigger_recovery_io() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(98);
    let (store, _, _) = seeded(&temp, &owner).await;
    let anchor = store
        .recovery_anchor()
        .await
        .expect("trusted current witness");
    let damaged =
        sqlx::query("UPDATE memory_fts_data SET block = zeroblob(length(block)) WHERE id > 10")
            .execute(&store.pool)
            .await
            .expect("inject physical FTS segment damage");
    assert!(damaged.rows_affected() > 0);
    assert!(store.recovery_anchor().await.is_err());
    let database = store.path().to_path_buf();
    store.pool.close().await;
    drop(store);
    let before = std::fs::read(&database).expect("read damaged source");
    let authority = recovery_authority(&owner);
    let failure = recovery_failure(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
            &authority,
            &RecoveryVerifier,
        )
        .await,
    );
    assert!(matches!(failure, CognitiveRecoveryError::Indeterminate(_)));
    assert_eq!(
        std::fs::read(&database).expect("re-read damaged source"),
        before
    );
}

fn recovery_failure(
    result: Result<CognitiveStore, CognitiveRecoveryError>,
) -> CognitiveRecoveryError {
    match result {
        Err(error) => error,
        Ok(_) => panic!("fail-closed recovery unexpectedly returned a store"),
    }
}

#[cfg(unix)]
fn install_identity_attack(database: &Path, attack: IdentityAttack) {
    match attack {
        IdentityAttack::Missing => {
            std::fs::remove_file(database).expect("remove database");
        }
        IdentityAttack::Symlink => {
            let retained = database.with_extension("retained");
            std::fs::rename(database, &retained).expect("retain symlink target");
            symlink(retained.file_name().expect("retained file name"), database)
                .expect("install database symlink");
        }
        IdentityAttack::Hardlink => {
            std::fs::hard_link(database, database.with_extension("hardlink"))
                .expect("install second database link");
        }
        IdentityAttack::Mode => {
            std::fs::set_permissions(database, std::fs::Permissions::from_mode(0o640))
                .expect("widen database mode");
        }
    }
}

fn capture_recovery_tree(root: &Path) -> RecoveryTreeImage {
    let directory = MetadataImage::capture(&std::fs::symlink_metadata(root).expect("stat root"));
    let mut entries = BTreeMap::new();
    for entry in std::fs::read_dir(root).expect("read cognitive root") {
        let entry = entry.expect("read cognitive entry");
        let path = entry.path();
        let metadata = std::fs::symlink_metadata(&path).expect("stat cognitive entry");
        let payload = if metadata.file_type().is_symlink() {
            EntryPayload::Symlink(std::fs::read_link(&path).expect("read symlink"))
        } else {
            EntryPayload::Bytes(std::fs::read(&path).expect("read cognitive bytes"))
        };
        entries.insert(
            entry.file_name(),
            EntryImage {
                metadata: MetadataImage::capture(&metadata),
                payload,
            },
        );
    }
    RecoveryTreeImage { directory, entries }
}

impl MetadataImage {
    fn capture(metadata: &std::fs::Metadata) -> Self {
        Self {
            length: metadata.len(),
            readonly: metadata.permissions().readonly(),
            modified: metadata.modified().ok(),
            #[cfg(unix)]
            device: metadata.dev(),
            #[cfg(unix)]
            inode: metadata.ino(),
            #[cfg(unix)]
            mode: metadata.mode(),
            #[cfg(unix)]
            links: metadata.nlink(),
            #[cfg(unix)]
            modified_seconds: metadata.mtime(),
            #[cfg(unix)]
            modified_nanoseconds: metadata.mtime_nsec(),
            #[cfg(unix)]
            changed_seconds: metadata.ctime(),
            #[cfg(unix)]
            changed_nanoseconds: metadata.ctime_nsec(),
        }
    }
}

#[tokio::test]
async fn federation_follows_recovered_owner_generation_and_revocation() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(93);
    let consumer = agent_id(94);
    let owner_layout = layout(&temp, &owner);
    let (store, owner_access, _) = seeded(&temp, &owner).await;
    let consumer_workspace = Sha256Digest::for_bytes(b"recovered-federation-consumer");
    let capability = store
        .grant_federated_recall(
            &owner_access,
            &crate::FederationGrantRequest {
                consumer_agent_id: consumer.clone(),
                scope: crate::FederationGrantScope::new(
                    CognitiveScope::AgentPrivate,
                    consumer_workspace.clone(),
                ),
                effective_at_unix_seconds: 100,
                expires_at_unix_seconds: 1_000,
            },
        )
        .await
        .expect("grant before recovery");
    let old_reader = crate::FederatedMemoryReader::discover(&owner_layout, &consumer, 150)
        .await
        .expect("pre-recovery discovery")
        .pop()
        .expect("pre-recovery reader");
    let consumer_access =
        crate::FederationConsumerAccess::new(consumer.clone(), consumer_workspace.clone());
    let prepared = old_reader
        .retrieve(
            &consumer_access,
            &crate::RetrievalRequest::new("remembered fact", 150),
        )
        .await
        .expect("pre-recovery federated read")
        .candidates
        .pop()
        .expect("pre-recovery candidate")
        .revalidation;
    let retained = store.recovery_anchor().await.expect("retained current cut");
    let predecessor_path = store.path().to_path_buf();
    store.pool.close().await;
    drop(store);

    let authority = recovery_authority(&owner);
    let recovered = CognitiveStore::open_with_recovery(
        &owner_layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&retained),
        &authority,
        &RecoveryVerifier,
    )
    .await
    .expect("recover current owner generation");
    assert_ne!(recovered.path(), predecessor_path.as_path());
    assert_eq!(
        old_reader
            .revalidate(&consumer_access, &prepared, 150)
            .await
            .expect("old reader revalidation"),
        crate::FederatedRevalidationStatus::Stale(
            crate::FederationRevalidationDrift::OwnerGeneration
        )
    );

    let current_reader = crate::FederatedMemoryReader::discover(&owner_layout, &consumer, 150)
        .await
        .expect("current recovered discovery")
        .pop()
        .expect("grant survives exact recovery");
    assert_ne!(
        current_reader.owner_generation_sha256(),
        old_reader.owner_generation_sha256()
    );
    recovered
        .revoke_federated_recall(&owner_access, &capability, 151)
        .await
        .expect("revoke in recovered generation");
    assert!(
        crate::FederatedMemoryReader::discover(&owner_layout, &consumer, 152)
            .await
            .expect("post-revoke discovery")
            .is_empty()
    );
    assert_eq!(
        current_reader
            .revalidate(&consumer_access, &prepared, 152)
            .await
            .expect("pre-recovery binding against current reader"),
        crate::FederatedRevalidationStatus::Stale(
            crate::FederationRevalidationDrift::OwnerGeneration
        )
    );

    let consumer_store = CognitiveStore::open(&layout(&temp, &consumer))
        .await
        .expect("consumer store");
    let runtime = crate::CognitiveRuntime::from_open_result(Ok(consumer_store))
        .with_federation_sources(consumer.clone(), vec![owner_layout]);
    let (batch, coverage) = runtime
        .retrieve_product_federated(
            &consumer_access,
            &crate::RetrievalRequest::new("remembered fact", 152),
        )
        .await
        .expect("post-revoke product retrieval");
    assert!(batch.candidates.is_empty());
    assert_eq!(coverage.requested_peers, 0);
    assert_eq!(coverage.completed_peers, 0);
    assert_eq!(coverage.failed_peers, 0);
}

#[tokio::test]
async fn recovered_owner_revision_and_forgetting_invalidate_federated_evidence() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(95);
    let consumer = agent_id(96);
    let owner_layout = layout(&temp, &owner);
    let (store, owner_access, memory) = seeded(&temp, &owner).await;
    let consumer_workspace = Sha256Digest::for_bytes(b"recovered-revision-consumer");
    store
        .grant_federated_recall(
            &owner_access,
            &crate::FederationGrantRequest {
                consumer_agent_id: consumer.clone(),
                scope: crate::FederationGrantScope::new(
                    CognitiveScope::AgentPrivate,
                    consumer_workspace.clone(),
                ),
                effective_at_unix_seconds: 100,
                expires_at_unix_seconds: 1_000,
            },
        )
        .await
        .expect("grant before recovery");
    let retained = store.recovery_anchor().await.expect("retained current cut");
    store.pool.close().await;
    drop(store);

    let recovered = CognitiveStore::open_with_recovery(
        &owner_layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&retained),
        &recovery_authority(&owner),
        &RecoveryVerifier,
    )
    .await
    .expect("recover current owner generation");
    let consumer_access =
        crate::FederationConsumerAccess::new(consumer.clone(), consumer_workspace);
    let reader = crate::FederatedMemoryReader::discover(&owner_layout, &consumer, 150)
        .await
        .expect("recovered discovery")
        .pop()
        .expect("recovered reader");
    let original_binding = reader
        .retrieve(
            &consumer_access,
            &crate::RetrievalRequest::new("remembered fact", 150),
        )
        .await
        .expect("original recovered read")
        .candidates
        .pop()
        .expect("original recovered candidate")
        .revalidation;

    let corrected = recovered
        .correct_memory(
            &owner_access,
            &memory.id.memory_id,
            memory.id.revision,
            &MemoryRevisionDraft {
                scope: CognitiveScope::AgentPrivate,
                content: "revised recovered federation fact".to_string(),
                verification: MemoryVerification::Verified,
                lifecycle: MemoryLifecycleState::Active,
                valid_from_unix_seconds: 200,
                valid_to_unix_seconds: None,
                citations: memory.citations.clone(),
            },
        )
        .await
        .expect("revise in recovered generation");
    assert_eq!(
        reader
            .revalidate(&consumer_access, &original_binding, 201)
            .await
            .expect("original binding revalidation"),
        crate::FederatedRevalidationStatus::Stale(crate::FederationRevalidationDrift::Memory)
    );
    // Token/rank matching can legitimately return the corrected record for
    // the previous query (both contain "fact"). It must never return the old
    // revision or content, even though the old database is still retained.
    let old_query_result = reader
        .retrieve(
            &consumer_access,
            &crate::RetrievalRequest::new("remembered fact", 201),
        )
        .await
        .expect("old query after correction");
    assert!(old_query_result.candidates.iter().all(|candidate| {
        candidate.candidate.memory.id.revision == corrected.id.revision
            && candidate.candidate.memory.content == corrected.content
            && candidate.candidate.memory.content != memory.content
    }));
    let corrected_binding = reader
        .retrieve(
            &consumer_access,
            &crate::RetrievalRequest::new("revised recovered federation", 201),
        )
        .await
        .expect("corrected read")
        .candidates
        .pop()
        .expect("corrected candidate")
        .revalidation;
    assert_eq!(
        corrected_binding.memory.memory.revision,
        corrected.id.revision
    );

    recovered
        .forget_memory(
            &owner_access,
            &corrected.id.memory_id,
            corrected.id.revision,
            &ForgetMemoryDraft {
                scope: CognitiveScope::AgentPrivate,
                reason: "withdraw recovered federation evidence".to_string(),
                valid_from_unix_seconds: 300,
                citations: corrected.citations.clone(),
            },
        )
        .await
        .expect("forget in recovered generation");
    assert!(
        reader
            .retrieve(
                &consumer_access,
                &crate::RetrievalRequest::new("revised recovered federation", 301),
            )
            .await
            .expect("read after forgetting")
            .candidates
            .is_empty()
    );
    assert_eq!(
        reader
            .revalidate(&consumer_access, &corrected_binding, 301)
            .await
            .expect("forgotten binding revalidation"),
        crate::FederatedRevalidationStatus::Stale(crate::FederationRevalidationDrift::Memory)
    );
}

#[tokio::test]
async fn active_federation_read_fence_blocks_recovery_until_released() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(197);
    let owner_layout = layout(&temp, &owner);
    let (store, _, _) = seeded(&temp, &owner).await;
    let retained = store.recovery_anchor().await.expect("current cut");
    let previous = store.path().to_path_buf();
    let read_generation = CognitiveStore::bind_current_read_generation(&owner_layout)
        .expect("bounded active read fence");
    store.pool.close().await;
    drop(store);
    let authority = recovery_authority(&owner);
    assert!(matches!(
        CognitiveStore::open_with_recovery(
            &owner_layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&retained),
            &authority,
            &RecoveryVerifier,
        )
        .await,
        Err(CognitiveRecoveryError::Unavailable(_))
    ));
    assert_eq!(
        resolve_active_database_path(owner_layout.cognitive_root()).expect("unmoved pointer"),
        previous
    );
    drop(read_generation);
    let recovered = CognitiveStore::open_with_recovery(
        &owner_layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&retained),
        &authority,
        &RecoveryVerifier,
    )
    .await
    .expect("recovery after reader released");
    assert_ne!(recovered.path(), previous);
    assert_eq!(
        CognitiveStore::bind_current_read_generation(&owner_layout)
            .expect("reader coexists with recovered writer")
            .database_path(),
        recovered.path()
    );
}

#[tokio::test]
async fn missing_federation_generation_fence_never_reopens_legacy_path() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(198);
    let owner_layout = layout(&temp, &owner);
    let (store, _, _) = seeded(&temp, &owner).await;
    store.pool.close().await;
    drop(store);
    let fence = owner_layout
        .cognitive_root()
        .join(".cognitive-generation.lock");
    std::fs::remove_file(&fence).expect("missing fence injection");
    assert!(
        crate::FederatedMemoryReader::discover(&owner_layout, &agent_id(199), 150)
            .await
            .is_err()
    );
    assert!(
        !fence.exists(),
        "read-only discovery must not create a missing fence"
    );
}
