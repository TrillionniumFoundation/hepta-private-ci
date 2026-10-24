//! Actual protected publication observations; no replacement head is supplied.
use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
#[ignore = "requires isolated actual Root checkpoint directory and UID60001 peers"]
async fn root_retained_checkpoint_observation_tracks_actual_cas_without_activating_a_writer() {
    let fixture = Fixture::new().await;
    let authority = fixture.issuer.retained_writer_state_for_root().unwrap();
    let observed =
        crate::HostCognitiveCheckpoint::retained_head_for_root(fixture.directory.clone()).unwrap();
    assert_eq!(observed, fixture.previous);
    assert_eq!(
        fixture.issuer.retained_writer_state_for_root().unwrap(),
        authority
    );
    // Merely observing the old durable head does not authorize the existing
    // failed writer as its publisher. Adoption must still use the original
    // signed registration, actual retained peer and verified physical image.
    let registration = checkpoint_registration(
        &fixture.issuer,
        &fixture.registry,
        &fixture.failed_writer,
        &fixture.failed_proof,
        fixture.previous.head.publisher_epoch + 1,
        &fixture.failed,
    );
    assert!(
        crate::HostCognitiveCheckpoint::open(
            fixture.directory.clone(),
            registration.clone(),
            fixture.clock.clone(),
        )
        .is_err()
    );
    let adopted = crate::HostCognitiveCheckpoint::adopt_retained_material_after_root_restart(
        fixture.directory.clone(),
        &fixture.previous,
        &fixture.old.retired(),
        registration.clone(),
        &fixture.failed.retained,
        fixture.clock.clone(),
        &fixture.material,
    )
    .unwrap();
    let committed = current(&adopted, registration.publisher_epoch);
    assert_ne!(committed, observed);
    assert_eq!(
        crate::HostCognitiveCheckpoint::retained_head_for_root(fixture.directory.clone(),).unwrap(),
        committed
    );
    assert_eq!(
        fixture.issuer.retained_writer_state_for_root().unwrap(),
        authority
    );
    fixture.material.verify_unchanged().unwrap();
}

#[tokio::test]
#[ignore = "requires isolated actual Root checkpoint directory and UID60001 peers"]
async fn root_retained_checkpoint_observation_refuses_corrupt_original_record_without_repair() {
    let fixture = Fixture::new().await;
    let authority = fixture.issuer.retained_writer_state_for_root().unwrap();
    assert_eq!(
        crate::HostCognitiveCheckpoint::retained_head_for_root(fixture.directory.clone(),).unwrap(),
        fixture.previous
    );
    let records = std::fs::read_dir(fixture._temp.path().join("checkpoint"))
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| {
            path.extension()
                .is_some_and(|extension| extension == "json")
        })
        .collect::<Vec<_>>();
    assert_eq!(records.len(), 1);
    let invalid = b"incomplete actual durable record\n";
    std::fs::write(&records[0], invalid).unwrap();
    std::fs::File::open(&records[0])
        .unwrap()
        .sync_all()
        .unwrap();
    assert!(
        crate::HostCognitiveCheckpoint::retained_head_for_root(fixture.directory.clone(),).is_err()
    );
    assert_eq!(std::fs::read(&records[0]).unwrap(), invalid.to_vec());
    assert_eq!(
        fixture.issuer.retained_writer_state_for_root().unwrap(),
        authority
    );
    fixture.material.verify_unchanged().unwrap();
}
