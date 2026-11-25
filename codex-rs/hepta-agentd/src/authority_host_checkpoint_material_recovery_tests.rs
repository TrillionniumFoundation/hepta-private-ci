//! Original Root image and actual process lifetimes; no deployed effect owner.

use super::*;
use codex_hepta_memory::RootCognitiveMaterialRegistration;
use codex_hepta_memory::VerifiedCognitiveMaterial;
use pretty_assertions::assert_eq;

async fn material(f: &Fixture) -> VerifiedCognitiveMaterial {
    let source = HeptaFleetRoot::parse(f._temp.path().join("fleet")).unwrap()
        .layout().agent(&f.previous.head.owner_agent_id);
    for entry in std::fs::read_dir(source.cognitive_root()).unwrap() {
        let path = entry.unwrap().path();
        if path.is_file() {
            std::os::unix::fs::chown(&path, Some(60001), Some(60001)).unwrap();
        }
    }
    std::os::unix::fs::chown(source.cognitive_root(), Some(60001), Some(60001)).unwrap();
    let image = HeptaFleetRoot::parse(f._temp.path().join("retained-image")).unwrap()
        .layout().agent(&f.previous.head.owner_agent_id);
    std::fs::create_dir_all(image.cognitive_root()).unwrap();
    std::fs::set_permissions(image.cognitive_root(), std::fs::Permissions::from_mode(0o700)).unwrap();
    RootCognitiveMaterialRegistration::bind_registered_layout(&source, 60001).unwrap()
        .materialize_private_candidate(&image).unwrap();
    CognitiveStore::verify_root_material_candidate(&image, &f.previous.head.last_current)
        .await.unwrap()
}

fn recover(
    f: &Fixture,
    material: &VerifiedCognitiveMaterial,
) -> Result<HostCognitiveCheckpoint, AuthorityTrustError> {
    let retired = RetiredCheckpointPublisher::observe(f.old.retained.lifetime.clone())?;
    HostCognitiveCheckpoint::adopt_retained_material_after_root_restart(
        f.directory.clone(), &f.previous, &retired, f.registration.clone(),
        &f.new.retained, f.clock.clone(), material,
    )
}

#[tokio::test]
#[ignore = "actual Root image/counter/pidfd recovery qualification"]
async fn root_material_recovery_promotes_only_retained_cut_after_actual_retirement() {
    for phase in [CognitiveCheckpointPhase::Dirty, CognitiveCheckpointPhase::Publishing, CognitiveCheckpointPhase::Fenced] {
        let mut f = Fixture::new().await;
        let image = material(&f).await;
        let original_cut = f.previous.head.last_current.clone();
        f.mutate(CognitiveCheckpointCommand::BeginWrites, 2);
        if phase == CognitiveCheckpointPhase::Publishing {
            f.mutate(CognitiveCheckpointCommand::PreparePublication, 3);
        } else if phase == CognitiveCheckpointPhase::Fenced {
            f.mutate(CognitiveCheckpointCommand::FencePublisher, 3);
        }
        assert_eq!(f.previous.head.phase, phase);
        assert_eq!(recover(&f, &image).err(), Some(AuthorityTrustError::Conflict));
        assert_eq!(f.backend.load().unwrap(), f.previous.head);
        f.old.stop();
        // The old API remains strict even after actual retirement.
        assert_eq!(f.adopt().err(), Some(AuthorityTrustError::Invalid));
        let recovered = recover(&f, &image).unwrap();
        let head = recovered.load().unwrap();
        let mut expected = f.previous.head.clone();
        expected.counter += 1;
        expected.publisher_epoch = f.registration.publisher_epoch;
        expected.writer_binding = f.registration.writer_binding.clone();
        expected.peer_lifetime = f.registration.peer_lifetime.clone();
        expected.phase = CognitiveCheckpointPhase::Current;
        expected.proposal = None;
        expected.last_mutation_sequence = 0;
        expected.last_request = None;
        assert_eq!(head, expected);
        assert_eq!(head.last_current, original_cut);
        image.verify_unchanged().unwrap();
        assert!(f.backend.load().is_err());
        assert_eq!(recover(&f, &image).err(), Some(AuthorityTrustError::Conflict));
        assert_eq!(HostCognitiveCheckpoint::open(f.directory.clone(), f.registration.clone(), f.clock.clone()).unwrap().load().unwrap(), head);
    }
}

#[tokio::test]
#[ignore = "actual Root image/counter/pidfd recovery qualification"]
async fn root_material_recovery_rejects_changed_held_image_without_advancing_head() {
    let mut f = Fixture::new().await;
    let image = material(&f).await;
    f.mutate(CognitiveCheckpointCommand::BeginWrites, 2);
    f.old.stop();
    use std::io::Write;
    std::fs::OpenOptions::new().append(true).open(image.path()).unwrap().write_all(b"changed").unwrap();
    assert_eq!(recover(&f, &image).err(), Some(AuthorityTrustError::Unavailable));
    assert_eq!(f.backend.load().unwrap(), f.previous.head);
}

#[tokio::test]
#[ignore = "actual Root image/counter/pidfd recovery qualification"]
async fn root_material_recovery_rejects_wrong_cut_or_stale_full_predecessor() {
    let mut f = Fixture::new().await;
    let image = material(&f).await;
    f.mutate(CognitiveCheckpointCommand::BeginWrites, 2);
    f.old.stop();
    let original = f.previous.clone();
    f.previous.head.last_current.state_digest = Sha256Digest::for_bytes(b"different retained cut");
    f.previous.token = token_for(&f.previous.head).unwrap();
    assert_eq!(recover(&f, &image).err(), Some(AuthorityTrustError::Invalid));
    f.previous = original.clone();
    // Obtain another valid full protected head through its original protocol.
    // A manually changed counter would be malformed and rejected before CAS,
    // so it cannot exercise the stale-but-valid full-predecessor comparison.
    f.mutate(CognitiveCheckpointCommand::FencePublisher, 3);
    let actual = f.previous.clone();
    f.previous = original;
    assert_eq!(recover(&f, &image).err(), Some(AuthorityTrustError::Conflict));
    assert_eq!(f.backend.load().unwrap(), actual.head);
}

#[tokio::test]
#[ignore = "actual Root image/counter/pidfd recovery qualification"]
async fn root_material_recovery_post_cas_expiry_is_unknown_and_preserves_committed_successor() {
    let mut f = Fixture::new().await;
    let image = material(&f).await;
    f.mutate(CognitiveCheckpointCommand::BeginWrites, 2);
    f.old.stop();
    let prior = f.clock.reads.load(Ordering::SeqCst);
    // The first read admits CAS; the original second post-I/O read expires.
    f.clock.expire_on.store(prior + 2, Ordering::SeqCst);
    assert_eq!(recover(&f, &image).err(), Some(AuthorityTrustError::Unavailable));
    let retained = HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(f.directory.clone(), STORE_OWNER.into()).unwrap()
        .load(STORE_OWNER).unwrap();
    assert_eq!(retained.counter, f.previous.head.counter + 1);
    assert_eq!(retained.publisher_epoch, f.registration.publisher_epoch);
    assert_eq!(retained.phase, CognitiveCheckpointPhase::Current);
    assert_eq!(retained.last_current, f.previous.head.last_current);
    assert_eq!(recover(&f, &image).err(), Some(AuthorityTrustError::Unavailable));
    assert_eq!(HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(f.directory.clone(), STORE_OWNER.into()).unwrap()
        .load(STORE_OWNER).unwrap(), retained);
}
