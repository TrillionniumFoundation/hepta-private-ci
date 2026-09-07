use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::ffi::OsString;
use std::path::Path;
use std::path::PathBuf;
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

#[tokio::test]
async fn exact_current_cut_is_unavailable_without_file_or_sidecar_mutation() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(91);
    let (store, _, _) = seeded(&temp, &owner).await;
    let anchor = store
        .recovery_anchor()
        .await
        .expect("trusted current witness");
    let serialized = serde_json::to_vec(&anchor).expect("host serializable witness");
    let retained: CognitiveRecoveryAnchor =
        serde_json::from_slice(&serialized).expect("retained witness");
    assert_eq!(retained, anchor);
    let root = store.path().parent().expect("cognitive root").to_path_buf();
    store.pool.close().await;
    let before = capture_recovery_tree(&root);

    for _ in 0..8 {
        let message = recovery_failure_message(
            CognitiveStore::open_with_recovery(
                &layout(&temp, &owner),
                CognitiveRecoveryRequirement::ExactCurrentCut(&retained),
            )
            .await,
        );
        assert!(message.contains("recovery is unavailable"));
        assert_eq!(capture_recovery_tree(&root), before);
    }
}

#[tokio::test]
async fn predecessor_and_current_witnesses_cannot_enable_path_recovery() {
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
    let root = store.path().parent().expect("cognitive root").to_path_buf();
    store.pool.close().await;
    let before = capture_recovery_tree(&root);

    for witness in [&predecessor, &current] {
        let message = recovery_failure_message(
            CognitiveStore::open_with_recovery(
                &layout(&temp, &owner),
                CognitiveRecoveryRequirement::ExactCurrentCut(witness),
            )
            .await,
        );
        assert!(message.contains("recovery is unavailable"));
        assert_eq!(capture_recovery_tree(&root), before);
    }
}

#[tokio::test]
async fn revoked_owner_profile_and_witness_checks_precede_recovery_admission() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(93);
    let (store, _, _) = seeded(&temp, &owner).await;
    let anchor = store.recovery_anchor().await.expect("current witness");
    let root = store.path().parent().expect("cognitive root").to_path_buf();
    store.pool.close().await;
    let before = capture_recovery_tree(&root);

    assert!(matches!(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::Revoked,
        )
        .await,
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));
    assert_eq!(capture_recovery_tree(&root), before);

    let wrong_layout = layout(&temp, &agent_id(94));
    assert!(matches!(
        CognitiveStore::open_with_recovery(
            &wrong_layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        )
        .await,
        Err(CognitiveRecoveryError::AccessDenied(_))
    ));
    assert!(!wrong_layout.cognitive_root().exists());
    assert_eq!(capture_recovery_tree(&root), before);

    let mut unsupported = anchor.clone();
    unsupported.profile = "unsupported".to_string();
    assert!(matches!(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&unsupported),
        )
        .await,
        Err(CognitiveRecoveryError::Invalid(_))
    ));
    assert_eq!(capture_recovery_tree(&root), before);

    let mut tampered = anchor;
    tampered.state_digest = Sha256Digest::for_bytes(b"altered witness");
    let message = recovery_failure_message(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&tampered),
        )
        .await,
    );
    assert!(message.contains("recovery is unavailable"));
    assert_eq!(capture_recovery_tree(&root), before);
}

#[cfg(unix)]
#[derive(Clone, Copy, Debug)]
enum IdentityAttack {
    Missing,
    Symlink,
    Hardlink,
    Mode,
    RenameReplacement,
}

#[cfg(unix)]
#[tokio::test]
async fn hostile_file_identities_fail_closed_without_additional_mutation() {
    let attacks = [
        IdentityAttack::Missing,
        IdentityAttack::Symlink,
        IdentityAttack::Hardlink,
        IdentityAttack::Mode,
        IdentityAttack::RenameReplacement,
    ];
    for attack in attacks {
        let temp = TempDir::new().expect("temp dir");
        let owner = agent_id(95);
        let (store, _, _) = seeded(&temp, &owner).await;
        let anchor = store.recovery_anchor().await.expect("current witness");
        let database = store.path().to_path_buf();
        let root = database.parent().expect("cognitive root").to_path_buf();
        store.pool.close().await;
        install_identity_attack(&database, attack);
        let attacked = capture_recovery_tree(&root);

        let failure = recovery_failure(
            CognitiveStore::open_with_recovery(
                &layout(&temp, &owner),
                CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
            )
            .await,
        );
        match attack {
            IdentityAttack::RenameReplacement => {
                assert!(matches!(failure, CognitiveRecoveryError::Unavailable(_)));
            }
            IdentityAttack::Missing
            | IdentityAttack::Symlink
            | IdentityAttack::Hardlink
            | IdentityAttack::Mode => {
                assert!(matches!(failure, CognitiveRecoveryError::Indeterminate(_)));
            }
        }
        assert_eq!(capture_recovery_tree(&root), attacked);
    }
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
    let root = store.path().parent().expect("cognitive root").to_path_buf();
    store.pool.close().await;
    let before = capture_recovery_tree(&root);
    let message = recovery_failure_message(
        CognitiveStore::open_with_recovery(
            &layout(&temp, &owner),
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        )
        .await,
    );
    assert!(message.contains("recovery is unavailable"));
    assert_eq!(capture_recovery_tree(&root), before);
}

fn recovery_failure(
    result: Result<CognitiveStore, CognitiveRecoveryError>,
) -> CognitiveRecoveryError {
    match result {
        Err(error) => error,
        Ok(_) => panic!("fail-closed recovery unexpectedly returned a store"),
    }
}

fn recovery_failure_message(result: Result<CognitiveStore, CognitiveRecoveryError>) -> String {
    match recovery_failure(result) {
        CognitiveRecoveryError::Unavailable(message) => message,
        error => panic!("fail-closed recovery returned the wrong error class: {error}"),
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
        IdentityAttack::RenameReplacement => {
            let retained = database.with_extension("retained");
            std::fs::rename(database, &retained).expect("retain original database");
            std::fs::copy(&retained, database).expect("install byte-identical replacement");
            std::fs::set_permissions(database, std::fs::Permissions::from_mode(0o600))
                .expect("protect replacement");
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
