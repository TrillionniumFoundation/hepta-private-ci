use super::*;
use crate::CognitiveAccess;
use crate::CognitiveRecoveryRequirement;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;
use tempfile::TempDir;

async fn close(store: &CognitiveStore) {
    store.pool.close().await;
}

#[tokio::test]
async fn exact_current_cut_recovery_promotes_and_reopens_writable_store() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(231);
    let layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&layout).await.expect("open store");
    let anchor = store.recovery_anchor().await.expect("current cut");
    close(&store).await;

    let recovered = CognitiveStore::open_replayed_recovery(
        &layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
    )
    .await
    .expect("exact current cut must recover");
    assert_eq!(
        recovered.recovery_anchor().await.expect("reopened cut"),
        anchor
    );
}

#[tokio::test]
async fn stale_cut_is_rejected_without_replacing_newer_source() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(232);
    let layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&layout).await.expect("open store");
    let stale = store.recovery_anchor().await.expect("old cut");
    let access = CognitiveAccess::agent_private(owner.clone());
    store
        .append_source(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "recovery-newer-source",
                "newer independently visible state",
            ),
        )
        .await
        .expect("advance owner state");
    let current = store.recovery_anchor().await.expect("new cut");
    assert_ne!(stale, current);
    close(&store).await;

    let error = CognitiveStore::open_replayed_recovery(
        &layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&stale),
    )
    .await
    .expect_err("stale cut must fail closed");
    assert!(matches!(error, CognitiveRecoveryError::AccessDenied(_)));

    let reopened = CognitiveStore::open(&layout).await.expect("source remains usable");
    assert_eq!(
        reopened.recovery_anchor().await.expect("source cut"),
        current
    );
}

#[tokio::test]
async fn live_authority_lock_blocks_recovery_promotion() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(233);
    let layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&layout).await.expect("open store");
    let anchor = store.recovery_anchor().await.expect("cut");
    close(&store).await;
    let lock = acquire_authority_lock(layout.cognitive_root()).expect("authority lock");

    let error = CognitiveStore::open_replayed_recovery(
        &layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
    )
    .await
    .expect_err("recovery must not race a live authority");
    assert!(matches!(error, CognitiveRecoveryError::Unavailable(_)));
    drop(lock);
}
