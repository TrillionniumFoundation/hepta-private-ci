//! Root-only component qualification using real SQLite, the original backend
//! and actual dedicated publisher pidfds. Controlled grants/clocks remain test
//! inputs: these cases do not qualify the deployed Root ceremony or native G2.

use super::*;
use crate::authority_host_checkpoint::PreparedMaterialRecovery;
use pretty_assertions::assert_eq;
use std::os::unix::fs::MetadataExt;
use std::path::PathBuf;

impl Fixture {
    fn material_profile(&self) -> RootMaterialProfile {
        RootMaterialProfile {
            layout: HeptaFleetRoot::parse(self._temp.path().join("fleet"))
                .unwrap()
                .layout()
                .agent(&self.previous.head.owner_agent_id),
            root: self._temp.path().join("physical-material"),
            deadline: Duration::from_secs(5),
        }
    }

    fn image(&self) -> PathBuf {
        let files: Vec<_> = std::fs::read_dir(self.material_profile().root)
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .filter(|path| {
                path.file_name()
                    .unwrap()
                    .to_string_lossy()
                    .starts_with("image-")
            })
            .collect();
        assert_eq!(files.len(), 1);
        files[0].clone()
    }

    fn observe_recovery(&self) -> Result<PreparedMaterialRecovery, AuthorityTrustError> {
        PreparedMaterialRecovery::observe(
            self.directory.clone(),
            self.material_profile(),
            self.registration.clone(),
            self.clock.clone(),
        )
    }

    fn retire_for_material_recovery(&mut self) {
        self.old.stop();
        self.registration.writer_binding.expires_at_unix_seconds = 20;
        self.clock.expire_on.store(1, Ordering::SeqCst);
    }
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn physical_current_survives_live_source_loss_and_refuses_corrupt_retained_image() {
    let f = Fixture::with_material(FixtureMaterial::Physical).await;
    let current = f.backend.current_for_handoff().unwrap();
    let image = f.image();
    let metadata = image.metadata().unwrap();
    assert_eq!(
        (metadata.uid(), metadata.mode() & 0o7777, metadata.nlink()),
        (0, 0o600, 1)
    );
    let live = f
        .material_profile()
        .layout
        .cognitive_root()
        .join("cognitive_1.sqlite3");
    std::fs::rename(&live, live.with_extension("retained-suspect")).unwrap();
    assert_eq!(f.backend.current_for_handoff().unwrap(), current);
    std::fs::OpenOptions::new()
        .write(true)
        .open(&image)
        .unwrap()
        .set_len(512)
        .unwrap();
    assert_eq!(
        f.backend.current_for_handoff(),
        Err(AuthorityTrustError::Unavailable)
    );
    assert_eq!(f.backend.load().unwrap(), current);
    assert!(f.backend.closed.load(Ordering::Acquire));
    assert!(!live.exists());
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn physical_recovery_requires_actual_old_exit_and_old_lease_expiry_before_installation() {
    let mut f = Fixture::with_material(FixtureMaterial::Physical).await;
    f.registration.writer_binding.expires_at_unix_seconds = 20;
    assert_eq!(
        f.observe_recovery().err(),
        Some(AuthorityTrustError::Conflict)
    );
    f.old.stop();
    assert_eq!(
        f.observe_recovery().err(),
        Some(AuthorityTrustError::Unavailable)
    );
    assert_eq!(f.backend.load().unwrap(), f.previous.head);
    f.clock.expire_on.store(1, Ordering::SeqCst);
    let bytes = std::fs::read(f.image()).unwrap();
    let root = f.material_profile().layout.cognitive_root().to_path_buf();
    let original = root.join("cognitive_1.sqlite3");
    std::fs::rename(&original, original.with_extension("suspect")).unwrap();
    let (adopted, installed) = f
        .observe_recovery()
        .unwrap()
        .install()
        .unwrap()
        .adopt()
        .unwrap();
    assert_eq!(std::fs::read(installed.path()).unwrap(), bytes);
    let current = adopted.current_for_handoff().unwrap();
    assert_eq!(current.last_current, f.previous.head.last_current);
    assert_eq!(current.counter, f.previous.head.counter + 1);
    assert_eq!(current.peer_lifetime, f.new.retained.lifetime);
    installed
        .release_to_registered_owner(/*uid*/ 60001, /*gid*/ 60001)
        .unwrap();
    assert_eq!(root.metadata().unwrap().uid(), 60001);
    assert_eq!(f.image().metadata().unwrap().uid(), 0);
    assert_eq!(adopted.current_for_handoff().unwrap(), current);
    assert!(!original.exists());
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn adopted_current_before_uid_release_cannot_be_adopted_again_or_reinitialized() {
    let mut f = Fixture::with_material(FixtureMaterial::Physical).await;
    f.retire_for_material_recovery();
    let (adopted, installed) = f
        .observe_recovery()
        .unwrap()
        .install()
        .unwrap()
        .adopt()
        .unwrap();
    let current = adopted.current_for_handoff().unwrap();
    drop(installed); // Controlled boundary: Root has not released the data UID.
    let profile = f.material_profile();
    assert_eq!(profile.layout.cognitive_root().metadata().unwrap().uid(), 0);
    assert_eq!(
        f.observe_recovery().err(),
        Some(AuthorityTrustError::Invalid)
    );
    assert!(
        HostCognitiveCheckpoint::initialize_fresh(
            f.directory.clone(),
            f.registration.clone(),
            current.last_current.clone(),
            f.clock.clone(),
        )
        .is_err()
    );
    assert_eq!(adopted.current_for_handoff().unwrap(), current);
    let retained = adopted.reopen_material_installation().unwrap();
    retained
        .release_to_registered_owner(/*uid*/ 60001, /*gid*/ 60001)
        .unwrap();
    assert_eq!(adopted.current_for_handoff().unwrap(), current);
    assert_eq!(
        f.material_profile()
            .layout
            .cognitive_root()
            .metadata()
            .unwrap()
            .uid(),
        60001
    );
}

#[tokio::test]
#[ignore = "explicit root-owned data-bind qualification"]
async fn physical_material_never_promotes_actual_dirty_current_predecessor() {
    let mut f = Fixture::with_material(FixtureMaterial::Physical).await;
    f.mutate(CognitiveCheckpointCommand::BeginWrites, /*sequence*/ 1);
    let dirty = f.previous.head.clone();
    f.retire_for_material_recovery();
    assert_eq!(
        f.observe_recovery().err(),
        Some(AuthorityTrustError::Invalid)
    );
    assert_eq!(f.backend.load().unwrap(), dirty);
    assert_eq!(
        std::fs::read_dir(f.material_profile().root)
            .unwrap()
            .count(),
        2
    );
}
