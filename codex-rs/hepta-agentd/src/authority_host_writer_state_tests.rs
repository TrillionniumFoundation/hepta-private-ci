//! Observe an actual expired original proof without reviving runtime authority.
use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
#[ignore = "requires isolated actual Root checkpoint directory and UID60001 peers"]
async fn root_retained_writer_observation_survives_actual_expiry_without_authorizing_runtime() {
    let mut fixture = Fixture::new().await;
    fixture.retire_failed_authority();
    let mut registration = fixture.failed_writer.clone();
    registration.spawn_generation += 2;
    registration.owner_epoch += 1;
    registration.local_lease_generation += 1;
    registration.authority_lease.lease_id = "root-read-actual-expiring-writer".into();
    registration.authority_lease.issued_at_unix_ms = fixture.clock.now_unix_ms().unwrap();
    registration.authority_lease.expires_at_unix_ms =
        registration.authority_lease.issued_at_unix_ms + 20_000;
    fixture
        .registry
        .put_lease(
            registration.authority_lease.clone(),
            /*expected_revision*/ 0,
        )
        .unwrap();
    let proof = fixture
        .issuer
        .rotate_writer_authorization(&fixture.failed_writer, &fixture.failed_proof, &registration)
        .unwrap();
    let before = fixture.issuer.retained_writer_state_for_root().unwrap();
    assert_eq!(before.registration, registration);
    assert_eq!(before.proof, proof);
    assert_eq!(
        fixture
            .issuer
            .retained_writer_authorization(&registration)
            .unwrap(),
        proof
    );
    let checkpoint = fixture.actual_head();
    let end = Instant::now() + Duration::from_secs(30);
    loop {
        let actual = fixture.clock.now_unix_ms().unwrap();
        if actual >= registration.authority_lease.expires_at_unix_ms {
            break;
        }
        assert!(
            Instant::now() < end,
            "original real clock did not reach the issued expiry"
        );
        std::thread::sleep(Duration::from_millis(20));
    }
    assert!(
        fixture
            .issuer
            .retained_writer_authorization(&registration)
            .is_err()
    );
    assert!(
        fixture
            .registry
            .verifier()
            .verify_use(
                &registration.authority_lease.lease_id,
                registration.authority_lease.revision,
                &registration.authority_lease.binding
            )
            .is_err()
    );
    // Every canonical byte/sequence and the checkpoint remain unchanged. The
    // Root observation is usable for deciding a later original transition,
    // while both original live-authorization paths continue to reject it.
    assert_eq!(
        fixture.issuer.retained_writer_state_for_root().unwrap(),
        before
    );
    assert_eq!(fixture.actual_head(), checkpoint);
    fixture.material.verify_unchanged().unwrap();
}
