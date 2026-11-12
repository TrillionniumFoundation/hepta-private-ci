//! Same original issuer-instance metadata concurrency; not Root deployment
//! or ordinary learning qualification.
use super::*;
use pretty_assertions::assert_eq;
use std::sync::mpsc;
use std::time::Duration;

#[test]
fn metadata_keeps_one_actual_proof_and_head_until_same_issuer_revoke_can_commit() {
    let fixture = Fixture::new();
    let proof = fixture
        .issuer
        .register_writer_authorization(&fixture.writer, &fixture.registry.verifier())
        .unwrap();
    let grant = fixture.issuer.issue(&fixture.binding).unwrap().unwrap();
    let before = fixture.issuer.revocations().unwrap();
    let verifier = fixture.registry.verifier();
    let lease = verifier
        .observe_original_lease(&fixture.writer.authority_lease)
        .unwrap();
    let retained = fixture
        .issuer
        .observe_original_writer_state(&fixture.writer)
        .unwrap();
    let (attempt_tx, attempt_rx) = mpsc::channel();
    let (committed_tx, committed_rx) = mpsc::channel();
    std::thread::scope(|scope| {
        let issuer = &fixture.issuer;
        let grant_id = &grant.grant.grant_id;
        let worker = scope.spawn(move || {
            attempt_tx.send(()).unwrap();
            let head = issuer.revoke(grant_id).unwrap();
            committed_tx.send(head.clone()).unwrap();
            head
        });
        attempt_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        assert!(matches!(
            committed_rx.recv_timeout(Duration::from_millis(50)),
            Err(mpsc::RecvTimeoutError::Timeout)
        ));
        assert_eq!(retained.original_writer_proof(), &proof);
        assert_eq!(retained.original_writer_revocations(), &before);
        assert_eq!(fixture.issuer.revocations().unwrap(), before);
        drop(retained);
        lease.finish_original_observation().unwrap();
        let actual = committed_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        assert_eq!(worker.join().unwrap(), actual);
        assert_eq!(actual.authority_epoch, before.authority_epoch);
        assert_eq!(actual.revision, before.revision + 1);
        assert!(actual.revoked_grant_ids.contains(&grant.grant.grant_id));
        let lease = verifier
            .observe_original_lease(&fixture.writer.authority_lease)
            .unwrap();
        let retained = fixture
            .issuer
            .observe_original_writer_state(&fixture.writer)
            .unwrap();
        assert_eq!(retained.original_writer_proof(), &proof);
        assert_eq!(retained.original_writer_revocations(), &actual);
        drop(retained);
        lease.finish_original_observation().unwrap();
    });
}

#[test]
fn original_metadata_refuses_wrong_registration_and_original_clock_expiry_without_a_new_signature()
{
    let fixture = Fixture::new();
    let proof = fixture
        .issuer
        .register_writer_authorization(&fixture.writer, &fixture.registry.verifier())
        .unwrap();
    let sequence = fixture.sequence();
    let before = fixture.issuer.revocations().unwrap();
    let verifier = fixture.registry.verifier();
    let lease = verifier
        .observe_original_lease(&fixture.writer.authority_lease)
        .unwrap();
    let mut wrong = fixture.writer.clone();
    wrong.owner_epoch += 1;
    assert!(
        fixture
            .issuer
            .observe_original_writer_state(&wrong)
            .is_err()
    );
    assert_eq!(fixture.sequence(), sequence);
    assert_eq!(fixture.issuer.revocations().unwrap(), before);
    fixture.clock.expire_on.store(0, Ordering::SeqCst);
    assert!(
        fixture
            .issuer
            .observe_original_writer_state(&fixture.writer)
            .is_err()
    );
    assert_eq!(fixture.sequence(), sequence);
    assert_eq!(
        fixture
            .issuer
            .store
            .load(STATE_OWNER)
            .unwrap()
            .writer_authorization
            .as_ref(),
        Some(&proof)
    );
    lease.finish_original_observation().unwrap();
}
