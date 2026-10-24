//! Real original SQLite and whole-pool terminal interlock tests. The existing
//! protocol peer is test-only: these do not qualify Root images or authority.
use super::*;
use crate::LocalLeaseHeadDisposition;
use crate::LocalLeaseState;

async fn assert_terminal(f: &ManagedFixture, disposition: LocalLeaseHeadDisposition) {
    let local = f.store.inspect_local_lease_head(LEASE).await.unwrap();
    assert_eq!(local.disposition, disposition);
    let current = f.peer.receipt.lock().unwrap().head.clone();
    assert_eq!(current.phase, CognitiveCheckpointPhase::Current);
    assert_eq!(current.last_current, f.store.recovery_anchor().await.unwrap());
    assert_eq!(current.proposal, None);
    assert!(!f.writer.checkpoint_fenced());
    assert!(!f.store.commit_gate.commit_allowed());
    assert!(f.writer.verify_current_authority().await.is_err());
    assert!(f.writer.admit("terminal-must-not-enqueue", "no-effect", "{}").await.is_err());
}

#[tokio::test]
async fn managed_release_publishes_exact_terminal_cut_without_reactivating_the_writer() {
    let f = ManagedFixture::new().await;
    let before = f.store.recovery_anchor().await.unwrap();
    let receipt = f.writer.release().await.unwrap();
    assert_eq!(receipt.state, "released");
    let head = f.store.inspect_local_lease_head(LEASE).await.unwrap().head.unwrap();
    assert_eq!(head.state, LocalLeaseState::Released);
    assert_eq!(receipt.lease_head_digest, head.lease_sha256);
    assert_ne!(before, f.store.recovery_anchor().await.unwrap());
    assert_terminal(&f, LocalLeaseHeadDisposition::Released).await;
    let current = f.peer.receipt.lock().unwrap().clone();
    assert!(f.writer.release().await.is_err());
    assert!(f.writer.rollback_lease().await.is_err());
    assert_eq!(*f.peer.receipt.lock().unwrap(), current);
}

#[tokio::test]
async fn managed_rollback_publishes_exact_terminal_cut_and_double_terminal_is_refused() {
    let f = ManagedFixture::new().await;
    let receipt = f.writer.rollback_lease().await.unwrap();
    assert_eq!(receipt.state, "rolled_back");
    assert_terminal(&f, LocalLeaseHeadDisposition::RolledBack).await;
    let current = f.peer.receipt.lock().unwrap().clone();
    assert!(f.writer.rollback_lease().await.is_err());
    assert!(f.writer.release().await.is_err());
    assert_eq!(*f.peer.receipt.lock().unwrap(), current);
}

#[tokio::test]
async fn managed_terminal_missing_original_publication_capability_stays_dirty_and_fenced() {
    let mut f = ManagedFixture::new().await;
    Arc::get_mut(&mut f.writer).unwrap().store.bound_publication = None;
    assert!(matches!(f.writer.release().await, Err(ProductionWriterError::CheckpointFenced)));
    assert_eq!(f.store.inspect_local_lease_head(LEASE).await.unwrap().disposition, LocalLeaseHeadDisposition::Released);
    assert_eq!(f.peer.receipt.lock().unwrap().head.phase, CognitiveCheckpointPhase::Dirty);
    assert!(f.writer.checkpoint_fenced());
    assert!(f.writer.admit("after-missing-publication", "no-effect", "{}").await.is_err());
}

#[tokio::test]
async fn managed_terminal_lost_commit_ack_keeps_terminal_but_never_restores_a_write_gate() {
    let f = ManagedFixture::new().await;
    f.peer.hold_current_reply.store(true, Ordering::SeqCst);
    assert!(matches!(f.writer.release().await, Err(ProductionWriterError::CheckpointFenced)));
    assert_eq!(f.store.inspect_local_lease_head(LEASE).await.unwrap().disposition, LocalLeaseHeadDisposition::Released);
    assert_eq!(f.peer.receipt.lock().unwrap().head.phase, CognitiveCheckpointPhase::Current);
    assert!(f.writer.checkpoint_fenced());
    assert!(!f.store.commit_gate.commit_allowed());
    assert!(f.writer.release().await.is_err());
    assert!(f.writer.admit("after-unknown-terminal", "no-effect", "{}").await.is_err());
}

#[tokio::test]
async fn managed_terminal_post_publication_revocation_is_unknown_without_an_active_handle() {
    let f = ManagedFixture::new().await;
    f.peer.revoke_after_publication.store(true, Ordering::SeqCst);
    assert!(matches!(f.writer.rollback_lease().await, Err(ProductionWriterError::CheckpointFenced)));
    assert_eq!(f.store.inspect_local_lease_head(LEASE).await.unwrap().disposition, LocalLeaseHeadDisposition::RolledBack);
    assert!(f.writer.checkpoint_fenced());
    assert!(!f.store.commit_gate.commit_allowed());
    assert!(f.writer.verify_current_authority().await.is_err());
}

#[tokio::test]
async fn terminal_publication_cannot_cover_a_newer_actual_local_generation() {
    let f = ManagedFixture::new().await;
    // Controlled original local APIs create the real competing head; no
    // production authority is claimed for this test-only direct competitor.
    let old = f.writer.lease.release().await.unwrap();
    f.store.acquire_host_bound_lease_after_head(LEASE, old.clone(),
        f.writer.authority.authority_epoch, f.writer.authority.owner_epoch + 1,
        /*generation*/ 2, "test-only-successor-token", f.writer.authority.lease_expires_at_unix_seconds)
        .await.unwrap();
    let actual = f.store.inspect_local_lease_head(LEASE).await.unwrap();
    assert!(matches!(f.writer.acknowledge_terminal_owner_cut(&old).await,
        Err(ProductionWriterError::CheckpointFenced)));
    assert_eq!(f.store.inspect_local_lease_head(LEASE).await.unwrap(), actual);
    assert_eq!(f.peer.receipt.lock().unwrap().head.phase, CognitiveCheckpointPhase::Dirty);
    assert!(f.writer.checkpoint_fenced());
}
