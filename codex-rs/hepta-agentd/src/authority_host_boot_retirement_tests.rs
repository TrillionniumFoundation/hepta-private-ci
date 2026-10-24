//! Actual local negative gate; positive retirement requires a real new boot.
use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
#[ignore = "requires isolated actual Root checkpoint directory and UID60001 peers"]
async fn root_previous_boot_observation_refuses_same_boot_after_actual_process_death() {
    let mut fixture = Fixture::new().await;
    fixture.retire_failed_authority();
    let before = fixture.actual_head();
    let proof = fixture
        .issuer
        .retained_writer_authorization(&fixture.failed_writer)
        .unwrap();
    // Both earlier processes really exited and the failed authority really
    // retired. None of these facts is a different kernel boot.
    let result = crate::HostCognitiveCheckpoint::observe_previous_boot_for_root(
        fixture.directory.clone(),
        &fixture.clock,
        &fixture.material,
    );
    assert_eq!(result.err(), Some(AuthorityTrustError::Conflict));
    assert_eq!(
        fixture
            .old
            .retired()
            .prior_boot_root_for_namespace(&fixture.previous)
            .err(),
        Some(AuthorityTrustError::Invalid),
        "actual same-boot death does not admit a new-boot CPU policy"
    );
    assert_eq!(fixture.actual_head(), before);
    assert_eq!(
        fixture
            .issuer
            .retained_writer_authorization(&fixture.failed_writer)
            .unwrap(),
        proof
    );
    fixture.material.verify_unchanged().unwrap();
    // The independent original same-boot replacement still works. The failed
    // prior-boot observation did not reserve a proof or alter a generation.
    let replacement = fixture.replace().unwrap();
    assert_eq!(replacement.claims.sequence, proof.claims.sequence + 1);
    assert_eq!(
        replacement.claims.local_lease_generation,
        proof.claims.local_lease_generation
    );
}
