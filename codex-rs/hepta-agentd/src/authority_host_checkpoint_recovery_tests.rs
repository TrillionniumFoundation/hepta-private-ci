//! Original Root-directory/pidfd fixture; its writer proof and clock are still
//! explicit test inputs, not production Notes or cross-boot qualification.
use super::*;
use crate::authority_host_checkpoint::RetiredCurrentRecovery;
use pretty_assertions::assert_eq;

fn capture(f: &Fixture) -> Result<RetiredCurrentRecovery, AuthorityTrustError> {
    RetiredCurrentRecovery::capture(
        f.directory.clone(),
        f.previous.clone(),
        f.backend.registration.clone(),
        f.clock.clone(),
    )
}

async fn retired() -> Fixture {
    let mut f = Fixture::new().await;
    f.old.stop();
    f.clock.expire_on.store(1, Ordering::SeqCst);
    f.registration.writer_binding.expires_at_unix_seconds = 20;
    f
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_notes_recovery_rejects_unexpired_or_live_predecessor_without_mutation() {
    let mut unexpired = Fixture::new().await;
    unexpired.old.stop();
    assert!(matches!(
        capture(&unexpired),
        Err(AuthorityTrustError::Invalid)
    ));
    assert_eq!(unexpired.backend.load().unwrap(), unexpired.previous.head);

    let live = Fixture::new().await;
    live.clock.expire_on.store(1, Ordering::SeqCst);
    assert!(matches!(capture(&live), Err(AuthorityTrustError::Conflict)));
    assert_eq!(live.backend.load().unwrap(), live.previous.head);
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_notes_recovery_requires_exact_protected_current_before_capture() {
    let mut f = retired().await;
    let retained = f.previous.clone();
    f.previous.token.counter += 1;
    assert!(matches!(capture(&f), Err(AuthorityTrustError::Invalid)));
    f.previous = retained;
    let recovery = capture(&f).unwrap();
    let mut wrong = f.registration.clone();
    wrong.peer_lifetime.boot_id = "different-boot".into();
    assert!(matches!(
        recovery.adopt_or_reconcile(wrong, &f.new.retained),
        Err(AuthorityTrustError::Invalid)
    ));
    assert_eq!(f.backend.load().unwrap(), f.previous.head);
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_notes_recovery_exact_retry_reads_same_successor_without_new_counter() {
    let f = retired().await;
    let recovery = capture(&f).unwrap();
    let first = recovery
        .adopt_or_reconcile(f.registration.clone(), &f.new.retained)
        .unwrap();
    let head = first.current_for_handoff().unwrap();
    let second = recovery
        .adopt_or_reconcile(f.registration.clone(), &f.new.retained)
        .unwrap();
    assert_eq!(second.current_for_handoff().unwrap(), head);
    assert_eq!(head.last_current, f.previous.head.last_current);
    assert_eq!(head.counter, f.previous.head.counter + 1);
    // Losing the typed admission does not let successor JSON recreate an old
    // protected predecessor after the CAS, even if it copies the original cut.
    assert!(capture(&f).is_err());
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_notes_recovery_post_cas_unknown_reconciles_only_same_retained_attempt() {
    let f = retired().await;
    let recovery = capture(&f).unwrap();
    let reads = f.clock.reads.load(Ordering::SeqCst);
    f.clock.reject_on.store(reads + 3, Ordering::SeqCst);
    assert!(matches!(
        recovery.adopt_or_reconcile(f.registration.clone(), &f.new.retained),
        Err(AuthorityTrustError::Unavailable)
    ));
    f.clock.reject_on.store(0, Ordering::SeqCst);
    let first = recovery
        .adopt_or_reconcile(f.registration.clone(), &f.new.retained)
        .unwrap();
    let actual = first.current_for_handoff().unwrap();
    let mut unrelated = f.registration.clone();
    unrelated.writer_binding.owner_epoch += 1;
    assert!(matches!(
        recovery.adopt_or_reconcile(unrelated, &f.new.retained),
        Err(AuthorityTrustError::Conflict)
    ));
    assert_eq!(first.current_for_handoff().unwrap(), actual);
    assert_eq!(actual.counter, f.previous.head.counter + 1);
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn root_notes_recovery_cannot_reconcile_dirty_or_dead_successor() {
    let mut f = retired().await;
    let recovery = capture(&f).unwrap();
    let next = recovery
        .adopt_or_reconcile(f.registration.clone(), &f.new.retained)
        .unwrap();
    let head = next.current_for_handoff().unwrap();
    let request = CognitiveCheckpointRequest {
        schema_version: 1,
        operation: OPERATION.into(),
        request_id: format!("{:016x}{:016x}", head.publisher_epoch, 1),
        command: CognitiveCheckpointCommand::BeginWrites,
        expected: Some(token_for(&head).unwrap()),
        proposal: None,
    };
    let response: CognitiveCheckpointResponse = serde_json::from_slice(
        &next
            .exchange(&serde_json::to_vec(&request).unwrap())
            .unwrap(),
    )
    .unwrap();
    assert_eq!(response.status, CognitiveCheckpointStatus::Ack);
    let dirty = next.load().unwrap();
    assert!(matches!(
        recovery.adopt_or_reconcile(f.registration.clone(), &f.new.retained),
        Err(AuthorityTrustError::Conflict)
    ));
    f.new.stop();
    assert!(
        recovery
            .adopt_or_reconcile(f.registration.clone(), &f.new.retained)
            .is_err()
    );
    assert_eq!(next.load().unwrap(), dirty);
}
