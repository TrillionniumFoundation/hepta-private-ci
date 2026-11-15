use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use futures::FutureExt;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveRecoveryRequirement;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityToken;
use crate::cognitive_store::CognitiveStoreOpenGuard;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::source;

#[tokio::test]
async fn close_waits_for_sqlite_workers_and_retains_recovery_fence() {
    close_and_recover(false).await;
}

#[tokio::test]
async fn cancelled_close_can_finish_without_releasing_recovery_fence() {
    close_and_recover(true).await;
}

async fn close_and_recover(cancel_first_wait: bool) {
    let temp = TempDir::new().expect("temporary directory");
    let owner = agent_id(163);
    let layout = layout(&temp, &owner);
    let store = CognitiveStore::open(&layout).await.expect("open store");
    let access = CognitiveAccess::agent_private(owner.clone());
    store
        .append_source(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "before-close",
                "retained value",
            ),
        )
        .await
        .expect("persist source before closing");
    let anchor = store.recovery_anchor().await.expect("independent cut");
    let original_path = store.path().to_path_buf();
    let root = original_path.parent().expect("store root");
    let peer = store.clone();
    let connection = store.pool.acquire().await.expect("hold a real connection");

    let mut close = Box::pin(store.close());
    assert!(close.as_mut().now_or_never().is_none());
    assert!(store.pool.is_closed());
    assert!(matches!(
        peer.pool.acquire().await,
        Err(sqlx::Error::PoolClosed)
    ));
    assert!(CognitiveStoreOpenGuard::acquire_exclusive(root).is_err());

    if cancel_first_wait {
        drop(close);
        assert!(store.pool.is_closed());
        assert!(CognitiveStoreOpenGuard::acquire_exclusive(root).is_err());
        close = Box::pin(store.close());
        assert!(close.as_mut().now_or_never().is_none());
    }
    connection.close().await.expect("close held SQLite worker");
    close.await;
    assert_eq!(store.pool.size(), 0);
    assert_eq!(store.pool.num_idle(), 0);
    assert!(CognitiveStoreOpenGuard::acquire_exclusive(root).is_err());
    drop(store);
    assert!(CognitiveStoreOpenGuard::acquire_exclusive(root).is_err());
    peer.close().await;
    drop(peer);

    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"close-recovery-grant"),
        7,
        11,
        u64::MAX,
        ProductionAuthorityToken::from_verified_bytes(b"close-recovery-fence".to_vec())
            .expect("authority token"),
    )
    .expect("verified authority");
    let verifier = |authority: &ProductionAuthorityLease, expected: &AgentId| {
        if &authority.agent_id == expected {
            Ok(())
        } else {
            Err("recovery owner mismatch".to_string())
        }
    };
    let recovered = CognitiveStore::open_with_recovery(
        &layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        &authority,
        &verifier,
    )
    .await
    .expect("recover only after SQLite shutdown and release of all handles");
    assert_ne!(recovered.path(), original_path);
    assert_eq!(
        recovered.recovery_anchor().await.expect("recovered cut"),
        anchor
    );
    recovered
        .append_source(
            &access,
            &source(
                CognitiveScope::AgentPrivate,
                "after-close",
                "new generation",
            ),
        )
        .await
        .expect("recovered generation remains writable");
    assert_ne!(
        recovered.recovery_anchor().await.expect("advanced cut"),
        anchor
    );
    recovered.close().await;
}
