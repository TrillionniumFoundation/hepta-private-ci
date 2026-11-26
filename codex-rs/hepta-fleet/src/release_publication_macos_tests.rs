use std::fs;
use std::fs::Permissions;
use std::io;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::super::*;
use super::Publication;
use super::create_staging;
use crate::AgentManifest;
use crate::ResourceBudget;
use crate::WorkspaceBinding;

struct Fixture {
    temp: TempDir,
    registry: FleetRegistry,
    agent: AgentId,
    release: ReleaseId,
    staging: PathBuf,
    final_root: PathBuf,
    allowance: PathBuf,
}

impl Fixture {
    fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let temp = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(temp.path().join("fleet"))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let workspace = temp.path().join("workspace");
        fs::create_dir(&workspace)?;
        let agent = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd3")?;
        let record = registry.register(AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
            ResourceBudget::local_default(),
        )?)?;
        let release = ReleaseId::parse("macos-publication")?;
        let staging = registry.layout().releases_root().join(".staging-fixture");
        let final_root = registry.layout().releases_root().join(release.as_str());
        let allowance = allowance_path(record.layout.releases_root(), &release);
        create_staging(&staging)?;
        let bin = staging.join("bin");
        fs::create_dir(&bin)?;
        let source = temp.path().join("source");
        fs::write(&source, b"#!/bin/sh\nexit 0\n")?;
        let program = staging.join(AGENTD_RELEASE_PROGRAM);
        copy_immutable_program(&source, &program)?;
        let metadata = ReleaseMetadata {
            schema_version: RELEASE_METADATA_SCHEMA_VERSION,
            release_id: release.clone(),
            agentd: ReleaseProgramMetadata {
                program_relative_path: PathBuf::from(AGENTD_RELEASE_PROGRAM),
                program_sha256: sha256_file(&program)?,
                program_size_bytes: fs::metadata(&program)?.len(),
                args: vec!["--fixed".to_string()],
            },
            matrixd: None,
        };
        let manifest = staging.join(RELEASE_MANIFEST_FILE);
        write_new_json(&manifest, &metadata)?;
        set_mode(&manifest, /*mode*/ 0o444)?;
        set_mode(&bin, /*mode*/ 0o555)?;
        sync_directory(&bin)?;
        sync_directory(&staging)?;
        Ok(Self {
            temp,
            registry,
            agent,
            release,
            staging,
            final_root,
            allowance,
        })
    }

    fn assert_pending_rejected(&self) -> Result<(), Box<dyn std::error::Error>> {
        assert_eq!(
            fs::metadata(&self.final_root)?.permissions().mode() & 0o777,
            0o700
        );
        assert!(matches!(
            resolve_catalog_release(self.registry.layout().releases_root(), &self.release),
            Err(FleetRegistryError::Corrupt(_))
        ));
        assert!(matches!(
            self.registry.allow_release(&self.agent, &self.release),
            Err(FleetRegistryError::Corrupt(_))
        ));
        assert!(!self.allowance.exists());
        Ok(())
    }

    fn cleanup(self) -> io::Result<()> {
        // Only the two paths created by this fixture, after every observation.
        make_tree_removable(&self.staging);
        make_tree_removable(&self.final_root);
        self.temp.close()
    }
}

#[test]
fn rename_failure_keeps_existing_destination_and_cleans_only_staging()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    fs::create_dir(&fixture.final_root)?;
    let sentinel = fixture.final_root.join("existing");
    fs::write(&sentinel, b"existing destination")?;
    let before_metadata = fs::symlink_metadata(&fixture.final_root)?;
    let before = (
        fs::read(&sentinel)?,
        before_metadata.dev(),
        before_metadata.ino(),
        before_metadata.mode(),
    );
    let mut publication = Publication::default();
    let mut seal_called = false;
    let result = publication.publish_with_seal(&fixture.staging, &fixture.final_root, |_| {
        seal_called = true;
        Ok(())
    });
    assert!(result.is_err());
    assert!(!seal_called);
    assert!(!publication.renamed);
    publication.cleanup_staging(&fixture.staging);
    assert!(!fixture.staging.exists());
    let after_metadata = fs::symlink_metadata(&fixture.final_root)?;
    assert_eq!(
        (
            fs::read(&sentinel)?,
            after_metadata.dev(),
            after_metadata.ino(),
            after_metadata.mode(),
        ),
        before
    );
    assert!(!fixture.allowance.exists());
    fixture.cleanup()?;
    Ok(())
}

#[test]
fn seal_failure_preserves_rejected_pending_release_and_reused_staging_name()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let manifest_before = fs::read(fixture.staging.join(RELEASE_MANIFEST_FILE))?;
    let program_before = fs::read(fixture.staging.join(AGENTD_RELEASE_PROGRAM))?;
    let mut publication = Publication::default();
    let result = publication.publish_with_seal(&fixture.staging, &fixture.final_root, |_| {
        assert!(!fixture.staging.exists());
        fs::create_dir(&fixture.staging)?;
        fs::write(fixture.staging.join("reused"), b"new staging occupant")?;
        Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "injected seal failure",
        ))
    });
    match result {
        Err(FleetRegistryError::Io(error)) => {
            assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
            assert_eq!(error.to_string(), "injected seal failure");
        }
        other => panic!("expected original seal error, got {other:?}"),
    }
    assert!(publication.renamed);
    publication.cleanup_staging(&fixture.staging);
    fixture.assert_pending_rejected()?;
    assert_eq!(
        fs::read(fixture.staging.join("reused"))?,
        b"new staging occupant"
    );
    assert_eq!(
        fs::read(fixture.final_root.join(RELEASE_MANIFEST_FILE))?,
        manifest_before
    );
    assert_eq!(
        fs::read(fixture.final_root.join(AGENTD_RELEASE_PROGRAM))?,
        program_before
    );
    fixture.cleanup()?;
    Ok(())
}

#[test]
fn sealed_publication_becomes_resolvable_and_allowable_after_pending_rejection()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new()?;
    let expected = RegisteredRelease {
        release_id: fixture.release.clone(),
        program: fixture.final_root.join(AGENTD_RELEASE_PROGRAM),
        args: vec!["--fixed".to_string()],
        matrixd: None,
    };
    let mut publication = Publication::default();
    publication.publish_with_seal(&fixture.staging, &fixture.final_root, |directory| {
        fixture
            .assert_pending_rejected()
            .map_err(|error| io::Error::other(error.to_string()))?;
        directory.set_permissions(Permissions::from_mode(/*mode*/ 0o555))
    })?;
    sync_directory(fixture.registry.layout().releases_root())?;
    assert!(!fixture.staging.exists());
    assert_eq!(
        resolve_catalog_release(fixture.registry.layout().releases_root(), &fixture.release)?,
        expected
    );
    assert!(!fixture.allowance.exists());
    fixture
        .registry
        .allow_release(&fixture.agent, &fixture.release)?;
    assert_eq!(
        fixture
            .registry
            .resolve_release(&fixture.agent, &fixture.release)?,
        expected
    );
    let binding = fixture
        .registry
        .resolve_release_binding(&fixture.agent, &fixture.release)?;
    assert_eq!(
        binding.manifest_sha256,
        sha256_file(&fixture.final_root.join(RELEASE_MANIFEST_FILE))?
    );
    assert_eq!(
        binding.agentd_program_sha256,
        sha256_file(&expected.program)?
    );
    fixture.cleanup()?;
    Ok(())
}
