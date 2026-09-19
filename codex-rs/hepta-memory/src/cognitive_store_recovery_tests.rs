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
