use std::cell::Cell;
use std::os::unix::fs::symlink;

use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use super::*;
use crate::AgentManifest;
use crate::ResourceBudget;
use crate::WorkspaceBinding;

struct Fixture {
    _temp: tempfile::TempDir,
    registry: FleetRegistry,
    agent: AgentId,
    release: ReleaseId,
    staging: PathBuf,
    manifest_hash: String,
}

impl Fixture {
    fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let temp = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(temp.path().canonicalize()?.join("fleet"))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let workspace = temp.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        registry.register(AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
            ResourceBudget::local_default(),
        )?)?;
        let source = temp.path().join("source");
        std::fs::write(&source, b"original executable bytes")?;
        let release = ReleaseId::parse("candidate")?;
        registry.install_release_bundle(
            release.clone(),
            &source,
            vec!["--original".to_owned()],
            Some(&source),
            Vec::new(),
        )?;
        registry.allow_release(&agent, &release)?;
        let destination = registry.layout().releases_root().join(release.as_str());
        let manifest_hash = sha256_file(&destination.join(RELEASE_MANIFEST_FILE))?;
        // Recreate the installer boundary with an existing exact allowance, so
        // failures cannot hide behind a missing allow marker in reader tests.
        let staging = registry.layout().releases_root().join(".staging-test");
        set_mode(&destination, /*mode*/ 0o755)?;
        std::fs::rename(&destination, &staging)?;
        Ok(Self {
            _temp: temp,
            registry,
            agent,
            release,
            staging,
            manifest_hash,
        })
    }

    fn begin(&self) -> Result<PendingPublication<'_>, FleetRegistryError> {
        PendingPublication::begin(
            self.registry.layout().releases_root(),
            &self.staging,
            &self.release,
        )
    }

    fn assert_quarantined(&self) -> Result<(), Box<dyn std::error::Error>> {
        let registry = FleetRegistry::open_existing(self.registry.layout().fleet_root().clone())?;
        assert!(registry.allow_release(&self.agent, &self.release).is_err());
        assert!(
            registry
                .resolve_release(&self.agent, &self.release)
                .is_err()
        );
        assert!(
            registry
                .resolve_release_binding(&self.agent, &self.release)
                .is_err()
        );
        assert!(registry.allowed_releases(&self.agent).is_err());
        assert!(
            registry
                .install_release(
                    self.release.clone(),
                    &self._temp.path().join("source"),
                    Vec::new(),
                )
                .is_err()
        );
        assert!(
            std::fs::symlink_metadata(pending_install_path(
                registry.layout().releases_root(),
                &self.release,
            ))
            .is_ok()
        );
        Ok(())
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        for path in [
            self.staging.clone(),
            self.registry
                .layout()
                .releases_root()
                .join(self.release.as_str()),
            self.registry.layout().releases_root().join("displaced"),
        ] {
            make_tree_removable(&path);
        }
    }
}

#[test]
fn crashed_publication_stays_quarantined_after_reopen() -> Result<(), Box<dyn std::error::Error>> {
    const CHILD_ROOT: &str = "HEPTA_RELEASE_CRASH_TEST_ROOT";
    const CHILD_PHASE: &str = "HEPTA_RELEASE_CRASH_TEST_PHASE";
    if let Some(root_record) = std::env::var_os(CHILD_ROOT) {
        let fixture = Fixture::new()?;
        let phase: u32 = std::env::var(CHILD_PHASE)?.parse()?;
        let publication = fixture.begin()?;
        if phase >= 1 {
            publication.rename()?;
        }
        if phase >= 2 {
            publication.seal_and_validate(&fixture.manifest_hash)?;
        }
        std::fs::write(
            root_record,
            fixture
                .registry
                .layout()
                .fleet_root()
                .as_path()
                .as_os_str()
                .as_encoded_bytes(),
        )?;
        // Terminate without unwinding or running any publication/tempdir Drop.
        std::process::exit(/*code*/ 86);
    }
    for phase in 0..3 {
        let temporary = tempfile::tempdir()?;
        let root_record = temporary.path().join("crashed-root");
        let status = std::process::Command::new(std::env::current_exe()?)
            .args([
                "--exact",
                "release::publication::tests::crashed_publication_stays_quarantined_after_reopen",
            ])
            .env(CHILD_ROOT, &root_record)
            .env(CHILD_PHASE, phase.to_string())
            .env("TMPDIR", temporary.path())
            .status()?;
        assert_eq!(status.code(), Some(86));
        let root = HeptaFleetRoot::parse(std::fs::read_to_string(&root_record)?)?;
        let registry = FleetRegistry::open_existing(root)?;
        // Process termination releases the live writer lock without clearing
        // the durable admission fence belonging to its unfinished candidate.
        let catalog_lock = File::open(registry.layout().releases_root())?;
        catalog_lock.try_lock().map_err(std::io::Error::from)?;
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        let release = ReleaseId::parse("candidate")?;
        assert!(registry.allow_release(&agent, &release).is_err());
        assert!(registry.resolve_release(&agent, &release).is_err());
        assert!(
            std::fs::symlink_metadata(pending_install_path(
                registry.layout().releases_root(),
                &release
            ))
            .is_ok()
        );
        for path in [".staging-test", "candidate"] {
            make_tree_removable(&registry.layout().releases_root().join(path));
        }
    }
    Ok(())
}

#[test]
fn unwinding_cancellation_keeps_the_fence() -> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let publication = fixture.begin()?;
    assert!(
        std::panic::catch_unwind(|| {
            publication.rename().expect("rename candidate");
            drop(publication);
            panic!("cancel publication before sealing");
        })
        .is_err()
    );
    fixture.assert_quarantined()
}

#[test]
fn stale_installer_preflight_cannot_refence_a_committed_winner()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let catalog = fixture.registry.layout().releases_root();
    let destination = catalog.join(fixture.release.as_str());
    // The contender's public preflight passed before the winner began.
    require_absent_release(&destination, &fixture.release)?;
    let winner = fixture.begin()?;
    assert!(
        matches!(fixture.begin(), Err(FleetRegistryError::Io(error)) if error.kind() == ErrorKind::WouldBlock)
    );
    winner.rename()?;
    let expected = winner.seal_and_validate(&fixture.manifest_hash)?;
    winner.commit(sync_directory)?;
    // After the winner unlinks its fence, the stale contender must recheck
    // under the OS lock before creating any new durable fence.
    assert!(matches!(
        fixture.begin(),
        Err(FleetRegistryError::Invalid(_))
    ));
    assert!(!pending_install_path(catalog, &fixture.release).exists());
    assert_eq!(
        fixture
            .registry
            .resolve_release(&fixture.agent, &fixture.release)?,
        expected
    );
    Ok(())
}

#[test]
fn concurrent_reader_and_installer_cannot_admit_pending_candidate()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let publication = fixture.begin()?;
    std::thread::scope(|scope| -> Result<(), FleetRegistryError> {
        let (phase_tx, phase_rx) = std::sync::mpsc::channel();
        let (checked_tx, checked_rx) = std::sync::mpsc::channel();
        let reader = &fixture;
        scope.spawn(move || {
            for _ in phase_rx {
                assert!(
                    reader
                        .registry
                        .resolve_release(&reader.agent, &reader.release)
                        .is_err()
                );
                assert!(
                    reader
                        .registry
                        .allow_release(&reader.agent, &reader.release)
                        .is_err()
                );
                assert!(
                    reader
                        .registry
                        .install_release(
                            reader.release.clone(),
                            &reader._temp.path().join("source"),
                            Vec::new(),
                        )
                        .is_err()
                );
                checked_tx.send(()).expect("report rejection");
            }
        });
        for phase in 0..3 {
            if phase == 1 {
                publication.rename()?;
            }
            if phase == 2 {
                publication.seal_and_validate(&fixture.manifest_hash)?;
            }
            phase_tx.send(()).expect("check pending phase");
            checked_rx.recv().expect("reader checked pending phase");
        }
        drop(phase_tx);
        Ok(())
    })?;
    publication.commit(sync_directory)?;
    fixture
        .registry
        .resolve_release(&fixture.agent, &fixture.release)?;
    Ok(())
}

#[test]
fn original_manifest_programs_and_modes_are_rechecked() -> Result<(), Box<dyn std::error::Error>> {
    for target in ["manifest", "agentd", "matrixd", "mode", "extra", "symlink"] {
        let fixture = Fixture::new()?;
        let publication = fixture.begin()?;
        publication.rename()?;
        let root = &publication.destination;
        match target {
            "manifest" => {
                let manifest = root.join(RELEASE_MANIFEST_FILE);
                let mut metadata: ReleaseMetadata =
                    read_bounded_json(&manifest, MAX_RELEASE_MANIFEST_BYTES)?;
                metadata.agentd.args = vec!["--substituted".to_owned()];
                set_mode(&manifest, /*mode*/ 0o644)?;
                std::fs::write(&manifest, serde_json::to_vec(&metadata)?)?;
                set_mode(&manifest, /*mode*/ 0o444)?;
                // The replacement is internally consistent; only binding the
                // installer's original manifest detects this substitution.
            }
            "agentd" | "matrixd" => {
                let program = root.join(format!("bin/hepta-{target}"));
                set_mode(&program, /*mode*/ 0o755)?;
                std::fs::write(&program, b"substituted executable")?;
                set_mode(&program, /*mode*/ 0o555)?;
            }
            "mode" => set_mode(&root.join(RELEASE_MANIFEST_FILE), /*mode*/ 0o555)?,
            "extra" => std::fs::write(root.join("unexpected"), b"extra")?,
            "symlink" => {
                set_mode(&root.join("bin"), /*mode*/ 0o755)?;
                std::fs::remove_file(root.join(AGENTD_RELEASE_PROGRAM))?;
                symlink(
                    fixture._temp.path().join("source"),
                    root.join(AGENTD_RELEASE_PROGRAM),
                )?;
                set_mode(&root.join("bin"), /*mode*/ 0o555)?;
            }
            _ => unreachable!(),
        }
        assert!(
            publication
                .seal_and_validate(&fixture.manifest_hash)
                .is_err()
        );
        fixture.assert_quarantined()?;
    }
    Ok(())
}

#[test]
fn replaced_directory_is_not_sealed_or_committed() -> Result<(), Box<dyn std::error::Error>> {
    for sealed in [false, true] {
        let fixture = Fixture::new()?;
        let publication = fixture.begin()?;
        publication.rename()?;
        if sealed {
            publication.seal_and_validate(&fixture.manifest_hash)?;
        }
        set_mode(&publication.destination, /*mode*/ 0o755)?;
        std::fs::rename(
            &publication.destination,
            publication.catalog.join("displaced"),
        )?;
        std::fs::create_dir(&publication.destination)?;
        set_mode(&publication.destination, /*mode*/ 0o755)?;
        assert!(
            publication
                .seal_and_validate(&fixture.manifest_hash)
                .is_err()
        );
        assert_eq!(
            std::fs::metadata(&publication.destination)?
                .permissions()
                .mode()
                & 0o777,
            0o755
        );
        assert!(publication.commit(sync_directory).is_err());
        fixture.assert_quarantined()?;
    }
    Ok(())
}

#[test]
fn durability_failure_distinguishes_precommit_from_committed_uncertainty()
-> Result<(), Box<dyn std::error::Error>> {
    for failed_sync in 1..=2 {
        let fixture = Fixture::new()?;
        let publication = fixture.begin()?;
        publication.rename()?;
        let expected = publication.seal_and_validate(&fixture.manifest_hash)?;
        let calls = Cell::new(/*value*/ 0);
        let result = publication.commit(|path| {
            calls.set(calls.get() + 1);
            if calls.get() == failed_sync {
                return Err(std::io::Error::other("injected catalog fsync failure").into());
            }
            sync_directory(path)
        });
        if failed_sync == 1 {
            assert!(matches!(result, Err(FleetRegistryError::Io(_))));
            fixture.assert_quarantined()?;
        } else {
            assert!(matches!(
                result,
                Err(FleetRegistryError::ReleasePublicationDurabilityUncertain { .. })
            ));
            assert_eq!(
                fixture
                    .registry
                    .resolve_release(&fixture.agent, &fixture.release)?,
                expected
            );
            assert!(
                !pending_install_path(fixture.registry.layout().releases_root(), &fixture.release)
                    .exists()
            );
        }
    }
    Ok(())
}

#[test]
fn any_pending_entry_including_dangling_symlink_denies_admission()
-> Result<(), Box<dyn std::error::Error>> {
    for entry in ["file", "directory", "symlink"] {
        let fixture = Fixture::new()?;
        publish(
            fixture.registry.layout().releases_root(),
            &fixture.staging,
            &fixture.release,
            &fixture.manifest_hash,
        )?;
        let fence =
            pending_install_path(fixture.registry.layout().releases_root(), &fixture.release);
        match entry {
            "file" => std::fs::write(&fence, b"")?,
            "directory" => std::fs::create_dir(&fence)?,
            "symlink" => symlink("missing-target", &fence)?,
            _ => unreachable!(),
        }
        fixture.assert_quarantined()?;
    }
    Ok(())
}

#[test]
fn pending_fence_does_not_reserve_legacy_release_names() -> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let legacy_name = ReleaseId::parse(".pending-install-candidate")?;
    fixture.registry.install_release(
        legacy_name.clone(),
        &fixture._temp.path().join("source"),
        Vec::new(),
    )?;
    let catalog = fixture.registry.layout().releases_root();
    publish(
        catalog,
        &fixture.staging,
        &fixture.release,
        &fixture.manifest_hash,
    )?;
    resolve_catalog_release(catalog, &fixture.release)?;
    resolve_catalog_release(catalog, &legacy_name)?;
    make_tree_removable(&catalog.join(legacy_name.as_str()));
    Ok(())
}
