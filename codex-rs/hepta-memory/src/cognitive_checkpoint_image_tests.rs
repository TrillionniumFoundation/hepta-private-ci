//! Actual original SQLite/image integrity tests under the test user's custody.
//! These establish no Root filesystem, Root publication or native qualification.

use super::*;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::KgFactSetDraft;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;

fn material_directory(temp: &tempfile::TempDir) -> PathBuf {
    let directory = temp.path().join("independent-material");
    std::fs::create_dir(&directory).unwrap();
    std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).unwrap();
    directory
}

#[tokio::test]
async fn live_image_retains_the_original_cut_after_the_live_database_is_removed() {
    let temp = tempfile::TempDir::new().unwrap();
    let registered = layout(&temp, &agent_id(231));
    let store = CognitiveStore::open(&registered).await.unwrap();
    let expected = store.recovery_anchor().await.unwrap();
    let original_path = store.path().to_path_buf();
    let before = std::fs::read(&original_path).unwrap();
    let barrier = store.begin_checkpoint_barrier().await.unwrap();
    let destination = material_directory(&temp).join("original.sqlite");
    let image = CognitiveStore::capture_live_checkpoint_image(
        &registered,
        std::fs::metadata(&original_path).unwrap().uid(),
        &expected,
        &destination,
    )
    .await
    .unwrap();
    assert_eq!(image.cut(), &expected);
    assert_eq!(std::fs::read(&original_path).unwrap(), before);
    assert_eq!(image.path(), destination);
    assert!(image.bytes() > 0);
    barrier.rollback().await.unwrap();
    store.close().await;
    std::fs::rename(&original_path, original_path.with_extension("quarantined")).unwrap();
    let checked =
        CognitiveStore::verify_retained_checkpoint_image(&destination, &expected, image.sha256())
            .await
            .unwrap();
    assert_eq!(
        (checked.cut(), checked.sha256(), checked.bytes()),
        (image.cut(), image.sha256(), image.bytes())
    );
    assert!(!original_path.exists());
}

#[tokio::test]
async fn stale_cut_is_rejected_after_an_actual_original_owner_memory_mutation() {
    let temp = tempfile::TempDir::new().unwrap();
    let owner = agent_id(232);
    let registered = layout(&temp, &owner);
    let store = CognitiveStore::open(&registered).await.unwrap();
    let stale = store.recovery_anchor().await.unwrap();
    store
        .remember_with_kg(
            &CognitiveAccess::agent_private(owner),
            &source(
                CognitiveScope::AgentPrivate,
                "material-source",
                "new original fact",
            ),
            &MemoryDraft {
                stable_key: "material-memory".into(),
                revision: MemoryRevisionDraft {
                    scope: CognitiveScope::AgentPrivate,
                    content: "new original fact".into(),
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
        .unwrap();
    let current = store.recovery_anchor().await.unwrap();
    assert_ne!(current, stale);
    let barrier = store.begin_checkpoint_barrier().await.unwrap();
    let destination = material_directory(&temp).join("stale.sqlite");
    assert!(
        CognitiveStore::capture_live_checkpoint_image(
            &registered,
            std::fs::metadata(store.path()).unwrap().uid(),
            &stale,
            &destination,
        )
        .await
        .is_err()
    );
    barrier.rollback().await.unwrap();
    assert_eq!(store.recovery_anchor().await.unwrap(), current);
    store.close().await;
}

#[tokio::test]
async fn material_verification_refuses_changed_bytes_without_consulting_live_state() {
    let temp = tempfile::TempDir::new().unwrap();
    let registered = layout(&temp, &agent_id(233));
    let store = CognitiveStore::open(&registered).await.unwrap();
    let expected = store.recovery_anchor().await.unwrap();
    let destination = material_directory(&temp).join("tampered.sqlite");
    let barrier = store.begin_checkpoint_barrier().await.unwrap();
    let image = CognitiveStore::capture_live_checkpoint_image(
        &registered,
        std::fs::metadata(store.path()).unwrap().uid(),
        &expected,
        &destination,
    )
    .await
    .unwrap();
    barrier.rollback().await.unwrap();
    store.close().await;
    OpenOptions::new()
        .write(true)
        .open(&destination)
        .unwrap()
        .set_len(512)
        .unwrap();
    assert!(
        CognitiveStore::verify_retained_checkpoint_image(&destination, &expected, image.sha256(),)
            .await
            .is_err()
    );
    assert_eq!(destination.metadata().unwrap().len(), 512);
}

#[tokio::test]
async fn capture_never_overwrites_an_existing_material_path() {
    let temp = tempfile::TempDir::new().unwrap();
    let registered = layout(&temp, &agent_id(234));
    let store = CognitiveStore::open(&registered).await.unwrap();
    let expected = store.recovery_anchor().await.unwrap();
    let destination = material_directory(&temp).join("existing.sqlite");
    std::fs::write(&destination, b"retained prior evidence").unwrap();
    assert!(
        CognitiveStore::capture_live_checkpoint_image(
            &registered,
            std::fs::metadata(store.path()).unwrap().uid(),
            &expected,
            &destination,
        )
        .await
        .is_err()
    );
    assert_eq!(
        std::fs::read(&destination).unwrap(),
        b"retained prior evidence"
    );
    assert_eq!(store.recovery_anchor().await.unwrap(), expected);
    store.close().await;
}
