use super::*;
use pretty_assertions::assert_eq;
use std::future::Future;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::task::Poll;

struct CurrentRecoveryVerifier {
    authorized: AtomicBool,
    calls: AtomicUsize,
}

impl crate::ProductionAuthorityVerifier for CurrentRecoveryVerifier {
    fn verify(
        &self,
        authority: &crate::ProductionAuthorityLease,
        expected_agent: &AgentId,
    ) -> Result<(), String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        RecoveryVerifier.verify(authority, expected_agent)?;
        if self.authorized.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err("recovery authority was withdrawn".to_string())
        }
    }
}

#[tokio::test]
async fn authority_withdrawn_during_recovery_await_cannot_publish_generation() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(94);
    let (store, _, _) = seeded(&temp, &owner).await;
    let anchor = store.recovery_anchor().await.expect("current cut");
    let original = store.path().to_path_buf();
    store.pool.close().await;
    drop(store);
    let original_bytes = std::fs::read(&original).expect("original database");
    let authority = recovery_authority(&owner);
    let verifier = CurrentRecoveryVerifier {
        authorized: AtomicBool::new(true),
        calls: AtomicUsize::new(0),
    };
    let owner_layout = layout(&temp, &owner);
    let mut recovery = Box::pin(CognitiveStore::open_with_recovery(
        &owner_layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        &authority,
        &verifier,
    ));
    // Pause the real SQLite recovery future at its first asynchronous wait,
    // after initial admission. No production hooks or artificial sleeps.
    std::future::poll_fn(|cx| match recovery.as_mut().poll(cx) {
        Poll::Pending => Poll::Ready(()),
        Poll::Ready(_) => panic!("recovery did not suspend before publication"),
    })
    .await;
    assert_eq!(verifier.calls.load(Ordering::SeqCst), 1);
    verifier.authorized.store(false, Ordering::SeqCst);

    assert!(matches!(
        recovery_failure(recovery.await),
        CognitiveRecoveryError::AccessDenied(message)
            if message == "recovery authority was withdrawn"
    ));
    assert_eq!(verifier.calls.load(Ordering::SeqCst), 2);
    assert_eq!(
        resolve_active_database_path(owner_layout.cognitive_root()).expect("original active path"),
        original
    );
    assert_eq!(
        std::fs::read(&original).expect("original preserved"),
        original_bytes
    );
    let candidate = owner_layout
        .cognitive_root()
        .join(recovered_database_filename(
            &anchor,
            &authority.fencing_token_digest().expect("original fence"),
        ));
    assert!(!candidate.exists(), "unpublished candidate must be removed");
}

#[tokio::test]
async fn authority_expired_during_recovery_await_cannot_publish_generation() {
    let temp = TempDir::new().expect("temp dir");
    let owner = agent_id(95);
    let (store, _, _) = seeded(&temp, &owner).await;
    let anchor = store.recovery_anchor().await.expect("current cut");
    let original = store.path().to_path_buf();
    store.pool.close().await;
    drop(store);
    let original_bytes = std::fs::read(&original).expect("original database");
    let deadline = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("clock")
        .as_secs()
        + 2;
    let authority = crate::ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"finite-recovery-grant"),
        7,
        11,
        deadline,
        crate::ProductionAuthorityToken::from_verified_bytes(b"finite-recovery-fence".to_vec())
            .expect("token"),
    )
    .expect("finite authority");
    let verifier = CurrentRecoveryVerifier {
        authorized: AtomicBool::new(true),
        calls: AtomicUsize::new(0),
    };
    let owner_layout = layout(&temp, &owner);
    let mut recovery = Box::pin(CognitiveStore::open_with_recovery(
        &owner_layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        &authority,
        &verifier,
    ));
    std::future::poll_fn(|cx| match recovery.as_mut().poll(cx) {
        Poll::Pending => Poll::Ready(()),
        Poll::Ready(_) => panic!("recovery did not suspend before publication"),
    })
    .await;
    assert_eq!(verifier.calls.load(Ordering::SeqCst), 1);
    // Let the original finite lease expire using the real clock. The external
    // verifier still accepts its signature/scope; that cannot renew its TTL.
    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
    assert!(matches!(
        recovery_failure(recovery.await),
        CognitiveRecoveryError::AccessDenied(message)
            if message == format!("production authority lease expired at {deadline}")
    ));
    assert_eq!(verifier.calls.load(Ordering::SeqCst), 2);
    assert_eq!(
        resolve_active_database_path(owner_layout.cognitive_root()).expect("original active path"),
        original
    );
    assert_eq!(
        std::fs::read(&original).expect("original preserved"),
        original_bytes
    );
    let candidate = owner_layout
        .cognitive_root()
        .join(recovered_database_filename(
            &anchor,
            &authority.fencing_token_digest().expect("original fence"),
        ));
    assert!(!candidate.exists(), "expired candidate must be removed");
}
