use std::error::Error;
use std::os::unix::fs::symlink;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;

use super::*;
use crate::AgentManifest;
use crate::FleetRegistry;
use crate::ResourceBudget;
use crate::WorkspaceBinding;

struct Fixture {
    temp: tempfile::TempDir,
    registry: FleetRegistry,
    agent: AgentId,
    release_id: ReleaseId,
    source: PathBuf,
}

impl Fixture {
    fn new() -> Result<Self, Box<dyn Error>> {
        let temp = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(temp.path().join("fleet"))?;
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
        std::fs::write(&source, b"#!/bin/sh\nexit 0\n")?;
        Ok(Self {
            temp,
            registry,
            agent,
            release_id: ReleaseId::parse("publication")?,
            source,
        })
    }

    fn final_root(&self) -> PathBuf {
        self.registry
            .layout()
            .releases_root()
            .join(self.release_id.as_str())
    }

    fn prepared(&self, name: &str) -> Result<Publication, Box<dyn Error>> {
        let catalog = self.registry.layout().releases_root();
        let staging = catalog.join(name);
        let publication = Publication::create(catalog, &staging)?;
        let bin = staging.join("bin");
        std::fs::create_dir(&bin)?;
        let program = staging.join(super::super::AGENTD_RELEASE_PROGRAM);
        super::super::copy_immutable_program(&self.source, &program)?;
        let metadata = super::super::ReleaseMetadata {
            schema_version: super::super::RELEASE_METADATA_SCHEMA_VERSION,
            release_id: self.release_id.clone(),
            agentd: super::super::ReleaseProgramMetadata {
                program_relative_path: PathBuf::from(super::super::AGENTD_RELEASE_PROGRAM),
                program_sha256: super::super::sha256_file(&program)?,
                program_size_bytes: std::fs::metadata(&program)?.len(),
                args: Vec::new(),
            },
            matrixd: None,
        };
        let manifest = staging.join(super::super::RELEASE_MANIFEST_FILE);
        super::super::write_new_json(&manifest, &metadata)?;
        super::super::set_mode(&manifest, /*mode*/ 0o444)?;
        super::super::set_mode(&bin, /*mode*/ 0o555)?;
        super::super::sync_directory(&bin)?;
        super::super::sync_directory(&staging)?;
        Ok(publication)
    }

    fn assert_unsealed_rejected(&self) -> Result<(), Box<dyn Error>> {
        assert!(matches!(
            super::super::resolve_catalog_release(
                self.registry.layout().releases_root(),
                &self.release_id
            ),
            Err(FleetRegistryError::Corrupt(_))
        ));
        assert!(matches!(
            self.registry.allow_release(&self.agent, &self.release_id),
            Err(FleetRegistryError::Corrupt(_))
        ));
        // Install a test-owned exact allowance to exercise downstream gates,
        // rather than allowing an earlier missing-marker rejection to hide them.
        let record = self
            .registry
            .load()?
            .agent(&self.agent)
            .ok_or("missing agent")?
            .clone();
        let marker = super::super::allowance_path(record.layout.releases_root(), &self.release_id);
        if !marker.exists() {
            super::super::write_new_json(
                &marker,
                &super::super::ReleaseAllowance {
                    schema_version: super::super::RELEASE_METADATA_SCHEMA_VERSION,
                    agent_id: self.agent.clone(),
                    release_id: self.release_id.clone(),
                    manifest_sha256: super::super::sha256_file(
                        &self.final_root().join(super::super::RELEASE_MANIFEST_FILE),
                    )?,
                },
            )?;
            super::super::set_mode(&marker, /*mode*/ 0o444)?;
        }
        assert!(matches!(
            self.registry.resolve_release(&self.agent, &self.release_id),
            Err(FleetRegistryError::Corrupt(_))
        ));
        assert!(matches!(
            self.registry
                .resolve_release_binding(&self.agent, &self.release_id),
            Err(FleetRegistryError::Corrupt(_))
        ));
        assert!(matches!(
            self.registry.allowed_releases(&self.agent),
            Err(FleetRegistryError::Corrupt(_))
        ));
        Ok(())
    }
}

#[test]
fn darwin_readonly_directory_rename_denial_is_not_retried() -> Result<(), Box<dyn Error>> {
    let temp = tempfile::tempdir()?;
    let denied = temp.path().join("denied");
    std::fs::create_dir(&denied)?;
    assert_ne!(
        std::fs::metadata(&denied)?.uid(),
        0,
        "requires the normal-user native runner"
    );
    super::super::set_mode(&denied, /*mode*/ 0o555)?;
    let before = std::fs::symlink_metadata(&denied)?;
    let error = std::fs::rename(&denied, temp.path().join("not-published")).unwrap_err();
    assert_eq!(error.raw_os_error(), Some(13));
    assert_eq!(
        identity(&std::fs::symlink_metadata(&denied)?)?,
        identity(&before)?
    );
    assert_eq!(std::fs::metadata(&denied)?.mode() & 0o777, 0o555);
    assert!(!temp.path().join("not-published").exists());
    // Different newly owned fixture: no chmod or retry of the denied directory.
    let writable = temp.path().join("writable");
    let publication = Publication::create(temp.path(), &writable)?;
    publication.publish_unsealed(&temp.path().join("published"))?;
    publication.seal(&temp.path().join("published"))?;
    Ok(())
}

#[test]
fn published_unsealed_release_is_corrupt_until_owned_handle_seal() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let publication = fixture.prepared(".prepared")?;
    verify_prepared(&publication.staging_path, &fixture.release_id)?;
    publication.publish_unsealed(&fixture.final_root())?;
    fixture.assert_unsealed_rejected()?;
    verify_prepared(&fixture.final_root(), &fixture.release_id)?;
    publication.seal(&fixture.final_root())?;
    let resolved = fixture
        .registry
        .resolve_release(&fixture.agent, &fixture.release_id)?;
    assert_eq!(
        std::fs::read(&resolved.program)?,
        std::fs::read(&fixture.source)?
    );
    assert!(
        fixture
            .registry
            .resolve_release_binding(&fixture.agent, &fixture.release_id)
            .is_ok()
    );
    Ok(())
}

#[test]
fn interrupted_unsealed_slot_is_retained_and_never_adopted() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let publication = fixture.prepared(".interrupted")?;
    publication.publish_unsealed(&fixture.final_root())?;
    drop(publication); // Simulated process interruption before seal, no cleanup.
    let before = identity(&std::fs::symlink_metadata(fixture.final_root())?)?;
    fixture.assert_unsealed_rejected()?;
    assert!(
        fixture
            .registry
            .install_release(fixture.release_id.clone(), &fixture.source, Vec::new())
            .is_err()
    );
    assert_eq!(
        identity(&std::fs::symlink_metadata(fixture.final_root())?)?,
        before
    );
    assert_eq!(
        std::fs::metadata(fixture.final_root())?.mode() & 0o777,
        0o700
    );
    Ok(())
}

#[test]
fn no_replace_preserves_existing_empty_full_and_symlink_targets() -> Result<(), Box<dyn Error>> {
    for kind in ["empty", "full", "symlink"] {
        let fixture = Fixture::new()?;
        let publication = fixture.prepared(".collision")?;
        let target = fixture.final_root();
        if kind == "symlink" {
            symlink(&fixture.source, &target)?;
        } else {
            std::fs::create_dir(&target)?;
            if kind == "full" {
                std::fs::write(target.join("sentinel"), b"unchanged")?;
            }
        }
        let before = std::fs::symlink_metadata(&target)?;
        let error = publication.publish(&target).unwrap_err();
        assert!(
            matches!(error, FleetRegistryError::Io(ref error) if error.kind() == std::io::ErrorKind::AlreadyExists)
        );
        let after = std::fs::symlink_metadata(&target)?;
        assert_eq!(
            (before.dev(), before.ino(), before.mode(), before.uid()),
            (after.dev(), after.ino(), after.mode(), after.uid())
        );
        assert!(publication.staging_path.exists());
        assert_eq!(std::fs::read(&fixture.source)?, b"#!/bin/sh\nexit 0\n");
        if kind == "full" {
            assert_eq!(std::fs::read(target.join("sentinel"))?, b"unchanged");
        }
        if kind == "symlink" {
            assert_eq!(std::fs::read_link(&target)?, fixture.source);
        }
    }
    Ok(())
}

#[test]
fn two_prepared_installers_have_one_winner_without_clobber() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let first = fixture.prepared(".first")?;
    let second = fixture.prepared(".second")?;
    first.publish(&fixture.final_root())?;
    let before = std::fs::symlink_metadata(fixture.final_root())?;
    let bytes = std::fs::read(
        fixture
            .final_root()
            .join(super::super::RELEASE_MANIFEST_FILE),
    )?;
    assert!(
        matches!(second.publish(&fixture.final_root()), Err(FleetRegistryError::Io(ref error)) if error.kind() == std::io::ErrorKind::AlreadyExists)
    );
    assert_eq!(
        identity(&std::fs::symlink_metadata(fixture.final_root())?)?,
        identity(&before)?
    );
    assert_eq!(
        std::fs::read(
            fixture
                .final_root()
                .join(super::super::RELEASE_MANIFEST_FILE)
        )?,
        bytes
    );
    assert_eq!(
        std::fs::metadata(fixture.final_root())?.mode() & 0o777,
        0o555
    );
    Ok(())
}

#[test]
fn replaced_final_path_is_not_chmodded_or_removed() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let publication = fixture.prepared(".replacement")?;
    publication.publish_unsealed(&fixture.final_root())?;
    let moved = fixture.temp.path().join("owned-moved");
    std::fs::rename(fixture.final_root(), &moved)?;
    std::fs::create_dir(fixture.final_root())?;
    super::super::set_mode(&fixture.final_root(), /*mode*/ 0o755)?;
    std::fs::write(fixture.final_root().join("foreign"), b"untouched")?;
    let before = std::fs::symlink_metadata(fixture.final_root())?;
    assert!(matches!(
        publication.seal(&fixture.final_root()),
        Err(FleetRegistryError::Corrupt(_))
    ));
    assert_eq!(
        identity(&std::fs::symlink_metadata(fixture.final_root())?)?,
        identity(&before)?
    );
    assert_eq!(
        std::fs::metadata(fixture.final_root())?.mode() & 0o777,
        0o755
    );
    assert_eq!(
        std::fs::read(fixture.final_root().join("foreign"))?,
        b"untouched"
    );
    assert_eq!(std::fs::metadata(moved)?.mode() & 0o777, 0o700);
    Ok(())
}

#[test]
fn replaced_staging_is_rejected_before_publication() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let publication = fixture.prepared(".staging-replacement")?;
    std::fs::rename(
        &publication.staging_path,
        fixture.temp.path().join("owned-moved"),
    )?;
    std::fs::create_dir(&publication.staging_path)?;
    let before = identity(&std::fs::symlink_metadata(&publication.staging_path)?)?;
    assert!(publication.publish_unsealed(&fixture.final_root()).is_err());
    assert_eq!(
        identity(&std::fs::symlink_metadata(&publication.staging_path)?)?,
        before
    );
    assert!(!fixture.final_root().exists());
    Ok(())
}

#[test]
fn unexpected_prepared_entry_fails_before_publication() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let publication = fixture.prepared(".unexpected")?;
    std::fs::write(publication.staging_path.join("extra"), b"not admitted")?;
    assert!(matches!(
        publication.publish(&fixture.final_root()),
        Err(FleetRegistryError::Corrupt(_))
    ));
    assert!(!fixture.final_root().exists());
    assert_eq!(
        std::fs::metadata(&publication.staging_path)?.mode() & 0o777,
        0o700
    );
    Ok(())
}

#[test]
fn concurrent_no_replace_publications_choose_one_owned_inode() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let first = fixture.prepared(".concurrent-first")?;
    let second = fixture.prepared(".concurrent-second")?;
    let barrier = std::sync::Barrier::new(/*n*/ 2);
    let target = fixture.final_root();
    let results = std::thread::scope(|scope| {
        let left = scope.spawn(|| {
            barrier.wait();
            first.publish(&target)
        });
        let right = scope.spawn(|| {
            barrier.wait();
            second.publish(&target)
        });
        [
            left.join().expect("left installer panicked"),
            right.join().expect("right installer panicked"),
        ]
    });
    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(results.iter().filter(|result| matches!(result, Err(FleetRegistryError::Io(error)) if error.kind() == std::io::ErrorKind::AlreadyExists)).count(), 1);
    let installed_identity = identity(&std::fs::symlink_metadata(&target)?)?;
    assert!(
        installed_identity == first.directory_identity
            || installed_identity == second.directory_identity
    );
    super::super::resolve_catalog_release(
        fixture.registry.layout().releases_root(),
        &fixture.release_id,
    )?;
    assert_eq!(
        std::fs::read(target.join(super::super::AGENTD_RELEASE_PROGRAM))?,
        std::fs::read(&fixture.source)?
    );
    Ok(())
}

#[test]
fn changed_unsealed_mode_cannot_be_silently_repaired() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let publication = fixture.prepared(".mode-change")?;
    publication.publish_unsealed(&fixture.final_root())?;
    super::super::set_mode(&fixture.final_root(), /*mode*/ 0o755)?;
    assert!(matches!(
        publication.seal(&fixture.final_root()),
        Err(FleetRegistryError::Corrupt(_))
    ));
    assert_eq!(
        std::fs::metadata(fixture.final_root())?.mode() & 0o777,
        0o755
    );
    fixture.assert_unsealed_rejected()?;
    Ok(())
}

#[test]
fn symlink_replacement_before_seal_never_changes_target() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    let publication = fixture.prepared(".symlink-replacement")?;
    publication.publish_unsealed(&fixture.final_root())?;
    std::fs::rename(
        fixture.final_root(),
        fixture.temp.path().join("owned-moved"),
    )?;
    let foreign = fixture.temp.path().join("foreign-directory");
    std::fs::create_dir(&foreign)?;
    super::super::set_mode(&foreign, /*mode*/ 0o755)?;
    symlink(&foreign, fixture.final_root())?;
    let before = identity(&std::fs::symlink_metadata(&foreign)?)?;
    assert!(matches!(
        publication.seal(&fixture.final_root()),
        Err(FleetRegistryError::Corrupt(_))
    ));
    assert_eq!(identity(&std::fs::symlink_metadata(&foreign)?)?, before);
    assert_eq!(std::fs::metadata(foreign)?.mode() & 0o777, 0o755);
    assert!(
        std::fs::symlink_metadata(fixture.final_root())?
            .file_type()
            .is_symlink()
    );
    Ok(())
}

#[test]
fn failed_public_install_retains_only_its_unsealed_staging() -> Result<(), Box<dyn Error>> {
    let fixture = Fixture::new()?;
    // Empty owned input reaches private preseal V2 validation and fails there.
    // This exercises install_release's actual error path, not only helper steps.
    std::fs::write(&fixture.source, b"")?;
    let original_source = std::fs::symlink_metadata(&fixture.source)?;
    let catalog = fixture.registry.layout().releases_root();
    assert!(super::super::directory_names(catalog)?.is_empty());
    assert!(matches!(
        fixture
            .registry
            .install_release(fixture.release_id.clone(), &fixture.source, Vec::new(),),
        Err(FleetRegistryError::Corrupt(_))
    ));
    assert!(!fixture.final_root().exists());
    let names = super::super::directory_names(catalog)?;
    assert_eq!(names.len(), 1);
    let name = names.iter().next().ok_or("missing retained staging")?;
    assert!(name.starts_with(".staging-publication-"));
    let staging = catalog.join(name);
    assert_eq!(std::fs::metadata(staging)?.mode() & 0o777, 0o700);
    let after_source = std::fs::symlink_metadata(&fixture.source)?;
    assert_eq!(
        (
            original_source.dev(),
            original_source.ino(),
            original_source.mode()
        ),
        (after_source.dev(), after_source.ino(), after_source.mode()),
    );
    assert!(std::fs::read(&fixture.source)?.is_empty());
    Ok(())
}
