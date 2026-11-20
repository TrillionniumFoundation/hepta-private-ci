//! Cleanup must finish before failed exclusive initialization releases the owner.

use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn refused_exclusive_bind_closes_pool_before_original_owner_reopens() {
    let fixture = ManagedFixture::new().await;
    let ManagedFixture {
        _temp: temp,
        store,
        writer,
        checkpoint,
        peer,
    } = fixture;
    let owner = crate::cognitive_test_support::agent_id(OWNER);
    let layout = crate::cognitive_test_support::layout(&temp, &owner);
    let cut = store.recovery_anchor().await.unwrap();
    drop(writer);
    drop(checkpoint);
    store.close().await;
    let verifier = TestVerifier::new();
    let grant = authority(&owner, 87);
    let store = crate::CognitiveStore::open_with_recovery(
        &layout,
        crate::CognitiveRecoveryRequirement::ExactCurrentCut(&cut),
        &grant,
        &verifier,
    )
    .await
    .unwrap();
    let pool = store.pool.clone();
    let mut receipt = peer.receipt.lock().unwrap().clone();
    receipt.head.owner_agent_id = AgentId::parse("fe4d9e62-67be-4ca8-bfed-8080d473e6a9").unwrap();
    assert!(
        store
            .bind_protected_checkpoint(peer, receipt, Duration::from_secs(2))
            .await
            .is_err()
    );
    // Retaining a raw pool handle must not prolong background WAL cleanup past
    // release of the original exclusive recovery lock.
    assert!(pool.is_closed());
    let reopened = crate::CognitiveStore::open_with_recovery(
        &layout,
        crate::CognitiveRecoveryRequirement::ExactCurrentCut(&cut),
        &grant,
        &verifier,
    )
    .await
    .unwrap();
    assert_eq!(reopened.recovery_anchor().await.unwrap(), cut);
    reopened.close().await;
}

#[tokio::test]
async fn shared_bind_refusal_does_not_close_the_live_original_owner() {
    let fixture = ManagedFixture::new().await;
    let receipt = fixture.peer.receipt.lock().unwrap().clone();
    assert!(
        fixture
            .store
            .clone()
            .bind_protected_checkpoint(fixture.peer.clone(), receipt, Duration::from_secs(2))
            .await
            .is_err()
    );
    assert!(!fixture.store.pool.is_closed());
    fixture
        .writer
        .admit("after-shared-bind-refusal", "test", "{}")
        .await
        .unwrap();
}
